"""
Tool 4: estimate_approval_likelihood
Predicts prior authorization approval probability and flags documentation gaps
BEFORE submission — helping clinicians fix issues proactively.
"""
from fhir.client import FHIRClient
from fhir.synthetic_data import summarize_bundle_for_llm
from tools.llm import llm_call

SYSTEM_PROMPT = """You are a healthcare data analyst and prior authorization specialist who has
reviewed tens of thousands of prior authorization requests and their outcomes.

You understand the specific patterns that lead to approvals vs. denials:
- Missing step therapy documentation
- Incomplete lab values or outdated results
- Diagnosis codes that don't align with the request
- Missing specialist consultation notes
- Insufficient duration of previous treatments
- Contraindication documentation gaps

Your approval likelihood estimates are calibrated to real-world payer behavior.
Be specific about WHY the score is what it is, and give actionable fixes."""


def estimate_approval_likelihood(
    patient_id: str,
    requested_medication: str,
    indication: str,
    payer_type: str = "commercial",
    fhir_base_url: str = None,
    fhir_token: str = None,
) -> dict:
    """
    Estimate the likelihood of prior authorization approval and identify gaps.

    Args:
        patient_id: FHIR Patient resource ID
        requested_medication: Medication/procedure being requested
        indication: Primary clinical indication
        payer_type: 'commercial', 'medicare', 'medicaid', or 'medicare_advantage'
        fhir_base_url: FHIR server base URL (from SHARP context)
        fhir_token: FHIR auth token (from SHARP context)

    Returns:
        dict with 'likelihood_score', 'likelihood_label', 'strengths', 'gaps', 'action_items'
    """
    client = FHIRClient(base_url=fhir_base_url or "", token=fhir_token)
    bundle = client.get_patient_bundle(patient_id)
    clinical_summary = summarize_bundle_for_llm(bundle)

    user_prompt = f"""Estimate the prior authorization approval likelihood for:

REQUESTED: {requested_medication}
INDICATION: {indication}
PAYER TYPE: {payer_type}

PATIENT CLINICAL DATA (from FHIR):
{clinical_summary}

Please provide a structured assessment:

1. APPROVAL LIKELIHOOD SCORE: Give a percentage (e.g., 78%) AND a label:
   - HIGH (>75%): Strong case, likely approved as-is
   - MODERATE (50-75%): Approvable with minor additions
   - LOW (25-50%): Significant gaps, likely denied without changes
   - VERY LOW (<25%): Major issues, consider alternative approach

2. STRENGTHS: What aspects of this request are strong? (list 3-5 specific points)

3. DOCUMENTATION GAPS: What is missing or weak that could trigger denial? (list specifically)

4. STEP THERAPY STATUS: Has the patient tried required first-line agents? What's documented?

5. ACTION ITEMS: Concrete steps to take BEFORE submission to maximize approval chances
   (prioritize by impact — most important first)

6. ESTIMATED REVIEW TIMELINE: Based on payer type and urgency, how long should the clinician
   expect to wait for a decision?"""

    response = llm_call(SYSTEM_PROMPT, user_prompt)

    # Infer likelihood label from response
    likelihood_label = "moderate"
    lower = response.lower()
    if "very low" in lower or "very_low" in lower:
        likelihood_label = "very_low"
    elif "high (>" in lower or "likelihood: high" in lower or "label: high" in lower:
        likelihood_label = "high"
    elif "low (" in lower and "very low" not in lower:
        likelihood_label = "low"

    return {
        "patient_id": patient_id,
        "requested_medication": requested_medication,
        "indication": indication,
        "payer_type": payer_type,
        "approval_assessment": response,
        "likelihood_label": likelihood_label,
        "fhir_data_used": True,
    }
