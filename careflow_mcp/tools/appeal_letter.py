"""
Tool 3: draft_appeal_letter
Generates a clinical appeal letter when a prior authorization has been denied.
Uses LLM reasoning to construct targeted counter-arguments.
Falls back to a professional template letter if the LLM is unavailable.
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
4. Escalate language appropriately — from collegial in Level 1 to assertive in Level 2/3
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
    """
    Draft a clinical appeal letter for a denied prior authorization.

    Args:
        patient_id: FHIR Patient resource ID
        denied_medication: The medication/procedure that was denied
        denial_reason: The payer's stated reason for denial
        appeal_level: 1 (first appeal), 2 (second appeal), or 3 (external review)
        payer_name: Name of the insurance payer
        ordering_physician: Name of the requesting physician
        fhir_base_url: FHIR server base URL (from SHARP context)
        fhir_token: FHIR auth token (from SHARP context)

    Returns:
        dict with 'appeal_letter', 'rebuttal_points', 'recommended_attachments', 'escalation_advice'
    """
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
        )

    # Parse structured sections from LLM response
    appeal_letter = _extract_section(response, ["APPEAL LETTER", "1. APPEAL LETTER"])
    rebuttal_points = _extract_section(response, ["KEY REBUTTAL POINTS", "2. KEY REBUTTAL POINTS"])
    recommended_attachments = _extract_section(response, ["RECOMMENDED ATTACHMENTS", "3. RECOMMENDED ATTACHMENTS"])
    escalation_advice = _extract_section(response, ["ESCALATION ADVICE", "4. ESCALATION ADVICE"])

    if not appeal_letter:
        appeal_letter = response  # Use full response if parsing fails

    return {
        "appeal_letter": appeal_letter,
        "rebuttal_points": rebuttal_points or "See appeal letter for clinical arguments.",
        "recommended_attachments": recommended_attachments or "Recent lab results, physician notes, clinical guidelines.",
        "escalation_advice": escalation_advice or "Request external independent review if Level 2 appeal is denied.",
        "appeal_level": appeal_level,
        "payer": payer_name,
        "denied_medication": denied_medication,
        "denial_reason": denial_reason,
        "patient_id": patient_id,
    }


def _extract_section(text: str, headers: list) -> str:
    """Extract a named section from structured LLM output."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line_upper = line.upper().strip()
        for header in headers:
            if header.upper() in line_upper:
                # Collect lines until next numbered section or end
                section_lines = []
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip()
                    # Stop at next major section header
                    if next_line and next_line[0].isdigit() and ". " in next_line[:5]:
                        break
                    section_lines.append(lines[j])
                return "\n".join(section_lines).strip()
    return ""


def _fallback_appeal_letter(
    patient_id: str,
    denied_medication: str,
    denial_reason: str,
    appeal_level: int,
    payer_name: str,
    ordering_physician: str,
) -> str:
    """Generate a professional template appeal letter when LLM is unavailable."""
    today = date.today().strftime("%B %d, %Y")
    level_text = {1: "First", 2: "Second", 3: "Third"}.get(appeal_level, "First")

    return f"""PRIOR AUTHORIZATION APPEAL — LEVEL {appeal_level} ({level_text.upper()} APPEAL)
Date: {today}

To: Medical Director / Appeals Department
{payer_name}

Re: {level_text} Level Appeal — Prior Authorization Denial for {denied_medication}
Patient ID: {patient_id}

Dear Medical Director,

I am writing to formally appeal the denial of prior authorization for {denied_medication} for the above-referenced patient. The stated reason for denial was: "{denial_reason}."

CLINICAL JUSTIFICATION

The requested treatment, {denied_medication}, is medically necessary for this patient based on their documented clinical history and current condition. The denial does not adequately account for the patient's individual clinical circumstances.

REBUTTAL TO DENIAL REASON

The denial reason of "{denial_reason}" is not supported by the patient's clinical record. The patient has a documented history that demonstrates medical necessity for this treatment. Alternative therapies have been considered and/or attempted, and {denied_medication} represents the most clinically appropriate treatment option.

SUPPORTING EVIDENCE

1. The patient's clinical history supports the medical necessity of {denied_medication}
2. Current clinical guidelines support the use of this treatment for the patient's condition
3. The requested treatment is consistent with evidence-based medicine

REQUEST

We respectfully request that {payer_name} reverse the denial and approve prior authorization for {denied_medication}. If additional clinical information is needed, please contact our office immediately.

If this appeal is denied, we will pursue all available remedies including external independent review as provided under applicable state and federal law.

Sincerely,

{ordering_physician}
Ordering Physician

---
Note: This is a template letter generated without LLM assistance. Please supplement with specific clinical details from the patient's medical record before submission.
"""
