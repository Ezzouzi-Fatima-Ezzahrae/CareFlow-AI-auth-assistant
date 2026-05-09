"""
Tool 2: assess_medical_necessity
Uses LLM reasoning to evaluate whether a treatment meets medical necessity criteria,
cross-referencing the patient's clinical data against established guidelines.
"""
from fhir.client import FHIRClient
from fhir.synthetic_data import summarize_bundle_for_llm
from tools.llm import llm_call

SYSTEM_PROMPT = """You are a clinical medical necessity reviewer with expertise in evidence-based
medicine, clinical guidelines, and insurance coverage criteria.

Your role is to perform an objective medical necessity assessment that:
1. Evaluates the clinical appropriateness of the requested treatment
2. Cross-references patient data against ADA, ACC/AHA, KDIGO, and other relevant guidelines
3. Identifies what criteria ARE met and which may need additional documentation
4. Flags any gaps in clinical documentation that could cause denial
5. Provides an overall necessity score and confidence level

Be analytical, cite specific guideline thresholds (e.g., "ADA recommends GLP-1 agonists when
HbA1c > 7.0% despite dual therapy"), and clearly distinguish between what the data shows vs.
what additional information might strengthen the case."""


def assess_medical_necessity(
    patient_id: str,
    requested_treatment: str,
    treatment_type: str = "medication",
    fhir_base_url: str = None,
    fhir_token: str = None,
) -> dict:
    """
    Assess medical necessity for a requested treatment based on FHIR patient data.

    Args:
        patient_id: FHIR Patient resource ID
        requested_treatment: Treatment/medication/procedure to assess
        treatment_type: 'medication', 'procedure', 'dme', or 'referral'
        fhir_base_url: FHIR server base URL (from SHARP context)
        fhir_token: FHIR auth token (from SHARP context)

    Returns:
        dict with 'assessment', 'criteria_met', 'criteria_missing', 'score', 'recommendation'
    """
    client = FHIRClient(base_url=fhir_base_url or "", token=fhir_token)
    bundle = client.get_patient_bundle(patient_id)
    clinical_summary = summarize_bundle_for_llm(bundle)

    user_prompt = f"""Perform a medical necessity assessment for the following request:

REQUESTED TREATMENT: {requested_treatment}
TREATMENT TYPE: {treatment_type}

PATIENT CLINICAL DATA (from FHIR):
{clinical_summary}

Please provide:

1. NECESSITY ASSESSMENT: Detailed analysis of whether this treatment is medically necessary

2. CRITERIA MET: List each clinical criterion that is satisfied, with specific values from the patient data

3. CRITERIA MISSING OR WEAK: List any criteria that are not met or need stronger documentation

4. GUIDELINE ALIGNMENT: Which clinical guidelines support (or contraindicate) this treatment for this patient

5. DOCUMENTATION GAPS: What additional documentation, if any, would strengthen the necessity case

6. OVERALL SCORE: Rate medical necessity as:
   - STRONG (high confidence of approval)
   - MODERATE (likely approvable with supplemental documentation)
   - WEAK (significant criteria unmet, likely requires alternative approach)
   - NOT INDICATED (treatment not appropriate for this patient)

7. RECOMMENDATION: Concise action recommendation for the ordering clinician"""

    response = llm_call(SYSTEM_PROMPT, user_prompt)

    # Infer score from response
    score = "moderate"
    lower = response.lower()
    if "strong" in lower and ("score: strong" in lower or "overall score: strong" in lower or "necessity: strong" in lower):
        score = "strong"
    elif "weak" in lower and "overall score: weak" in lower:
        score = "weak"
    elif "not indicated" in lower:
        score = "not_indicated"

    return {
        "patient_id": patient_id,
        "requested_treatment": requested_treatment,
        "treatment_type": treatment_type,
        "necessity_assessment": response,
        "overall_score": score,
        "fhir_data_used": True,
    }
