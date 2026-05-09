"""
Tool 3: draft_appeal_letter
Generates a clinical appeal letter when a prior authorization has been denied.
Uses LLM reasoning to construct targeted counter-arguments.
"""
from fhir.client import FHIRClient
from fhir.synthetic_data import summarize_bundle_for_llm
from tools.llm import llm_call

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

    response = llm_call(SYSTEM_PROMPT, user_prompt)

    return {
        "patient_id": patient_id,
        "denied_medication": denied_medication,
        "denial_reason": denial_reason,
        "appeal_level": appeal_level,
        "payer": payer_name,
        "appeal_letter": response,
        "fhir_data_used": True,
    }
