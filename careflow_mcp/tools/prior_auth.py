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
            requested_medication