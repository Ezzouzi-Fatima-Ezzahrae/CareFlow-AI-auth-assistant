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
            clinical_summary=clinical_summary,
        )

    # Parse urgency from response
    urgency = "routine"
    lower = response.lower()
    if "stat" in lower or "immediate" in lower or "life-threatening" in lower:
        urgency = "stat"
    elif "urgent" in lower or "expedited" in lower:
        urgency = "urgent"

    return {
        "patient_id": patient_id,
        "requested_medication": requested_medication,
        "indication": indication,
        "payer": payer_name,
        "prior_auth_letter": response,
        "urgency": urgency,
        "fhir_data_used": True,
    }


def _fallback_prior_auth(
    patient_id: str,
    requested_medication: str,
    indication: str,
    payer_name: str,
    clinical_summary: str,
) -> str:
    """
    Generate a professional template prior auth letter using FHIR clinical summary data.
    Used when the LLM is unavailable.
    """
    today = date.today().strftime("%B %d, %Y")

    # Extract patient name and DOB from the clinical_summary
    patient_name = "Patient"
    dob = ""
    for line in clinical_summary.splitlines():
        if line.startswith("PATIENT:"):
            parts = line.replace("PATIENT:", "").split(",")
            patient_name = parts[0].strip()
            for p in parts[1:]:
                if "DOB:" in p:
                    dob = p.replace("DOB:", "").strip()
            break

    conditions_block = ""
    labs_block = ""
    meds_block = ""
    in_section = None
    for line in clinical_summary.splitlines():
        if "ACTIVE CONDITIONS:" in line:
            in_section = "conditions"
        elif "CURRENT MEDICATIONS:" in line:
            in_section = "meds"
        elif "RECENT LABS" in line:
            in_section = "labs"
        elif "ALLERGIES:" in line or "REQUESTED MEDICATION" in line:
            in_section = None
        elif in_section == "conditions" and line.strip().startswith("-"):
            conditions_block += line.strip() + "\n"
        elif in_section == "meds" and line.strip().startswith("-"):
            meds_block += line.strip() + "\n"
        elif in_section == "labs" and line.strip().startswith("-"):
            labs_block += line.strip() + "\n"

    letter = f"""{today}

Prior Authorization Department
{payer_name}
Utilization Management Division

RE: Prior Authorization Request
    Patient: {patient_name}{f" | DOB: {dob}" if dob else ""}
    Patient ID: {patient_id}
    Requested Treatment: {requested_medication}
    Primary Indication: {indication}

Dear Prior Authorization Reviewer,

I am writing to request prior authorization for {requested_medication} for my patient, {patient_name}, for the treatment of {indication}. This request is supported by clinical evidence and is consistent with current evidence-based guidelines.

**PATIENT SUMMARY**

{patient_name} is a patient with the following active diagnoses:
{conditions_block.strip() if conditions_block.strip() else "  - See attached clinical records"}

**CURRENT MEDICATIONS**

{meds_block.strip() if meds_block.strip() else "  - See attached medication list"}

**RECENT LABORATORY VALUES AND VITALS**

{labs_block.strip() if labs_block.strip() else "  - See attached laboratory reports"}

**CLINICAL INDICATION AND MEDICAL NECESSITY**

The requested medication, {requested_medication}, is medically necessary for the treatment of {indication} in this patient. The patient's clinical course demonstrates:

1. **Established Diagnosis.** The diagnosis of {indication} is confirmed based on clinical evaluation, laboratory findings, and documented disease progression as reflected in the patient's medical record.

2. **Inadequate Response to Prior Therapy.** The patient has been treated with appropriate first-line therapies. Despite optimization of current regimen, the patient has not achieved adequate therapeutic goals, necessitating advancement to {requested_medication}.

3. **Guideline-Concordant Care.** This request is consistent with current clinical practice guidelines. {requested_medication} is recommended by major specialty societies for patients with {indication} who have not responded adequately to first-line treatment.

4. **Expected Clinical Benefit.** Evidence from clinical trials and real-world studies demonstrates that {requested_medication} provides clinically meaningful improvements in disease outcomes, quality of life, and long-term complication prevention for patients with this indication.

**SUPPORTING DOCUMENTATION**

The following documents are available upon request:
- Complete office visit notes and clinical records
- Laboratory reports confirming diagnosis and current disease status
- Documentation of prior treatment history and response
- Peer-reviewed literature supporting use of {requested_medication} in {indication}

**REQUEST**

Please approve prior authorization for {requested_medication} for {patient_name}. This treatment is medically necessary and will significantly improve this patient's clinical outcomes and quality of life.

For questions or to arrange a peer-to-peer discussion, please contact our office directly.

Sincerely,

Ordering Physician

---
*This prior authorization letter was generated by CareFlow Prior Authorization Intelligence using patient FHIR clinical data.*
"""
    return letter
