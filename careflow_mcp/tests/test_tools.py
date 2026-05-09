"""
Quick smoke tests for CareFlow MCP tools.
Uses only synthetic data — no real PHI, no live FHIR server required.
Run with: python -m pytest tests/ -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fhir.synthetic_data import get_synthetic_patient_bundle, summarize_bundle_for_llm


def test_synthetic_bundle_structure():
    bundle = get_synthetic_patient_bundle("test-001")
    assert bundle["resourceType"] == "Bundle"
    assert len(bundle["entry"]) > 0
    resource_types = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert "Patient" in resource_types
    assert "Condition" in resource_types
    assert "MedicationRequest" in resource_types
    assert "Observation" in resource_types


def test_bundle_summarizer():
    bundle = get_synthetic_patient_bundle("test-001")
    summary = summarize_bundle_for_llm(bundle)
    assert "PATIENT:" in summary
    assert "ACTIVE CONDITIONS:" in summary
    assert "CURRENT MEDICATIONS:" in summary
    assert "RECENT LABS" in summary
    assert len(summary) > 200


def test_summary_contains_key_clinical_data():
    bundle = get_synthetic_patient_bundle("test-001")
    summary = summarize_bundle_for_llm(bundle)
    # Should contain the patient's key data
    assert "Diabetes" in summary or "diabetes" in summary
    assert "Metformin" in summary or "metformin" in summary
    assert "HbA1c" in summary or "hba1c" in summary.lower()


# Integration tests (require GEMINI_API_KEY — skip in CI if not set)
@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")
def test_generate_prior_auth_smoke():
    from tools.prior_auth import generate_prior_auth
    result = generate_prior_auth(
        patient_id="demo-001",
        requested_medication="Semaglutide 0.5mg weekly",
        indication="Type 2 Diabetes with inadequate glycemic control",
        payer_name="Test Payer",
    )
    assert "prior_auth_letter" in result
    assert len(result["prior_auth_letter"]) > 100
    assert result["fhir_data_used"] is True


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")
def test_estimate_approval_likelihood_smoke():
    from tools.approval_likelihood import estimate_approval_likelihood
    result = estimate_approval_likelihood(
        patient_id="demo-001",
        requested_medication="Semaglutide 0.5mg weekly",
        indication="Type 2 Diabetes",
        payer_type="commercial",
    )
    assert "approval_assessment" in result
    assert result["likelihood_label"] in ["high", "moderate", "low", "very_low"]
