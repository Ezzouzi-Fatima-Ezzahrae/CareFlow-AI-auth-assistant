"""
CareFlow MCP Server - Streamable HTTP transport (MCP 1.x standard).
Reads Prompt Opinion FHIR context headers and injects into tool calls.
Declares ai.promptopinion/fhir-context extension via monkey-patched get_capabilities.
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
        # Declare FHIR context support – all scopes optional so Po will invoke
        # tools even when no patient is selected (we fall back to FHIR discovery
        # or synthetic data automatically).
        "ai.promptopinion/fhir-context": {
            "scopes": [
                {"name": "patient/Patient.rs",           "required": False},
                {"name": "patient/Condition.rs",         "required": False},
                {"name": "patient/MedicationRequest.rs", "required": False},
                {"name": "patient/Observation.rs",       "required": False},
                {"name": "patient/AllergyIntolerance.rs","required": False},
            ]
        },
        # Acknowledge Po's UI extension so it knows we can return HTML content.
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
    # Log ALL headers on first request of each session so we can see exactly
    # what Po is sending (useful for diagnosing missing patient/FHIR headers).
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
        # GET/DELETE: pass receive directly so SSE stream stays alive
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
                await send({"type":"http.response.start","status":200,
                    "headers":[[b"content-type",b"image/png"],[b"content-length",str(len(logo_bytes)).encode()],[b"cache-control",b"public, max-age=86400"]]})
                await send({"type":"http.response.body","body":logo_bytes})
            except FileNotFoundError:
                await send({"type":"http.response.start","status":404,"headers":[[b"content-type",b"text/plain"]]})
                await send({"type":"http.response.body","body":b"logo not found"})

        elif path == "/mcp" or path.startswith("/mcp/"):
            await handle_mcp(scope, receive, send)

        elif path == "/letter":
            # Browser form: pick tool, fill fields, get a styled letter back.
            html = b"""<!doctype html><meta charset=utf-8>
<title>CareFlow Letter Generator</title>
<style>
  body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:760px;margin:40px auto;padding:0 24px;color:#111}
  h1{font-weight:600;border-bottom:2px solid #2563eb;padding-bottom:8px}
  fieldset{border:1px solid #d4d4d8;border-radius:8px;padding:16px 20px;margin:18px 0;background:#fafafa}
  legend{font-weight:600;color:#2563eb;padding:0 8px}
  label{display:block;margin:10px 0 4px;font-size:14px;color:#374151}
  input,select,textarea{width:100%;padding:8px 10px;border:1px solid #d4d4d8;border-radius:6px;font-size:14px;font-family:inherit}
  textarea{min-height:60px}
  button{background:#2563eb;color:#fff;border:0;padding:10px 18px;border-radius:6px;font-size:15px;cursor:pointer;margin-top:8px}
  button:hover{background:#1d4ed8}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  small{color:#6b7280}
</style>
<h1>CareFlow Letter Generator</h1>
<p><small>Fills letters using the patient's FHIR clinical data when a patient ID is set.</small></p>

<form action="/letter/generate" method="POST">
  <fieldset>
    <legend>Letter type</legend>
    <select name="kind" required>
      <option value="appeal">Prior Authorization APPEAL Letter (after a denial)</option>
      <option value="prior_auth">Prior Authorization REQUEST Letter (initial submission)</option>
    </select>
    <label>Patient ID <small>(blank = synthetic demo patient)</small></label>
    <input name="patient_id" placeholder="e.g. Tamera164 or leave blank" />
  </fieldset>

  <fieldset>
    <legend>Common fields</legend>
    <div class=row>
      <div>
        <label>Medication / treatment</label>
        <input name="medication" required placeholder="Mounjaro 5mg weekly" />
      </div>
      <div>
        <label>Payer / insurer</label>
        <input name="payer_name" required placeholder="Aetna" />
      </div>
    </div>
    <label>Indication / diagnosis <small>(only used for prior-auth requests)</small></label>
    <input name="indication" placeholder="Type 2 Diabetes Mellitus" />
  </fieldset>

  <fieldset>
    <legend>Appeal-letter fields</legend>
    <label>Stated denial reason</label>
    <textarea name="denial_reason">not medically necessary - try metformin first</textarea>
    <div class=row>
      <div>
        <label>Appeal level</label>
        <select name="appeal_level"><option>1</option><option>2</option><option>3</option></select>
      </div>
      <div>
        <label>Ordering physician</label>
        <input name="ordering_physician" placeholder="Dr. Sarah Chen" />
      </div>
    </div>
  </fieldset>

  <button type="submit">Generate letter</button>
</form>
"""
            await send({"type":"http.response.start","status":200,
                "headers":[[b"content-type",b"text/html; charset=utf-8"],
                           [b"content-length",str(len(html)).encode()]]})
            await send({"type":"http.response.body","body":html})

        elif path == "/letter/generate" and method == "POST":
            # Read form-urlencoded body, dispatch the matching tool, render result as HTML.
            body_chunks = []
            more_body = True
            while more_body:
                ev = await receive()
                body_chunks.append(ev.get("body", b""))
                more_body = ev.get("more_body", False)
            raw_body = b"".join(body_chunks).decode("utf-8", "replace")

            from urllib.parse import parse_qs
            form = {k: v[0] if v else "" for k, v in parse_qs(raw_body, keep_blank_values=True).items()}

            kind = form.get("kind", "appeal")
            patient_id = form.get("patient_id", "").strip() or "synthetic-demo-patient"
            payer = form.get("payer_name", "Insurance Payer").strip() or "Insurance Payer"
            medication = form.get("medication", "").strip()

            try:
                if kind == "appeal":
                    from tools.appeal_letter import draft_appeal_letter
                    try:
                        level = int(form.get("appeal_level", "1") or "1")
                    except ValueError:
                        level = 1
                    result = draft_appeal_letter(
                        patient_id=patient_id,
                        denied_medication=medication,
                        denial_reason=form.get("denial_reason", "").strip() or "not medically necessary",
                        appeal_level=level,
                        payer_name=payer,
                        ordering_physician=form.get("ordering_physician", "").strip() or "Ordering Physician",
                    )
                    title = f"Level {level} Appeal Letter — {medication} ({payer})"
                    body_text = result.get("appeal_letter", "")
                else:
                    from tools.prior_auth import generate_prior_auth
                    result = generate_prior_auth(
                        patient_id=patient_id,
                        requested_medication=medication,
                        indication=form.get("indication", "").strip() or "(not specified)",
                        payer_name=payer,
                    )
                    title = f"Prior Authorization Request — {medication} ({payer})"
                    body_text = result.get("prior_auth_letter", "")

                # Escape the letter body for safe HTML rendering, preserve newlines.
                import html as _html
                safe_body = _html.escape(body_text).replace("\n", "<br>")
                page = (
                    "<!doctype html><meta charset=utf-8>"
                    "<title>" + _html.escape(title) + "</title>"
                    "<style>body{font-family:Georgia,'Times New Roman',serif;max-width:780px;margin:40px auto;padding:0 32px;line-height:1.55;color:#111}"
                    "h1{font-family:system-ui,sans-serif;color:#2563eb;border-bottom:2px solid #2563eb;padding-bottom:8px}"
                    "a{color:#2563eb}.actions{font-family:system-ui,sans-serif;margin:8px 0 24px}.actions a{margin-right:14px}"
                    "@media print{.actions{display:none}h1{border:0}}</style>"
                    "<h1>" + _html.escape(title) + "</h1>"
                    "<div class=actions><a href='/letter'>&larr; Back</a> <a href='#' onclick='window.print();return false'>Print / Save as PDF</a></div>"
                    "<div>" + safe_body + "</div>"
                )
                page_bytes = page.encode("utf-8")
                status = 200
            except Exception as e:
                page_bytes = (f"<pre>Error generating letter: {e}</pre>").encode("utf-8")
                status = 500

            await send({"type":"http.response.start","status":status,
                "headers":[[b"content-type",b"text/html; charset=utf-8"],
                           [b"content-length",str(len(page_bytes)).encode()]]})
            await send({"type":"http.response.body","body":page_bytes})

        elif path == "/test/draft_appeal_letter":
            # Direct test endpoint - bypasses MCP handshake entirely.
            # Useful for verifying the tool works end-to-end.
            try:
                from tools.appeal_letter import draft_appeal_letter
                result = draft_appeal_letter(
                    patient_id="synthetic-demo-patient",
                    denied_medication="Mounjaro 5mg weekly",
                    denial_reason="not medically necessary - try metformin first",
                    appeal_level=1,
                    payer_name="Demo Insurance",
                    ordering_physician="Dr. Demo Physician",
                )
                import html as _html
                body = _html.escape(result.get("appeal_letter", str(result))).replace("\n", "<br>")
                page = (
                    b"<!doctype html><meta charset=utf-8><title>Appeal Letter Test</title>"
                    b"<style>body{font-family:Georgia,serif;max-width:780px;margin:40px auto;padding:0 32px;line-height:1.55}</style>"
                    b"<h2>Test: draft_appeal_letter</h2><div>" + body.encode() + b"</div>"
                )
                await send({"type": "http.response.start", "status": 200,
                    "headers": [[b"content-type", b"text/html; charset=utf-8"],
                                [b"content-length", str(len(page)).encode()]]})
                await send({"type": "http.response.body", "body": page})
            except Exception as e:
                err = f"<pre>Error: {e}</pre>".encode()
                await send({"type": "http.response.start", "status": 500,
                    "headers": [[b"content-type", b"text/html"]]})
                await send({"type": "http.response.body", "body": err})

        elif path == "/demo":
            # Interactive demo page - shows all tools in a single UI
            html = b"""<!doctype html><meta charset=utf-8>
<title>CareFlow AI - Demo</title>
<style>
  *{box-sizing:border-box}
  body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#f8fafc;color:#111}
  header{background:#1e40af;color:#fff;padding:16px 32px;display:flex;align-items:center;gap:16px}
  header img{height:40px;border-radius:8px}
  header h1{margin:0;font-size:1.4rem;font-weight:700}
  header p{margin:0;font-size:0.85rem;opacity:0.85}
  .container{max-width:900px;margin:32px auto;padding:0 24px}
  .card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:24px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
  h2{font-size:1.1rem;font-weight:600;color:#1e40af;margin:0 0 16px}
  label{display:block;font-size:13px;font-weight:500;color:#374151;margin:10px 0 4px}
  input,select,textarea{width:100%;padding:8px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:14px;font-family:inherit}
  textarea{min-height:60px;resize:vertical}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  button{background:#1e40af;color:#fff;border:0;padding:10px 20px;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer;margin-top:12px}
  button:hover{background:#1d4ed8}
  button:disabled{background:#94a3b8;cursor:not-allowed}
  .result{margin-top:20px;padding:16px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;white-space:pre-wrap;font-family:Georgia,serif;font-size:14px;line-height:1.6;display:none}
  .result.show{display:block}
  .spinner{display:none;margin-top:12px;color:#6b7280;font-size:13px}
  .spinner.show{display:block}
  .tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
  .tab{padding:8px 16px;border:1px solid #d1d5db;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;background:#fff;color:#374151}
  .tab.active{background:#1e40af;color:#fff;border-color:#1e40af}
  .tool-panel{display:none}
  .tool-panel.active{display:block}
  .badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;margin-left:8px}
  .badge-green{background:#dcfce7;color:#166534}
  .badge-blue{background:#dbeafe;color:#1e40af}
  .badge-orange{background:#ffedd5;color:#9a3412}
</style>
<header>
  <img src="/logo" alt="CareFlow logo" onerror="this.style.display='none'">
  <div>
    <h1>CareFlow AI</h1>
    <p>Prior Authorization Intelligence — Interactive Demo</p>
  </div>
</header>
<div class=container>
  <div class=card>
    <div class=tabs>
      <div class="tab active" onclick="showTab('prior_auth')">Prior Auth Request</div>
      <div class=tab onclick="showTab('appeal')">Appeal Letter</div>
      <div class=tab onclick="showTab('necessity')">Medical Necessity</div>
      <div class=tab onclick="showTab('likelihood')">Approval Likelihood</div>
    </div>

    <!-- Prior Auth -->
    <div id=prior_auth class="tool-panel active">
      <h2>Generate Prior Authorization Request</h2>
      <label>Patient ID <small style="color:#6b7280">(leave blank for synthetic demo patient)</small></label>
      <input id=pa_patient placeholder="e.g. Tamera164 or leave blank">
      <div class=row>
        <div>
          <label>Medication / Treatment</label>
          <input id=pa_med value="Mounjaro 5mg weekly">
        </div>
        <div>
          <label>Payer</label>
          <input id=pa_payer value="Aetna">
        </div>
      </div>
      <label>Indication / Diagnosis</label>
      <input id=pa_indication value="Type 2 Diabetes Mellitus">
      <button onclick="runTool('prior_auth')">Generate Letter</button>
      <div class="spinner" id=prior_auth_spin>Generating... this may take 15-30 seconds</div>
      <div class="result" id=prior_auth_result></div>
    </div>

    <!-- Appeal -->
    <div id=appeal class=tool-panel>
      <h2>Draft Appeal Letter</h2>
      <label>Patient ID <small style="color:#6b7280">(leave blank for synthetic demo patient)</small></label>
      <input id=ap_patient placeholder="e.g. Tamera164 or leave blank">
      <div class=row>
        <div>
          <label>Denied Medication</label>
          <input id=ap_med value="Mounjaro 5mg weekly">
        </div>
        <div>
          <label>Payer</label>
          <input id=ap_payer value="Aetna">
        </div>
      </div>
      <label>Denial Reason</label>
      <textarea id=ap_reason>not medically necessary - try metformin first</textarea>
      <div class=row>
        <div>
          <label>Appeal Level</label>
          <select id=ap_level><option value=1>Level 1</option><option value=2>Level 2</option><option value=3>Level 3</option></select>
        </div>
        <div>
          <label>Ordering Physician</label>
          <input id=ap_physician value="Dr. Sarah Chen">
        </div>
      </div>
      <button onclick="runTool('appeal')">Draft Appeal Letter</button>
      <div class="spinner" id=appeal_spin>Generating... this may take 15-30 seconds</div>
      <div class="result" id=appeal_result></div>
    </div>

    <!-- Medical Necessity -->
    <div id=necessity class=tool-panel>
      <h2>Assess Medical Necessity</h2>
      <label>Patient ID <small style="color:#6b7280">(leave blank for synthetic demo patient)</small></label>
      <input id=mn_patient placeholder="e.g. Tamera164 or leave blank">
      <label>Requested Treatment</label>
      <input id=mn_treatment value="Mounjaro 5mg weekly">
      <label>Treatment Type</label>
      <select id=mn_type>
        <option value=medication>Medication</option>
        <option value=procedure>Procedure</option>
        <option value=dme>DME</option>
        <option value=referral>Referral</option>
      </select>
      <button onclick="runTool('necessity')">Assess Necessity</button>
      <div class="spinner" id=necessity_spin>Analyzing... this may take 15-30 seconds</div>
      <div class="result" id=necessity_result></div>
    </div>

    <!-- Approval Likelihood -->
    <div id=likelihood class=tool-panel>
      <h2>Estimate Approval Likelihood</h2>
      <label>Patient ID <small style="color:#6b7280">(leave blank for synthetic demo patient)</small></label>
      <input id=al_patient placeholder="e.g. Tamera164 or leave blank">
      <div class=row>
        <div>
          <label>Medication</label>
          <input id=al_med value="Mounjaro 5mg weekly">
        </div>
        <div>
          <label>Payer Type</label>
          <select id=al_payer_type>
            <option value=commercial>Commercial</option>
            <option value=medicare>Medicare</option>
            <option value=medicaid>Medicaid</option>
            <option value=medicare_advantage>Medicare Advantage</option>
          </select>
        </div>
      </div>
      <label>Indication</label>
      <input id=al_indication value="Type 2 Diabetes Mellitus">
      <button onclick="runTool('likelihood')">Estimate Likelihood</button>
      <div class="spinner" id=likelihood_spin>Analyzing... this may take 15-30 seconds</div>
      <div class="result" id=likelihood_result></div>
    </div>
  </div>
</div>

<script>
function showTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', ['prior_auth','appeal','necessity','likelihood'][i] === name));
  document.querySelectorAll('.tool-panel').forEach(p => p.classList.toggle('active', p.id === name));
}

async function runTool(tool) {
  const spin = document.getElementById(tool + '_spin');
  const result = document.getElementById(tool + '_result');
  spin.classList.add('show');
  result.classList.remove('show');

  let body = {};
  if (tool === 'prior_auth') {
    body = {tool: 'prior_auth', patient_id: document.getElementById('pa_patient').value,
      medication: document.getElementById('pa_med').value,
      payer: document.getElementById('pa_payer').value,
      indication: document.getElementById('pa_indication').value};
  } else if (tool === 'appeal') {
    body = {tool: 'appeal', patient_id: document.getElementById('ap_patient').value,
      medication: document.getElementById('ap_med').value,
      payer: document.getElementById('ap_payer').value,
      denial_reason: document.getElementById('ap_reason').value,
      appeal_level: parseInt(document.getElementById('ap_level').value),
      ordering_physician: document.getElementById('ap_physician').value};
  } else if (tool === 'necessity') {
    body = {tool: 'necessity', patient_id: document.getElementById('mn_patient').value,
      treatment: document.getElementById('mn_treatment').value,
      treatment_type: document.getElementById('mn_type').value};
  } else if (tool === 'likelihood') {
    body = {tool: 'likelihood', patient_id: document.getElementById('al_patient').value,
      medication: document.getElementById('al_med').value,
      indication: document.getElementById('al_indication').value,
      payer_type: document.getElementById('al_payer_type').value};
  }

  try {
    const resp = await fetch('/demo/run', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const data = await resp.json();
    result.textContent = data.text || JSON.stringify(data, null, 2);
    result.classList.add('show');
  } catch(e) {
    result.textContent = 'Error: ' + e.message;
    result.classList.add('show');
  }
  spin.classList.remove('show');
}
</script>
"""
            await send({"type": "http.response.start", "status": 200,
                "headers": [[b"content-type", b"text/html; charset=utf-8"],
                            [b"content-length", str(len(html)).encode()]]})
            await send({"type": "http.response.body", "body": html})

        elif path == "/demo/run" and method == "POST":
            # JSON API endpoint for the demo page
            body_chunks = []
            more_body = True
            while more_body:
                ev = await receive()
                body_chunks.append(ev.get("body", b""))
                more_body = ev.get("more_body", False)
            raw_body = b"".join(body_chunks)

            try:
                data = json.loads(raw_body)
                tool_name = data.get("tool", "")
                patient_id = data.get("patient_id", "").strip() or "synthetic-demo-patient"

                if tool_name == "prior_auth":
                    from tools.prior_auth import generate_prior_auth
                    result = generate_prior_auth(
                        patient_id=patient_id,
                        requested_medication=data.get("medication", ""),
                        indication=data.get("indication", ""),
                        payer_name=data.get("payer", "Insurance Payer"),
                    )
                    text = result.get("prior_auth_letter", str(result))
                elif tool_name == "appeal":
                    from tools.appeal_letter import draft_appeal_letter
                    result = draft_appeal_letter(
                        patient_id=patient_id,
                        denied_medication=data.get("medication", ""),
                        denial_reason=data.get("denial_reason", "not medically necessary"),
                        appeal_level=int(data.get("appeal_level", 1)),
                        payer_name=data.get("payer", "Insurance Payer"),
                        ordering_physician=data.get("ordering_physician", "Ordering Physician"),
                    )
                    text = result.get("appeal_letter", str(result))
                elif tool_name == "necessity":
                    from tools.medical_necessity import assess_medical_necessity
                    result = assess_medical_necessity(
                        patient_id=patient_id,
                        requested_treatment=data.get("treatment", ""),
                        treatment_type=data.get("treatment_type", "medication"),
                    )
                    text = json.dumps(result, indent=2)
                elif tool_name == "likelihood":
                    from tools.approval_likelihood import estimate_approval_likelihood
                    result = estimate_approval_likelihood(
                        patient_id=patient_id,
                        requested_medication=data.get("medication", ""),
                        indication=data.get("indication", ""),
                        payer_type=data.get("payer_type", "commercial"),
                    )
                    text = json.dumps(result, indent=2)
                else:
                    text = f"Unknown tool: {tool_name}"

                resp_body = json.dumps({"text": text}).encode("utf-8")
                await send({"type": "http.response.start", "status": 200,
                    "headers": [[b"content-type", b"application/json"],
                                [b"content-length", str(len(resp_body)).encode()]]})
                await send({"type": "http.response.body", "body": resp_body})
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode("utf-8")
                await send({"type": "http.response.start", "status": 500,
                    "headers": [[b"content-type", b"application/json"]]})
                await send({"type": "http.response.body", "body": err})

        elif path == "/health":
            body = b'{"status":"ok","service":"careflow-mcp"}'
            await send({"type": "http.response.start", "status": 200,
                "headers": [[b"content-type", b"application/json"],
                            [b"content-length", str(len(body)).encode()]]})
            await send({"type": "http.response.body", "body": body})

        else:
            body = b"Not found"
            await send({"type": "http.response.start", "status": 404,
                "headers": [[b"content-type", b"text/plain"],
                            [b"content-length", str(len(body)).encode()]]})
            await send({"type": "http.response.body", "body": body})


if __name__ == "__main__":
    uvicorn.run(
        "server_http:app",
        host=MCP_SERVER_HOST,
        port=MCP_SERVER_PORT,
        log_level="info",
    )
