# CareFlow Prior Authorization Intelligence MCP Server

> **Hackathon submission for:** Agents Assemble — The Healthcare AI Endgame  
> **Track:** Path A — MCP Server (Superpower)  
> **Platform:** Prompt Opinion Marketplace

An AI-powered MCP server that automates the prior authorization workflow in healthcare.
Connects to any FHIR R4 server via SHARP context, retrieves real patient clinical data,
and uses large language model reasoning to generate complete PA requests, assess medical
necessity, draft appeal letters, and predict approval likelihood — all in seconds.

---

## The Problem

Prior authorization wastes **14+ hours per physician per week**, delays patient care, and
costs the US healthcare system ~$35 billion annually. 94% of physicians report PA causes
direct patient care delays. Traditional rule-based systems can't reason over nuanced
clinical data the way a specialist reviewer does.

## What CareFlow Does

| Tool | What it does |
|---|---|
| `generate_prior_auth` | Generates a complete, payer-ready PA letter from FHIR data |
| `assess_medical_necessity` | Evaluates necessity against ADA/ACC-AHA/KDIGO guidelines |
| `draft_appeal_letter` | Builds a clinical appeal rebutting specific denial reasons |
| `estimate_approval_likelihood` | Pre-submission gap analysis with action items |

---

## Quick Start

### 1. Install dependencies

```bash
cd careflow_mcp
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 3. Run the MCP server

```bash
python server.py
```

The server communicates over stdio (standard MCP protocol).

### 4. Run tests

```bash
python -m pytest tests/ -v
```

---

## Prompt Opinion Marketplace — Deployment Steps

### Step 1: Host your server

Deploy `server.py` to any cloud service (Railway, Render, Fly.io, etc.).
The server uses stdio transport — wrap it with a simple HTTP-to-stdio proxy,
or use the `--transport sse` flag if your MCP version supports it.

### Step 2: Create a Prompt Opinion account

Sign up at [app.promptopinion.ai](https://app.promptopinion.ai)

### Step 3: Register your MCP server

In the Prompt Opinion dashboard:
1. Go to **Marketplace → Publish Tool**
2. Enter your server URL
3. Select **MCP Server** as the type
4. The platform will auto-discover your tools via `list_tools`

### Step 4: Configure SHARP Context

In your tool configuration, enable the following SHARP fields:
- `x-sharp-patient-id` → maps to `patient_id`
- `x-sharp-fhir-base-url` → maps to your EHR's FHIR endpoint
- `x-sharp-fhir-token` → maps to the session SMART-on-FHIR token

This allows CareFlow to pull live (synthetic for demo) patient data automatically
when invoked from a clinician's EHR session.

---

## Architecture

```
Clinician (EHR Session)
        │
        ▼
Prompt Opinion Platform
  │  SHARP Context: patient-id, fhir-url, fhir-token
  ▼
CareFlow MCP Server (server.py)
  │
  ├── FHIRClient → HAPI FHIR R4 Server (synthetic data)
  │     └── Patient + Conditions + Medications + Labs + Allergies
  │
  └── LLM Tools (Claude via Anthropic API)
        ├── generate_prior_auth
        ├── assess_medical_necessity
        ├── draft_appeal_letter
        └── estimate_approval_likelihood
```

---

## Demo Scenario

The included synthetic patient is **Marcus Johnson**, a 58-year-old male with:
- Type 2 Diabetes (HbA1c 8.9% — above target despite dual oral therapy)
- Hypertension (BP 148/92)
- CKD Stage 3 (eGFR 42)
- Obesity (BMI 34.2)
- On Metformin 1000mg BID + Glipizide 5mg BID

**PA Request:** Semaglutide (Ozempic) 0.5mg weekly — a GLP-1 agonist indicated for
glycemic control with proven cardiovascular and renal protection benefits.

This is a perfect demonstration case because:
- ADA guidelines strongly support GLP-1 agonists in this clinical profile
- Step therapy (Metformin + sulfonylurea) is already documented
- The CKD adds urgency (renal protection data)
- Real payers frequently deny this due to cost — making the appeal tool relevant

---

## Data Privacy

All demo data is entirely synthetic and de-identified. No real PHI is used.
The architecture is designed for HIPAA-compatible deployment:
- No patient data is stored by the MCP server
- All LLM calls use ephemeral context (no training on patient data)
- FHIR tokens are passed through in-session only

---

## License

MIT License — free to use, modify, and deploy.
