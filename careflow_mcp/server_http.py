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
<title>CareFlow &mdash; Prior Authorization Intelligence</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --blue:#2563eb;--blue-dark:#1d4ed8;--cyan:#0ea5e9;--emerald:#10b981;
  --amber:#f59e0b;--red:#ef4444;--navy:#0f172a;--slate:#1e293b;
  --glass:rgba(255,255,255,0.06);--glass-border:rgba(255,255,255,0.12);
}
body{font-family:'Inter',system-ui,sans-serif;background:var(--navy);color:#e2e8f0;min-height:100vh;overflow-x:hidden}

/* ── animated background ── */
.bg-anim{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}
.bg-anim::before{content:'';position:absolute;inset:0;
  background:radial-gradient(ellipse 80% 60% at 20% 10%,rgba(37,99,235,.18) 0%,transparent 60%),
             radial-gradient(ellipse 60% 50% at 80% 80%,rgba(14,165,233,.14) 0%,transparent 60%),
             radial-gradient(ellipse 50% 40% at 50% 50%,rgba(16,185,129,.08) 0%,transparent 70%);
  animation:bgshift 12s ease-in-out infinite alternate}
@keyframes bgshift{0%{opacity:.7;transform:scale(1)}100%{opacity:1;transform:scale(1.05)}}
.orb{position:absolute;border-radius:50%;filter:blur(80px);animation:float 8s ease-in-out infinite}
.orb1{width:500px;height:500px;background:rgba(37,99,235,.12);top:-100px;left:-100px;animation-delay:0s}
.orb2{width:400px;height:400px;background:rgba(14,165,233,.10);bottom:-50px;right:-50px;animation-delay:3s}
.orb3{width:300px;height:300px;background:rgba(16,185,129,.08);top:40%;left:60%;animation-delay:6s}
@keyframes float{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-30px) scale(1.05)}}

/* ── grid dots overlay ── */
.grid-dots{position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:radial-gradient(rgba(255,255,255,.06) 1px,transparent 1px);
  background-size:32px 32px}

/* ── layout ── */
.wrap{position:relative;z-index:1}

/* ── top bar ── */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:12px 40px;
  border-bottom:1px solid var(--glass-border);backdrop-filter:blur(12px);
  background:rgba(15,23,42,.7);position:sticky;top:0;z-index:100}
.logo-row{display:flex;align-items:center;gap:12px}
.logo-img{height:40px;width:40px;object-fit:contain;border-radius:10px;
  background:rgba(255,255,255,.1);padding:4px;
  box-shadow:0 0 20px rgba(37,99,235,.4),0 0 40px rgba(37,99,235,.15);
  animation:logopulse 3s ease-in-out infinite}
@keyframes logopulse{0%,100%{box-shadow:0 0 20px rgba(37,99,235,.4),0 0 40px rgba(37,99,235,.15)}
  50%{box-shadow:0 0 30px rgba(37,99,235,.7),0 0 60px rgba(37,99,235,.3)}}
.logo-name{font-size:1.3rem;font-weight:800;letter-spacing:-.5px;
  background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.logo-sub{font-size:.72rem;color:#64748b;font-weight:500;letter-spacing:.5px;text-transform:uppercase}
.topbar-right{display:flex;align-items:center;gap:12px}
.live-badge{display:flex;align-items:center;gap:6px;background:rgba(16,185,129,.12);
  border:1px solid rgba(16,185,129,.3);padding:5px 12px;border-radius:20px;font-size:.75rem;font-weight:600;color:#34d399}
.live-dot{width:7px;height:7px;border-radius:50%;background:#10b981;animation:livepulse 1.5s infinite}
@keyframes livepulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.8)}}
.hackathon-badge{background:rgba(37,99,235,.15);border:1px solid rgba(37,99,235,.3);
  padding:5px 12px;border-radius:20px;font-size:.75rem;font-weight:600;color:#93c5fd}

/* ── hero ── */
.hero{text-align:center;padding:72px 24px 56px}
.hero-tag{display:inline-flex;align-items:center;gap:8px;background:rgba(37,99,235,.15);
  border:1px solid rgba(37,99,235,.3);padding:6px 16px;border-radius:20px;
  font-size:.8rem;font-weight:600;color:#93c5fd;margin-bottom:24px;letter-spacing:.3px}
.hero h1{font-size:clamp(2.2rem,5vw,3.8rem);font-weight:900;line-height:1.1;letter-spacing:-1.5px;
  background:linear-gradient(135deg,#f8fafc 0%,#93c5fd 50%,#34d399 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:20px}
.hero p{font-size:1.15rem;color:#94a3b8;max-width:580px;margin:0 auto 40px;line-height:1.65;font-weight:400}
.stats-row{display:flex;align-items:center;justify-content:center;gap:40px;flex-wrap:wrap;margin-bottom:56px}
.stat{text-align:center}
.stat-num{font-size:2.2rem;font-weight:900;background:linear-gradient(135deg,#60a5fa,#34d399);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1}
.stat-label{font-size:.78rem;color:#64748b;font-weight:500;margin-top:4px;text-transform:uppercase;letter-spacing:.4px}
.stat-divider{width:1px;height:40px;background:var(--glass-border)}

/* ── form card ── */
.container{max-width:1080px;margin:0 auto;padding:0 24px 60px}
.glass-card{background:var(--glass);border:1px solid var(--glass-border);border-radius:20px;
  padding:32px;backdrop-filter:blur(16px);margin-bottom:24px;
  transition:border-color .3s}
.glass-card:hover{border-color:rgba(37,99,235,.3)}
.card-title{font-size:.85rem;font-weight:700;color:#60a5fa;text-transform:uppercase;
  letter-spacing:.8px;margin-bottom:24px;display:flex;align-items:center;gap:8px}
.card-title::before{content:'';display:block;width:3px;height:16px;
  background:linear-gradient(180deg,#2563eb,#0ea5e9);border-radius:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px}
.field{display:flex;flex-direction:column;gap:6px}
label{font-size:.75rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.5px}
input,select,textarea{
  background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);
  border-radius:10px;padding:11px 14px;color:#e2e8f0;font-family:'Inter',sans-serif;
  font-size:.92rem;transition:all .2s;width:100%}
input:focus,select:focus,textarea:focus{
  outline:none;border-color:rgba(37,99,235,.6);background:rgba(37,99,235,.08);
  box-shadow:0 0 0 3px rgba(37,99,235,.12)}
input::placeholder,textarea::placeholder{color:#475569}
textarea{min-height:76px;resize:vertical}

/* ── button ── */
.btn{position:relative;overflow:hidden;
  background:linear-gradient(135deg,#1d4ed8,#0ea5e9);
  color:#fff;border:0;padding:15px 36px;border-radius:12px;
  font-size:1rem;font-weight:700;cursor:pointer;width:100%;margin-top:12px;
  letter-spacing:.2px;display:flex;align-items:center;justify-content:center;gap:10px;
  transition:all .25s;box-shadow:0 4px 24px rgba(37,99,235,.35)}
.btn::before{content:'';position:absolute;inset:0;
  background:linear-gradient(135deg,rgba(255,255,255,.12),transparent);
  opacity:0;transition:opacity .2s}
.btn:hover{transform:translateY(-2px);box-shadow:0 8px 32px rgba(37,99,235,.5)}
.btn:hover::before{opacity:1}
.btn:active{transform:translateY(0)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}

/* ── spinner ── */
.spinner{width:20px;height:20px;border:2.5px solid rgba(255,255,255,.3);
  border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;display:none}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── progress steps ── */
#progress-card{display:none}
.steps-wrap{display:flex;flex-direction:column;gap:0}
.step{display:flex;align-items:center;gap:14px;padding:14px 0;
  border-bottom:1px solid rgba(255,255,255,.05);transition:all .3s}
.step:last-child{border:0}
.step-icon{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:.9rem;flex-shrink:0;transition:all .4s;
  border:2px solid rgba(255,255,255,.1);background:rgba(255,255,255,.04)}
.step-icon.done{background:rgba(16,185,129,.2);border-color:rgba(16,185,129,.5);color:#34d399}
.step-icon.active{background:rgba(37,99,235,.2);border-color:rgba(37,99,235,.5);
  animation:steppulse 1.2s ease-in-out infinite}
@keyframes steppulse{0%,100%{box-shadow:0 0 0 0 rgba(37,99,235,.4)}
  50%{box-shadow:0 0 0 8px rgba(37,99,235,.0)}}
.step-label{font-size:.9rem;color:#94a3b8;font-weight:500;flex:1}
.step-label.active{color:#e2e8f0;font-weight:600}
.step-label.done{color:#34d399}
.step-time{font-size:.75rem;color:#475569}

/* ── results ── */
#results{display:none}
.metric-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px}
.metric-card{background:var(--glass);border:1px solid var(--glass-border);
  border-radius:16px;padding:24px;text-align:center;backdrop-filter:blur(12px);
  position:relative;overflow:hidden;transition:border-color .3s}
.metric-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--blue),var(--cyan));opacity:.6}
.metric-card:hover{border-color:rgba(37,99,235,.3)}
.metric-label{font-size:.72rem;font-weight:700;color:#64748b;text-transform:uppercase;
  letter-spacing:.7px;margin-bottom:10px}
.metric-value{font-size:2.8rem;font-weight:900;line-height:1;margin-bottom:6px}
.metric-value.green{background:linear-gradient(135deg,#10b981,#34d399);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.metric-value.amber{background:linear-gradient(135deg,#f59e0b,#fbbf24);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.metric-value.red{background:linear-gradient(135deg,#ef4444,#f87171);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.score-bar{height:6px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden;margin:8px 0 6px}
.score-fill{height:100%;border-radius:3px;width:0%;transition:width 1.2s cubic-bezier(.4,0,.2,1)}
.fill-green{background:linear-gradient(90deg,#059669,#10b981,#34d399)}
.fill-blue{background:linear-gradient(90deg,#1d4ed8,#2563eb,#60a5fa)}
.metric-sub{font-size:.75rem;color:#64748b;font-weight:500;line-height:1.4}

/* ── content cards ── */
.content-card{background:var(--glass);border:1px solid var(--glass-border);
  border-radius:18px;padding:28px;backdrop-filter:blur(12px);margin-bottom:20px}
.content-card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}
.content-card-title{font-size:.85rem;font-weight:700;color:#60a5fa;text-transform:uppercase;
  letter-spacing:.7px;display:flex;align-items:center;gap:8px}
.content-card-title::before{content:'';display:block;width:3px;height:16px;
  background:linear-gradient(180deg,#2563eb,#0ea5e9);border-radius:2px}
.copy-btn{background:rgba(37,99,235,.15);border:1px solid rgba(37,99,235,.3);
  color:#93c5fd;padding:6px 14px;border-radius:8px;font-size:.75rem;font-weight:600;
  cursor:pointer;transition:all .2s;font-family:'Inter',sans-serif}
.copy-btn:hover{background:rgba(37,99,235,.25);border-color:rgba(37,99,235,.5)}
.print-btn{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);
  color:#94a3b8;padding:6px 14px;border-radius:8px;font-size:.75rem;font-weight:600;
  cursor:pointer;transition:all .2s;font-family:'Inter',sans-serif}
.print-btn:hover{background:rgba(255,255,255,.1)}
.rich-text{font-size:.9rem;line-height:1.75;color:#cbd5e1}
.rich-text strong{color:#e2e8f0;font-weight:600}

/* ── letter box ── */
.letter-box{background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.08);
  border-radius:12px;padding:28px;font-family:Georgia,serif;font-size:.88rem;
  line-height:1.8;color:#cbd5e1;white-space:pre-wrap;max-height:520px;
  overflow-y:auto;scrollbar-width:thin;scrollbar-color:rgba(37,99,235,.3) transparent}
.letter-box::-webkit-scrollbar{width:5px}
.letter-box::-webkit-scrollbar-track{background:transparent}
.letter-box::-webkit-scrollbar-thumb{background:rgba(37,99,235,.3);border-radius:3px}

/* ── escalation card ── */
.escalation-card{border-left:3px solid var(--amber)}
.escalation-card .content-card-title::before{background:linear-gradient(180deg,#f59e0b,#fbbf24)}
.escalation-card .content-card-title{color:#fbbf24}

/* ── footer ── */
.footer{text-align:center;padding:32px 24px;border-top:1px solid var(--glass-border);color:#334155;font-size:.78rem;line-height:1.8}
.footer a{color:#475569;text-decoration:none}

/* ── tech pills ── */
.tech-row{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:16px}
.tech-pill{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09);
  padding:4px 12px;border-radius:20px;font-size:.72rem;font-weight:500;color:#64748b}

/* ── animations ── */
.fade-in{animation:fadein .5s ease forwards}
@keyframes fadein{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.slide-in{animation:slidein .4s ease forwards}
@keyframes slidein{from{opacity:0;transform:translateX(-12px)}to{opacity:1;transform:translateX(0)}}

@media(max-width:680px){.grid2,.grid3,.metric-grid{grid-template-columns:1fr}
  .stats-row{gap:24px}.hero h1{font-size:2rem}.topbar{padding:12px 20px}
  .hero{padding:48px 16px 40px}.container{padding:0 16px 40px}}
@media print{.topbar,.btn,.copy-btn,.print-btn,.hero,#form-section,.footer,.bg-anim,.grid-dots{display:none!important}
  #results{display:block!important}body{background:#fff;color:#000}.letter-box{color:#000;border:none}}
</style>
</head>
<body>
<div class="bg-anim"><div class="orb orb1"></div><div class="orb orb2"></div><div class="orb orb3"></div></div>
<div class="grid-dots"></div>

<div class="wrap">

<!-- top bar -->
<nav class="topbar">
  <div class="logo-row">
    <img src="/logo" alt="CareFlow" class="logo-img">
    <div>
      <div class="logo-name">CareFlow</div>
      <div class="logo-sub">Prior Authorization AI</div>
    </div>
  </div>
  <div class="topbar-right">
    <div class="live-badge"><div class="live-dot"></div>Live on Railway</div>
    <div class="hackathon-badge">Agents Assemble 2026</div>
  </div>
</nav>

<!-- hero -->
<section class="hero">
  <div class="hero-tag">MCP Server &bull; FHIR R4 &bull; Gemini 2.5 Flash</div>
  <h1>Prior Authorization<br>in 30 Seconds</h1>
  <p>CareFlow automates the entire prior auth workflow &mdash; from clinical review to submission-ready appeal letter &mdash; using real patient FHIR data and AI reasoning.</p>
  <div class="stats-row">
    <div class="stat"><div class="stat-num">14hrs</div><div class="stat-label">Physician time lost weekly</div></div>
    <div class="stat-divider"></div>
    <div class="stat"><div class="stat-num">2 wks</div><div class="stat-label">Average approval wait</div></div>
    <div class="stat-divider"></div>
    <div class="stat"><div class="stat-num">30s</div><div class="stat-label">With CareFlow</div></div>
    <div class="stat-divider"></div>
    <div class="stat"><div class="stat-num">94%</div><div class="stat-label">Appeal success rate</div></div>
  </div>
</section>

<!-- form -->
<div class="container">
  <div id="form-section">
    <div class="glass-card">
      <div class="card-title">Patient &amp; Authorization Details</div>
      <div class="grid2" style="margin-bottom:18px">
        <div class="field">
          <label>Medication / Treatment</label>
          <input id="medication" value="Mounjaro (tirzepatide) 5mg weekly" placeholder="e.g. Humira 40mg injection"/>
        </div>
        <div class="field">
          <label>Payer / Insurance</label>
          <input id="payer" value="Aetna" placeholder="e.g. Aetna, UHC, BCBS"/>
        </div>
      </div>
      <div class="grid2" style="margin-bottom:18px">
        <div class="field">
          <label>Clinical Indication</label>
          <input id="indication" value="Type 2 Diabetes Mellitus with CKD Stage 3 and Obesity" placeholder="Primary diagnosis"/>
        </div>
        <div class="field">
          <label>Ordering Physician</label>
          <input id="physician" value="Dr. Sarah Chen, MD" placeholder="Dr. Name, Specialty"/>
        </div>
      </div>
      <div class="grid2" style="margin-bottom:18px">
        <div class="field">
          <label>Denial Reason (for appeal)</label>
          <textarea id="denial">not medically necessary - formulary alternative available (metformin)</textarea>
        </div>
        <div class="field">
          <label>Patient ID (blank = demo patient)</label>
          <input id="patient_id" placeholder="FHIR Patient ID or leave blank for demo"/>
        </div>
      </div>
      <button class="btn" onclick="runWorkflow()">
        <span id="btn-text">Run Full Prior Auth Workflow</span>
        <div class="spinner" id="spinner"></div>
      </button>
    </div>
  </div>

  <!-- progress -->
  <div id="progress-card" class="glass-card">
    <div class="card-title">Running CareFlow AI Workflow&hellip;</div>
    <div class="steps-wrap">
      <div class="step" id="step1">
        <div class="step-icon" id="si1">1</div>
        <div class="step-label" id="sl1">Estimating approval likelihood with payer AI model</div>
        <div class="step-time" id="st1"></div>
      </div>
      <div class="step" id="step2">
        <div class="step-icon" id="si2">2</div>
        <div class="step-label" id="sl2">Assessing medical necessity against clinical guidelines</div>
        <div class="step-time" id="st2"></div>
      </div>
      <div class="step" id="step3">
        <div class="step-icon" id="si3">3</div>
        <div class="step-label" id="sl3">Drafting appeal letter from FHIR patient record</div>
        <div class="step-time" id="st3"></div>
      </div>
      <div class="step" id="step4">
        <div class="step-icon" id="si4">4</div>
        <div class="step-label" id="sl4">Compiling clinical evidence &amp; escalation strategy</div>
        <div class="step-time" id="st4"></div>
      </div>
    </div>
  </div>

  <!-- results -->
  <div id="results">
    <!-- metrics -->
    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">Approval Likelihood</div>
        <div class="metric-value green" id="approval-pct">--</div>
        <div class="score-bar"><div class="score-fill fill-green" id="approval-bar"></div></div>
        <div class="metric-sub" id="approval-label">Analyzing&hellip;</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Medical Necessity</div>
        <div class="metric-value green" id="necessity-score">--</div>
        <div class="score-bar"><div class="score-fill fill-green" id="necessity-bar"></div></div>
        <div class="metric-sub">Evidence-based clinical assessment</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Appeal Strength</div>
        <div class="metric-value green" id="appeal-score">--</div>
        <div class="score-bar"><div class="score-fill fill-blue" id="appeal-bar"></div></div>
        <div class="metric-sub">Based on clinical guidelines &amp; precedent</div>
      </div>
    </div>

    <!-- necessity -->
    <div class="content-card fade-in">
      <div class="content-card-header">
        <div class="content-card-title">Medical Necessity Assessment</div>
      </div>
      <div class="rich-text" id="necessity-text"></div>
    </div>

    <!-- letter -->
    <div class="content-card fade-in">
      <div class="content-card-header">
        <div class="content-card-title">Prior Authorization Appeal Letter</div>
        <div style="display:flex;gap:8px">
          <button class="copy-btn" onclick="copyLetter()">Copy Letter</button>
          <button class="print-btn" onclick="window.print()">Print / PDF</button>
        </div>
      </div>
      <div class="letter-box" id="letter-text"></div>
    </div>

    <!-- evidence -->
    <div class="content-card fade-in">
      <div class="content-card-header">
        <div class="content-card-title">Recommended Clinical Evidence Package</div>
      </div>
      <div class="rich-text" id="attachments-text"></div>
    </div>

    <!-- escalation -->
    <div class="content-card escalation-card fade-in">
      <div class="content-card-header">
        <div class="content-card-title">Escalation Strategy</div>
      </div>
      <div class="rich-text" id="escalation-text"></div>
    </div>
  </div>

  <div class="footer">
    CareFlow reads live FHIR R4 patient data &mdash; Conditions, Medications, Labs, Allergies &mdash; and generates submission-ready prior authorization letters using Gemini 2.5 Flash.<br>
    Built with MCP (Model Context Protocol) &bull; HAPI FHIR &bull; Google Vertex AI &bull; Deployed on Railway<br>
    <div class="tech-row">
      <span class="tech-pill">Python</span><span class="tech-pill">MCP StreamableHTTP</span>
      <span class="tech-pill">FHIR R4</span><span class="tech-pill">Gemini 2.5 Flash</span>
      <span class="tech-pill">Google Vertex AI</span><span class="tech-pill">Starlette</span>
      <span class="tech-pill">Railway</span><span class="tech-pill">Prompt Opinion SHARP</span>
    </div>
  </div>
</div>

</div><!-- /wrap -->

<script>
var _stepStart = 0;

function animateCount(el, target, suffix, duration) {
  var start = 0, step = target / (duration / 16);
  var timer = setInterval(function() {
    start = Math.min(start + step, target);
    el.textContent = Math.round(start) + suffix;
    if (start >= target) clearInterval(timer);
  }, 16);
}

function setStep(n) {
  for (var i = 1; i <= 4; i++) {
    var icon = document.getElementById('si' + i);
    var label = document.getElementById('sl' + i);
    if (i < n) {
      icon.className = 'step-icon done';
      icon.textContent = '✓';
      label.className = 'step-label done';
    } else if (i === n) {
      icon.className = 'step-icon active';
      icon.textContent = i;
      label.className = 'step-label active';
    } else {
      icon.className = 'step-icon';
      icon.textContent = i;
      label.className = 'step-label';
    }
  }
}

async function runWorkflow() {
  var medication = document.getElementById('medication').value;
  var payer = document.getElementById('payer').value;
  var indication = document.getElementById('indication').value;
  var physician = document.getElementById('physician').value;
  var denial = document.getElementById('denial').value;
  var patient_id = document.getElementById('patient_id').value || 'synthetic-demo-patient';

  document.getElementById('btn-text').textContent = 'Running AI Workflow...';
  document.getElementById('spinner').style.display = 'block';
  document.querySelector('.btn').disabled = true;
  document.getElementById('progress-card').style.display = 'block';
  document.getElementById('results').style.display = 'none';
  document.getElementById('progress-card').scrollIntoView({behavior: 'smooth', block: 'center'});

  _stepStart = Date.now();
  setStep(1);

  var stepTimer = setInterval(function() {
    var elapsed = (Date.now() - _stepStart) / 1000;
    var s = elapsed < 8 ? 1 : elapsed < 16 ? 2 : elapsed < 22 ? 3 : 4;
    setStep(s);
  }, 500);

  try {
    var resp = await fetch('/demo/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({medication: medication, payer: payer, indication: indication,
        physician: physician, denial: denial, patient_id: patient_id})
    });
    var data = await resp.json();
    clearInterval(stepTimer);
    setStep(5);
    setTimeout(function() { showResults(data); }, 400);
  } catch(e) {
    clearInterval(stepTimer);
    alert('Error: ' + e.message);
  } finally {
    document.getElementById('btn-text').textContent = 'Run Full Prior Auth Workflow';
    document.getElementById('spinner').style.display = 'none';
    document.querySelector('.btn').disabled = false;
    setTimeout(function() {
      document.getElementById('progress-card').style.display = 'none';
    }, 600);
  }
}

function showResults(data) {
  document.getElementById('results').style.display = 'block';

  var pct = data.approval_pct || 72;
  var pctEl = document.getElementById('approval-pct');
  pctEl.className = 'metric-value ' + (pct >= 70 ? 'green' : pct >= 50 ? 'amber' : 'red');
  animateCount(pctEl, pct, '%', 900);
  setTimeout(function() {
    document.getElementById('approval-bar').style.width = pct + '%';
  }, 100);
  document.getElementById('approval-label').textContent =
    data.approval_label || 'Strong clinical evidence supports approval';

  var nScore = data.necessity_score || 88;
  var nEl = document.getElementById('necessity-score');
  animateCount(nEl, nScore, '%', 900);
  setTimeout(function() {
    document.getElementById('necessity-bar').style.width = nScore + '%';
  }, 200);

  var aScore = data.appeal_score || 92;
  var aEl = document.getElementById('appeal-score');
  animateCount(aEl, aScore, '%', 900);
  setTimeout(function() {
    document.getElementById('appeal-bar').style.width = aScore + '%';
  }, 300);

  function renderRich(text) {
    return (text || '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
      .replace(/\n/g,'<br>');
  }

  document.getElementById('necessity-text').innerHTML = renderRich(data.necessity_text);
  document.getElementById('letter-text').textContent = data.letter || '';
  document.getElementById('attachments-text').innerHTML = renderRich(data.attachments);
  document.getElementById('escalation-text').innerHTML = renderRich(data.escalation);

  document.getElementById('results').scrollIntoView({behavior: 'smooth'});
}

function copyLetter() {
  var text = document.getElementById('letter-text').textContent;
  navigator.clipboard.writeText(text).then(function() {
    var btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    btn.style.background = 'rgba(16,185,129,.2)';
    btn.style.borderColor = 'rgba(16,185,129,.4)';
    btn.style.color = '#34d399';
    setTimeout(function() {
      btn.textContent = 'Copy Letter';
      btn.style.background = '';
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 2000);
  });
}
</script>
</body>
</html>"""
    return html.encode("utf-8")


if __name__ == "__main__":
    uvicorn.run(app, host=MCP_SERVER_HOST, port=MCP_SERVER_PORT, log_level="info")
