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

        if path == "/mcp" or path.startswith("/mcp/"):
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
                    payer_name="Aetna",
                    ordering_physician="Dr. Sarah Chen",
                )
                body = json.dumps(result, indent=2).encode()
                status = 200
            except Exception as e:
                body = json.dumps({"error": str(e)}, indent=2).encode()
                status = 500
            await send({"type":"http.response.start","status":status,
                "headers":[[b"content-type",b"application/json"],
                           [b"content-length",str(len(body)).encode()]]})
            await send({"type":"http.response.body","body":body})

        elif path in ("/", "/health"):
            body = json.dumps({
                "service": "CareFlow Prior Authorization Intelligence",
                "status":  "running",
                "mcp_endpoint": "/mcp",
            }).encode()
            await send({
                "type": "http.response.start", "status": 200,
                "headers": [
                    [b"content-type",   b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            })
            await send({"type": "http.response.body", "body": body})

        else:
            await send({"type": "http.response.start", "status": 404,
                        "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": b'{"error":"not found"}'})


if __name__ == "__main__":
    uvicorn.run(app, host=MCP_SERVER_HOST, port=MCP_SERVER_PORT, log_level="info")
