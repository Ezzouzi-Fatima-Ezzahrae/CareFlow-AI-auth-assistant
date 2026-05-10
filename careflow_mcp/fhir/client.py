"""
CareFlow FHIR Client
Fetches patient resources from any FHIR R4 server.
Falls back to synthetic data when server is unavailable.
"""
import logging
import httpx
from typing import Optional
from config import FHIR_BASE_URL
from fhir.synthetic_data import get_synthetic_patient_bundle

logger = logging.getLogger("careflow.fhir")


class FHIRClient:
    def __init__(self, base_url: str = FHIR_BASE_URL, token: Optional[str] = None):
        base = (base_url or "").rstrip("/")
        # Po sometimes sends the workspace URL without /fhir suffix — normalise it
        if base and not base.endswith("/fhir") and "/fhir" not in base.split("/")[-1]:
            base = base + "/fhir"
        self.base_url = base
        headers = {
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        }
        if token:
            # Prompt Opinion sends token with "Bearer " prefix already included
            if token.startswith("Bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(headers=headers, timeout=15)

    def get_patient_bundle(self, patient_id: str) -> dict:
        """
        Fetch a comprehensive FHIR bundle for a patient.
        Falls back to synthetic data if the server is unreachable.
        """
        logger.info(f"FHIR fetch: base_url={self.base_url!r} patient_id={patient_id}")

        if not self.base_url:
            logger.info("No FHIR base URL - using synthetic data fallback")
            return get_synthetic_patient_bundle(patient_id)

        try:
            bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}

            patient = self._get(f"Patient/{patient_id}")
            bundle["entry"].append({"resource": patient})

            conditions = self._search("Condition", {"patient": patient_id, "clinical-status": "active"})
            bundle["entry"].extend(conditions.get("entry", []))

            meds = self._search("MedicationRequest", {"patient": patient_id, "status": "active"})
            bundle["entry"].extend(meds.get("entry", []))

            obs = self._search("Observation", {"patient": patient_id, "_sort": "-date", "_count": "10"})
            bundle["entry"].extend(obs.get("entry", []))

            allergies = self._search("AllergyIntolerance", {"patient": patient_id})
            bundle["entry"].extend(allergies.get("entry", []))

            logger.info(f"FHIR bundle: {len(bundle['entry'])} resources fetched")
            return bundle

        except Exception as exc:
            logger.warning(f"FHIR fetch failed ({exc}) - using synthetic data fallback")
            return get_synthetic_patient_bundle(patient_id)

    def _get(self, path: str) -> dict:
        r = self.client.get(f"{self.base_url}/{path}")
        r.raise_for_status()
        return r.json()

    def _search(self, resource_type: str, params: dict) -> dict:
        r = self.client.get(f"{self.base_url}/{resource_type}", params=params)
        r.raise_for_status()
        return r.json()
