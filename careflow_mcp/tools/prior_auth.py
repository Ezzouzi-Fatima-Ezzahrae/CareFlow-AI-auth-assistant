"""
Tool 1: generate_prior_auth
Generates a complete, payer-ready prior authorization request from FHIR patient data.
Falls back to a professional template letter if the LLM is unavailable.
"""
import logging
from datetime import date
from fhir.client import FHIRClient
from fhir.synthetic_data import summarize_bundle_for_llm
from tools.llm import llm_call

logger = logging.getLogger("careflow.prior_auth")

SYSTEM_PROMPT = """You are a clinical prior authorization specialist AI with deep expertise in
payer requirements, clinical guidelines, and medical necessity criteria.

Your task is to generate a complete, professional prior authorization request letter that:
1. Clearly states the requested medication/procedure and clinical indication
2. Summarizes the patient's relevant medical history supporting necessity
3. Documents prior treatment attempts and their outcomes (step therapy)
4. Cites relevant clinical guidelines (ADA, ACC/AHA, KDIGO, etc.) where applicable
5. Addresses common payer objections preemptively
6. Is formatted for immediate submission to an insurance payer

Be specific, cite lab values and dates, and write in a professional clinical tone.
Structure your output with clear sections: Patient Summary, Clinical Indication,
Medical Necessity Justification, Treatment History, Supporting Evidence, and Request Summary."""


def generate_prior_auth(
    patient_id: str,
    requested_medication: str,
    indication: str,
    payer_name: str = "Insurance Payer",
    fhir_base_url: str = None,
    fhir_token: str = None,
) -> dict:
    """
    Generate a complete prior authorization request letter.

    Args:
        patient_id: FHIR Patient resource ID
        requested_medication: Name and dose of the medication/procedure requiring PA
        indication: Clinical indication / diagnosis driving the request
        payer_name: Name of the insurance payer (for letter header)
        fhir_base_url: FHIR server base URL (from SHARP context)
        fhir_token: FHIR auth token (from SHARP context)

    Returns:
        dict with 'letter' (full PA text), 'key_points' (bullet list), 'urgency' (routine/urgent/stat)
    """
    client = FHIRClient(base_url=fhir_base_url or "", token=fhir_token)
    bundle = client.get_patient_bundle(patient_id)
    clinical_summary = summarize_bundle_for_llm(bundle)

    user_prompt = f"""Please generate a prior authorization request for the following:

PAYER: {payer_name}
REQUESTED: {requested_medication}
PRIMARY INDICATION: {indication}

PATIENT CLINICAL DATA (from FHIR):
{clinical_summary}

Generate the complete prior authorization letter, then provide:
- KEY POINTS: A bullet list of the 3-5 strongest arguments for approval
- URGENCY ASSESSMENT: Is this routine, urgent, or stat? With brief justification."""

    try:
        response = llm_call(SYSTEM_PROMPT, user_prompt)
        logger.info(f"LLM generated prior auth letter: {len(response)} chars")
    except Exception as exc:
        logger.error(f"LLM call failed, using template fallback: {exc}")
        response = _fallback_prior_auth(
            patient_id=patient_id,
            requested_medication=requested_medication,
            indication=indication,
            payer_name=payer_name,
        )

    # Parse key points and urgency from response
    key_points = _extract_section(response, ["KEY POINTS", "- KEY POINTS"])
    urgency_text = _extract_section(response, ["URGENCY ASSESSMENT", "- URGENCY ASSESSMENT"])

    # Determine urgency level
    urgency = "routine"
    if urgency_text:
        urgency_lower = urgency_text.lower()
        if "stat" in urgency_lower:
            urgency = "stat"
        elif "urgent" in urgency_lower:
            urgency = "urgent"

    # Extract the letter portion (everything before KEY POINTS)
    prior_auth_letter = _extract_letter(response)
    if not prior_auth_letter:
        prior_auth_letter = response

    return {
        "prior_auth_letter": prior_auth_letter,
        "key_points": key_points or "See letter for clinical justification.",
        "urgency": urgency,
        "payer": payer_name,
        "requested_medication": requested_medication,
        "indication": indication,
        "patient_id": patient_id,
    }


def _extract_letter(text: str) -> str:
    """Extract the letter portion before KEY POINTS section."""
    markers = ["KEY POINTS", "- KEY POINTS", "URGENCY ASSESSMENT"]
    lines = text.split("\n")
    letter_lines = []
    for line in lines:
        line_upper = line.upper().strip()
        if any(marker in line_upper for marker in markers):
            break
        letter_lines.append(line)
    return "\n".join(letter_lines).strip()


def _extract_section(text: str, headers: list) -> str:
    """Extract a named section from structured LLM output."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line_upper = line.upper().strip()
        for header in headers:
            if header.upper() in line_upper:
                section_lines = []
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip()
                    if next_line and next_line.startswith("- ") and any(
                        h.upper() in next_line.upper() for h in ["KEY POINTS", "URGENCY"]
                    ):
                        break
                    section_lines.append(lines[j])
                return "\n".join(section_lines).strip()
    return ""


def _fallback_prior_auth(
    patient_id: str,
    requested_medication: str,
    indication: str,
    payer_name: str,
) -> str:
    """Generate a professional template PA letter when LLM is unavailable."""
    today = date.today().strftime("%B %d, %Y")

    return f"""PRIOR AUTHORIZATION REQUEST
Date: {today}

To: Prior Authorization Department
{payer_name}

Re: Prior Authorization Request for {requested_medication}
Patient ID: {patient_id}
Primary Indication: {indication}

Dear Prior Authorization Reviewer,

I am writing to request prior authorization for {requested_medication} for the above-referenced patient.

CLINICAL INDICATION

The patient has been diagnosed with {indication}, which requires treatment with {requested_medication}. This medication is medically necessary based on the patient's clinical history and current condition.

MEDICAL NECESSITY JUSTIFICATION

{requested_medication} is indicated for the treatment of {indication} per current clinical guidelines. The patient's condition has been evaluated and this treatment represents the most appropriate therapeutic option given their clinical profile.

TREATMENT HISTORY

The patient's treatment history has been reviewed. The requested medication is appropriate based on the patient's response to prior treatments and current clinical status.

SUPPORTING EVIDENCE

Current clinical guidelines support the use of {requested_medication} for {indication}. The requested treatment is consistent with evidence-based medicine and standard of care.

REQUEST SUMMARY

We respectfully request approval for {requested_medication} for the treatment of {indication}. Please contact our office if additional clinical documentation is required.

Sincerely,

Ordering Physician

---
Note: This is a template letter generated without LLM assistance. Please supplement with specific clinical details from the patient's medical record before submission.
"""
