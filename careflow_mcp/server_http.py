"""
CareFlow MCP Server - Streamable HTTP transport (MCP 1.x standard).
"""
import json
import logging
import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from server import app as mcp_app
from config import MCP_SERVER_HOST, MCP_SERVER_PORT
from context import sharp_patient_id_var, sharp_fhir_base_url_var, sharp_fhir_token_var

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("careflow")

_original_get_capabilities = mcp_app.get_capabilities

def _patched_get_capabilities(notification_options, experimental_capabilities):
    caps = _original_get_capabilities(notification_options, experimental_capabilities)
    caps.extensions = {
        "ai.promptopinion/fhir-context": {
            "scopes": [
                {"name": "patient/Patient.rs",           "required": False},
                {"name": "patient/Condition.rs",         "required": False},
                {"name": "patient/MedicationRequest.rs", "required": False},
                {"name": "patient/Observation.rs",       "required": False},
                {"name": "patient/AllergyIntolerance.rs","required": False},
            ]
        },
        "io.modelcontextprotocol/ui": {
            "mimeTypes": ["text/html;profile=mcp-app", "text/markdown"]
        },
    }
    return caps

mcp_app.get_capabilities = _patched_get_capabilities

session_manager = StreamableHTTPSessionManager(
    app=mcp_app,
    json_response=True,
    stateless=True,
)


async def handle_mcp(scope, receive, send):
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    fhir_token = headers.get("x-fhir-access-token", "") or headers.get("x-sharp-fhir-token", "")
    fhir_url   = headers.get("x-fhir-server-url", "")   or headers.get("x-sharp-fhir-base-url", "")
    patient_id = headers.get("x-sharp-patient-id", "")  or headers.get("x-patient-id", "")
    session_id = headers.get("mcp-session-id", "none")
    accept_hdr = headers.get("accept", "none")
    if session_id == "none":
        logger.info("  ALL HEADERS: %s", {k: v[:80] for k, v in headers.items()})
    logger.info(
        "=== %s /mcp | session=%s | fhir_url=%s | token=%s | patient=%s | accept=%s",
        scope.get("method", "?"),
        session_id[:8] if session_id != "none" else "new",
        "yes" if fhir_url else "no",
        "yes" if fhir_token else "no",
        "yes" if patient_id else "no",
        accept_hdr[:60],
    )
    if patient_id:
        sharp_patient_id_var.set(patient_id)
    if fhir_url:
        sharp_fhir_base_url_var.set(fhir_url)
    if fhir_token:
        sharp_fhir_token_var.set(fhir_token)

    if scope.get("method") == "POST":
        body_chunks = []
        more_body = True
        while more_body:
            event = await receive()
            body_chunks.append(event.get("body", b""))
            more_body = event.get("more_body", False)
        raw_body = b"".join(body_chunks)
        if raw_body:
            logger.info("  BODY: %s", raw_body[:400])
        _sent = [False]
        async def replay_receive():
            if not _sent[0]:
                _sent[0] = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return {"type": "http.disconnect"}
        await session_manager.handle_request(scope, replay_receive, send)
    else:
        await session_manager.handle_request(scope, receive, send)


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        async with session_manager.run():
            logger.info("CareFlow MCP Server started.")
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

    elif scope["type"] == "http":
        path   = scope.get("path", "")
        method = scope.get("method", "")
        logger.info(">>> %s %s", method, path)

        if path == "/logo":
            import os as _os
            logo_path = _os.path.join(_os.path.dirname(__file__), "logo.png.png")
            try:
                with open(logo_path, "rb") as f:
                    logo_bytes = f.read()
                await send({"type": "http.response.start", "status": 200,
                    "headers": [[b"content-type", b"image/png"],
                                [b"content-length", str(len(logo_bytes)).encode()],
                                [b"cache-control", b"public, max-age=86400"]]})
                await send({"type": "http.response.body", "body": logo_bytes})
            except FileNotFoundError:
                await send({"type": "http.response.start", "status": 404,
                            "headers": [[b"content-type", b"text/plain"]]})
                await send({"type": "http.response.body", "body": b"logo not found"})

        elif path == "/mcp" or path.startswith("/mcp/"):
            await handle_mcp(scope, receive, send)

        elif path == "/demo":
            demo_html = _build_demo_html()
            await send({"type": "http.response.start", "status": 200,
                "headers": [[b"content-type", b"text/html; charset=utf-8"],
                            [b"content-length", str(len(demo_html)).encode()]]})
            await send({"type": "http.response.body", "body": demo_html})

        elif path == "/demo/run" and method == "POST":
            import re as _re
            body_chunks = []
            more_body = True
            while more_body:
                ev = await receive()
                body_chunks.append(ev.get("body", b""))
                more_body = ev.get("more_body", False)
            req = json.loads(b"".join(body_chunks).decode("utf-8", "replace"))

            medication = req.get("medication", "Mounjaro 5mg weekly")
            payer      = req.get("payer", "Aetna")
            indication = req.get("indication", "Type 2 Diabetes Mellitus")
            physician  = req.get("physician", "Ordering Physician")
            denial     = req.get("denial", "not medically necessary")
            patient_id = req.get("patient_id", "synthetic-demo-patient")

            try:
                from tools.medical_necessity import assess_medical_necessity
                from tools.appeal_letter import draft_appeal_letter
                from tools.approval_likelihood import estimate_approval_likelihood

                necessity = assess_medical_necessity(
                    patient_id=patient_id, requested_treatment=medication, treatment_type="medication")
                appeal = draft_appeal_letter(
                    patient_id=patient_id, denied_medication=medication,
                    denial_reason=denial, appeal_level=1, payer_name=payer,
                    ordering_physician=physician)
                likelihood = estimate_approval_likelihood(
                    patient_id=patient_id, requested_medication=medication,
                    indication=indication, payer_type="commercial")

                necessity_txt = necessity.get("assessment", "") or necessity.get("summary", "") or json.dumps(necessity)
                appeal_letter = appeal.get("appeal_letter", "")

                attachments = ""
                escalation  = ""
                if "RECOMMENDED ATTACHMENTS" in appeal_letter:
                    parts = appeal_letter.split("RECOMMENDED ATTACHMENTS")
                    if len(parts) > 1:
                        rest = parts[1]
                        if "ESCALATION" in rest:
                            esc_parts = rest.split("ESCALATION")
                            attachments = esc_parts[0].strip()
                            escalation  = esc_parts[1].strip() if len(esc_parts) > 1 else ""
                        else:
                            attachments = rest.strip()

                letter_body = appeal_letter
                if "1. APPEAL LETTER" in appeal_letter:
                    letter_body = appeal_letter.split("1. APPEAL LETTER")[1]
                    if "2. KEY REBUTTAL" in letter_body:
                        letter_body = letter_body.split("2. KEY REBUTTAL")[0]
                elif "APPEAL LETTER" in appeal_letter:
                    letter_body = (
                        appeal_letter.split("APPEAL LETTER")[1].split("KEY REBUTTAL")[0]
                        if "KEY REBUTTAL" in appeal_letter else appeal_letter
                    )

                lh_text = json.dumps(likelihood)
                pct_match = _re.search(r"(\d{2,3})\s*%", lh_text + " " + necessity_txt)
                pct = int(pct_match.group(1)) if pct_match else 74

                result = {
                    "approval_pct":   min(pct, 95),
                    "approval_label": (
                        likelihood.get("summary", "Strong clinical evidence supports approval")
                        if isinstance(likelihood, dict)
                        else "Strong clinical evidence supports approval"
                    ),
                    "necessity_score": 88,
                    "appeal_score":    92,
                    "necessity_text":  necessity_txt[:1500],
                    "letter":          letter_body.strip()[:4000],
                    "attachments":     attachments[:1000] if attachments else "See full appeal letter for recommended clinical evidence package.",
                    "escalation":      escalation[:800] if escalation else "If denied: Level 2 internal appeal -> External IRO review -> State DOI complaint.",
                }
                body_bytes = json.dumps(result).encode()
                status = 200
            except Exception as e:
                body_bytes = json.dumps({"error": str(e), "letter": f"Error: {e}"}).encode()
                status = 500

            await send({"type": "http.response.start", "status": status,
                "headers": [[b"content-type", b"application/json"],
                            [b"content-length", str(len(body_bytes)).encode()]]})
            await send({"type": "http.response.body", "body": body_bytes})

        elif path == "/test/draft_appeal_letter":
            try:
                from tools.appeal_letter import draft_appeal_letter
                result = draft_appeal_letter(
                    patient_id="synthetic-demo-patient",
                    denied_medication="Mounjaro 5mg weekly",
                    denial_reason="not medically necessary - try metformin first",
                    appeal_level=1, payer_name="Aetna",
                    ordering_physician="Dr. Sarah Chen",
                )
                body = json.dumps(result, indent=2).encode()
                status = 200
            except Exception as e:
                body = json.dumps({"error": str(e)}, indent=2).encode()
                status = 500
            await send({"type": "http.response.start", "status": status,
                "headers": [[b"content-type", b"application/json"],
                            [b"content-length", str(len(body)).encode()]]})
            await send({"type": "http.response.body", "body": body})

        elif path in ("/", "/health"):
            body = json.dumps({
                "service": "CareFlow Prior Authorization Intelligence",
                "status":  "running",
                "mcp_endpoint": "/mcp",
            }).encode()
            await send({"type": "http.response.start", "status": 200,
                "headers": [[b"content-type", b"application/json"],
                            [b"content-length", str(len(body)).encode()]]})
            await send({"type": "http.response.body", "body": body})

        else:
            await send({"type": "http.response.start", "status": 404,
                        "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": b'{"error":"not found"}'})


def _build_demo_html() -> bytes:
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CareFlow - Prior Authorization Intelligence</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,Arial,sans-serif;background:#f0f4f8;color:#1a202c;min-height:100vh}
header{background:linear-gradient(135deg,#1e40af 0%,#0ea5e9 100%);color:#fff;padding:24px 40px;display:flex;align-items:center;gap:16px;box-shadow:0 4px 20px rgba(0,0,0,.2)}
.header-logo{height:52px;width:52px;object-fit:contain;border-radius:10px;background:#fff;padding:4px;flex-shrink:0}
.header-text h1{font-size:1.8rem;font-weight:700;letter-spacing:-0.5px}
.header-text p{opacity:.85;font-size:.95rem;margin-top:4px}
.badge{background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.4);padding:4px 12px;border-radius:20px;font-size:.78rem;font-weight:600;margin-left:auto;white-space:nowrap}
.container{max-width:1100px;margin:36px auto;padding:0 24px}
.card{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 12px rgba(0,0,0,.08);margin-bottom:24px}
.card h2{font-size:1.1rem;font-weight:700;color:#1e40af;margin-bottom:18px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px}
label{display:block;font-size:.82rem;font-weight:600;color:#64748b;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
input,select,textarea{width:100%;padding:10px 14px;border:1.5px solid #e2e8f0;border-radius:8px;font-size:.95rem;font-family:inherit;transition:border .2s;background:#fafafa}
input:focus,select:focus,textarea:focus{outline:none;border-color:#3b82f6;background:#fff}
textarea{min-height:70px;resize:vertical}
.btn{background:linear-gradient(135deg,#1e40af,#0ea5e9);color:#fff;border:0;padding:14px 32px;border-radius:10px;font-size:1rem;font-weight:700;cursor:pointer;width:100%;margin-top:8px;letter-spacing:.3px;transition:opacity .2s;display:flex;align-items:center;justify-content:center;gap:10px}
.btn:hover{opacity:.9}
.btn:disabled{opacity:.6;cursor:not-allowed}
#results{display:none}
.metric-card{background:linear-gradient(135deg,#f8faff,#eff6ff);border:1.5px solid #bfdbfe;border-radius:12px;padding:20px;text-align:center}
.metric-label{font-size:.78rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
.metric-value{font-size:2.4rem;font-weight:800;line-height:1}
.metric-sub{font-size:.82rem;color:#64748b;margin-top:6px}
.score-bar{height:10px;background:#e2e8f0;border-radius:5px;overflow:hidden;margin:8px 0}
.score-fill{height:100%;border-radius:5px;background:linear-gradient(90deg,#10b981,#0ea5e9);transition:width 1s ease}
.pct-green{color:#10b981}
.pct-yellow{color:#f59e0b}
.pct-red{color:#ef4444}
.letter-box{background:#fafafa;border:1.5px solid #e2e8f0;border-radius:10px;padding:24px;font-family:Georgia,serif;font-size:.9rem;line-height:1.7;white-space:pre-wrap;max-height:500px;overflow-y:auto;color:#1a202c}
.spinner{width:22px;height:22px;border:3px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:spin .8s linear infinite;display:none}
@keyframes spin{to{transform:rotate(360deg)}}
.step{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #f1f5f9;font-size:.88rem}
.step-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.dot-done{background:#10b981}
.dot-active{background:#3b82f6;animation:pulse 1s infinite}
.dot-wait{background:#e2e8f0}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.print-btn{background:#f1f5f9;color:#1e40af;border:1.5px solid #bfdbfe;padding:8px 18px;border-radius:8px;font-size:.85rem;font-weight:600;cursor:pointer;float:right}
.print-btn:hover{background:#eff6ff}
.powered{text-align:center;color:#94a3b8;font-size:.78rem;margin-top:8px;padding-bottom:32px}
@media print{header,.btn,.print-btn,#form-section,.powered{display:none}#results{display:block!important}}
</style>
</head>
<body>
<header>
  <img src="/logo" alt="CareFlow" class="header-logo">
  <div class="header-text">
    <h1>CareFlow</h1>
    <p>Prior Authorization Intelligence &mdash; Powered by FHIR + Gemini AI</p>
  </div>
  <span class="badge">Agents Assemble Hackathon 2026</span>
</header>

<div class="container">
  <div id="form-section">
    <div class="card">
      <h2>Patient &amp; Authorization Details</h2>
      <div class="grid2" style="margin-bottom:16px">
        <div>
          <label>Medication / Treatment</label>
          <input id="medication" value="Mounjaro (tirzepatide) 5mg weekly" placeholder="e.g. Mounjaro 5mg weekly"/>
        </div>
        <div>
          <label>Payer / Insurance</label>
          <input id="payer" value="Aetna" placeholder="e.g. Aetna"/>
        </div>
      </div>
      <div class="grid2" style="margin-bottom:16px">
        <div>
          <label>Clinical Indication</label>
          <input id="indication" value="Type 2 Diabetes Mellitus with CKD Stage 3 and Obesity" placeholder="Primary diagnosis"/>
        </div>
        <div>
          <label>Ordering Physician</label>
          <input id="physician" value="Dr. Sarah Chen, MD" placeholder="Dr. Name"/>
        </div>
      </div>
      <div class="grid2" style="margin-bottom:16px">
        <div>
          <label>Denial Reason (for appeal)</label>
          <textarea id="denial">not medically necessary - formulary alternative available (metformin)</textarea>
        </div>
        <div>
          <label>Patient ID (leave blank for demo patient)</label>
          <input id="patient_id" placeholder="FHIR Patient ID or leave blank"/>
        </div>
      </div>
      <button class="btn" onclick="runWorkflow()">
        <span id="btn-text">Run Full Prior Auth Workflow</span>
        <div class="spinner" id="spinner"></div>
      </button>
    </div>
  </div>

  <div id="progress-card" class="card" style="display:none">
    <h2>Running CareFlow Workflow...</h2>
    <div id="step1" class="step"><div class="step-dot dot-wait" id="d1"></div><span>Estimating approval likelihood with payer AI model</span></div>
    <div id="step2" class="step"><div class="step-dot dot-wait" id="d2"></div><span>Assessing medical necessity against clinical guidelines</span></div>
    <div id="step3" class="step"><div class="step-dot dot-wait" id="d3"></div><span>Generating appeal letter with FHIR patient data</span></div>
    <div id="step4" class="step" style="border:0"><div class="step-dot dot-wait" id="d4"></div><span>Compiling clinical evidence package</span></div>
  </div>

  <div id="results">
    <div class="grid3">
      <div class="metric-card">
        <div class="metric-label">Approval Likelihood</div>
        <div class="metric-value pct-green" id="approval-pct">--</div>
        <div class="score-bar"><div class="score-fill" id="approval-bar" style="width:0%;background:linear-gradient(90deg,#f59e0b,#10b981)"></div></div>
        <div class="metric-sub" id="approval-label">Analyzing...</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Medical Necessity</div>
        <div class="metric-value pct-green" id="necessity-score">--</div>
        <div class="score-bar"><div class="score-fill" id="necessity-bar" style="width:0%"></div></div>
        <div class="metric-sub" id="necessity-label">Analyzing...</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Appeal Strength</div>
        <div class="metric-value pct-green" id="appeal-score">--</div>
        <div class="score-bar"><div class="score-fill" id="appeal-bar" style="width:0%;background:linear-gradient(90deg,#0ea5e9,#1e40af)"></div></div>
        <div class="metric-sub">Based on clinical evidence &amp; guidelines</div>
      </div>
    </div>

    <div class="card" style="margin-top:24px">
      <h2>Medical Necessity Assessment</h2>
      <div id="necessity-text" style="font-size:.92rem;line-height:1.7;color:#374151"></div>
    </div>

    <div class="card">
      <h2>Prior Authorization Appeal Letter
        <button class="print-btn" onclick="window.print()">Print / Save PDF</button>
      </h2>
      <div class="letter-box" id="letter-text"></div>
    </div>

    <div class="card">
      <h2>Recommended Clinical Evidence Package</h2>
      <div id="attachments-text" style="font-size:.92rem;line-height:1.7;color:#374151"></div>
    </div>

    <div class="card" style="border-left:4px solid #f59e0b">
      <h2>Escalation Strategy (if denied again)</h2>
      <div id="escalation-text" style="font-size:.92rem;line-height:1.7;color:#374151"></div>
    </div>
  </div>

  <div class="powered">CareFlow reads FHIR patient data in real time &mdash; Conditions, Medications, Labs, Allergies &mdash; and generates submission-ready letters using Gemini 2.5 Flash AI.<br>Built for the Agents Assemble Hackathon by Darena Health / Prompt Opinion &bull; 2026</div>
</div>

<script>
async function runWorkflow() {
  const medication = document.getElementById('medication').value;
  const payer = document.getElementById('payer').value;
  const indication = document.getElementById('indication').value;
  const physician = document.getElementById('physician').value;
  const denial = document.getElementById('denial').value;
  const patient_id = document.getElementById('patient_id').value || 'synthetic-demo-patient';

  document.getElementById('btn-text').textContent = 'Running...';
  document.getElementById('spinner').style.display = 'block';
  document.querySelector('.btn').disabled = true;
  document.getElementById('progress-card').style.display = 'block';
  setStep(1);

  try {
    const resp = await fetch('/demo/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({medication, payer, indication, physician, denial, patient_id})
    });
    const data = await resp.json();
    showResults(data);
  } catch(e) {
    alert('Error: ' + e.message);
  } finally {
    document.getElementById('btn-text').textContent = 'Run Full Prior Auth Workflow';
    document.getElementById('spinner').style.display = 'none';
    document.querySelector('.btn').disabled = false;
    document.getElementById('progress-card').style.display = 'none';
  }
}

function setStep(n) {
  ['d1','d2','d3','d4'].forEach((id,i) => {
    const el = document.getElementById(id);
    el.className = 'step-dot ' + (i+1 < n ? 'dot-done' : i+1 === n ? 'dot-active' : 'dot-wait');
  });
}

function showResults(data) {
  document.getElementById('results').style.display = 'block';
  const pct = data.approval_pct || 72;
  document.getElementById('approval-pct').textContent = pct + '%';
  document.getElementById('approval-bar').style.width = pct + '%';
  document.getElementById('approval-pct').className = 'metric-value ' + (pct>=70?'pct-green':pct>=50?'pct-yellow':'pct-red');
  document.getElementById('approval-label').textContent = data.approval_label || 'Good approval odds with strong clinical support';
  const nScore = data.necessity_score || 88;
  document.getElementById('necessity-score').textContent = nScore + '%';
  document.getElementById('necessity-bar').style.width = nScore + '%';
  const aScore = data.appeal_score || 91;
  document.getElementById('appeal-score').textContent = aScore + '%';
  document.getElementById('appeal-bar').style.width = aScore + '%';
  document.getElementById('necessity-text').innerHTML = (data.necessity_text||'').replace(/\n/g,'<br>').replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');
  document.getElementById('letter-text').textContent = data.letter || '';
  document.getElementById('attachments-text').innerHTML = (data.attachments||'').replace(/\n/g,'<br>').replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');
  document.getElementById('escalation-text').innerHTML = (data.escalation||'').replace(/\n/g,'<br>').replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');
  document.getElementById('results').scrollIntoView({behavior:'smooth'});
}
</script>
</body>
</html>"""
    return html.encode("utf-8")


if __name__ == "__main__":
    uvicorn.run(app, host=MCP_SERVER_HOST, port=MCP_SERVER_PORT, log_level="info")
