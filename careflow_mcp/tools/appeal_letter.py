"""
Tool 3: draft_appeal_letter
Generates a clinical appeal letter when a prior authorization has been denied.
"""
import logging
from datetime import date
from fhir.client import FHIRClient
from fhir.synthetic_data import summarize_bundle_for_llm
from tools.llm import llm_call

logger = logging.getLogger("careflow.appeal_letter")

SYSTEM_PROMPT = """You are an expert healthcare attorney and clinical advocate specializing in
insurance appeals. You have successfully overturned thousands of prior authorization denials.

When drafting appeal letters you:
1. Directly address and rebut each stated denial reason with clinical evidence
2. Cite peer-reviewed literature and clinical guidelines by name and year
3. Invoke patient rights under applicable law (ACA, state surprise billing laws, ERISA, etc.) where relevant
4. Escalate language appropriately -- from collegial in Level 1 to assertive in Level 2/3
5. Include a clear timeline of events showing the patient has already tried required alternatives
6. Request expedited review when patient safety is at stake
7. Always close with a specific, actionable request

Your letters are professional, evidence-based, and compelling."""


def draft_appeal_letter(
    patient_id: str,
    denied_medication: str,
    denial_reason: str,
    appeal_level: int = 1,
    payer_name: str = "Insurance Payer",
    ordering_physician: str = "Ordering Physician",
    fhir_base_url: str = None,
    fhir_token: str = None,
) -> dict:
    """Draft a clinical appeal letter for a denied prior authorization."""
    client = FHIRClient(base_url=fhir_base_url or "", token=fhir_token)
    bundle = client.get_patient_bundle(patient_id)
    clinical_summary = summarize_bundle_for_llm(bundle)

    level_context = {
        1: "This is a Level 1 (first-level) appeal. Tone should be collegial but firm. Focus on clinical evidence.",
        2: "This is a Level 2 appeal. The first appeal was denied. Tone should be more assertive. Include legal references and request expedited review if appropriate.",
        3: "This is a Level 3 external review request. Tone is formal and legally precise. Reference the patient's right to independent external review.",
    }.get(appeal_level, "This is a Level 1 appeal.")

    user_prompt = f"""Draft a prior authorization appeal letter for:

PAYER: {payer_name}
DENIED TREATMENT: {denied_medication}
STATED DENIAL REASON: {denial_reason}
ORDERING PHYSICIAN: {ordering_physician}
{level_context}

PATIENT CLINICAL DATA (from FHIR):
{clinical_summary}

Please provide:

1. APPEAL LETTER: Complete, ready-to-send appeal letter

2. KEY REBUTTAL POINTS: Bullet list of the 3-5 strongest counter-arguments to the denial

3. RECOMMENDED ATTACHMENTS: List of clinical documents that should accompany this appeal
   (e.g., lab results, specialist notes, peer-reviewed articles)

4. ESCALATION ADVICE: If this appeal is also denied, what should the next step be?"""

    try:
        response = llm_call(SYSTEM_PROMPT, user_prompt)
        logger.info(f"LLM generated appeal letter: {len(response)} chars")
    except Exception as exc:
        logger.error(f"LLM call failed, using template fallback: {exc}")
        response = _fallback_appeal_letter(
            patient_id=patient_id,
            denied_medication=denied_medication,
            denial_reason=denial_reason,
            appeal_level=appeal_level,
            payer_name=payer_name,
            ordering_physician=ordering_physician,
            clinical_summary=clinical_summary,
        )

    return {
        "patient_id": patient_id,
        "denied_medication": denied_medication,
        "denial_reason": denial_reason,
        "appeal_level": appeal_level,
        "payer": payer_name,
        "appeal_letter": response,
        "fhir_data_used": True,
    }


def _fallback_appeal_letter(
    patient_id: str,
    denied_medication: str,
    denial_reason: str,
    appeal_level: int,
    payer_name: str,
    ordering_physician: str,
    clinical_summary: str,
) -> str:
    today = date.today().strftime("%B %d, %Y")
    level_word = {1: "First", 2: "Second", 3: "Third"}.get(appeal_level, "First")

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

Medical Director, Prior Authorization Review
{payer_name}
Appeals & Grievances Department

RE: {level_word}-Level Appeal -- Prior Authorization Denial
    Patient: {patient_name}{f" | DOB: {dob}" if dob else ""}
    Patient ID: {patient_id}
    Requested Treatment: {denied_medication}
    Stated Denial Reason: {denial_reason}

Dear Medical Director,

I am writing on behalf of my patient, {patient_name}, to formally appeal the denial of prior authorization for {denied_medication}. This {level_word.lower()}-level appeal is submitted pursuant to applicable state and federal law, including the Affordable Care Act's internal appeals requirements and, where applicable, ERISA.

**I. CLINICAL BACKGROUND AND MEDICAL NECESSITY**

{patient_name} presents with the following active diagnoses:
{conditions_block.strip() if conditions_block.strip() else "  - See attached clinical records"}

Current medications:
{meds_block.strip() if meds_block.strip() else "  - See attached medication list"}

Recent laboratory values and vital signs:
{labs_block.strip() if labs_block.strip() else "  - See attached laboratory reports"}

**II. REBUTTAL OF STATED DENIAL REASON**

Your organization denied this request citing: "{denial_reason}"

We respectfully disagree with this determination for the following reasons:

1. **Medical Necessity Is Established.** The clinical evidence cited above clearly demonstrates that {denied_medication} is medically necessary for the management of this patient's conditions. The patient has not achieved adequate disease control with currently available alternatives.

2. **Applicable Clinical Guidelines Support This Request.** The requested treatment is consistent with current evidence-based clinical practice guidelines, including recommendations from the American Diabetes Association Standards of Care (2025), the ACC/AHA Cardiovascular Prevention Guidelines, and other relevant specialty society recommendations.

3. **Step Therapy Requirements Have Been Met.** The patient's medical records document prior treatment attempts with first-line and alternative therapies. These therapies have been tried, optimized, and have failed to provide adequate therapeutic benefit, or are contraindicated given the patient's comorbidities.

4. **Denial Creates Risk of Harm.** Continued denial of this medically necessary treatment places the patient at increased risk of disease progression, hospitalization, and preventable complications -- outcomes that would ultimately increase overall healthcare costs far beyond the cost of the requested treatment.

**III. SUPPORTING EVIDENCE**

The following documents are enclosed in support of this appeal:
- Complete medical records including office visit notes
- Laboratory reports and imaging studies
- Documentation of prior therapy attempts and outcomes
- Peer-reviewed literature supporting the clinical appropriateness of {denied_medication}

**IV. REQUESTED ACTION**

We respectfully request that {payer_name} reverse its denial and approve prior authorization for {denied_medication} for {patient_name}. Given the clinical urgency, we request that this appeal be reviewed and a determination issued within the timeframes required by applicable law.

If you require additional clinical information or a peer-to-peer consultation, please contact our office at your earliest convenience.

Sincerely,

{ordering_physician}
Ordering Physician

cc: Patient file
    {payer_name} Member Appeals Department

---
*This appeal letter was generated by CareFlow Prior Authorization Intelligence using patient FHIR clinical data.*
"""
    return letter
