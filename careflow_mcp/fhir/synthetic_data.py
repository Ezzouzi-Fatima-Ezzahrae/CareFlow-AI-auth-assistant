"""
CareFlow — Synthetic FHIR Patient Data
Realistic de-identified patient bundles for demo and testing.
All data is entirely fictional. No PHI.
"""


def get_synthetic_patient_bundle(patient_id: str = "demo-001") -> dict:
    """
    Returns a realistic synthetic FHIR R4 Bundle for demo purposes.
    Scenario: 58-year-old with Type 2 Diabetes, hypertension, and CKD Stage 3
    requiring prior authorization for a GLP-1 agonist (semaglutide).
    """
    return {
        "resourceType": "Bundle",
        "id": f"bundle-{patient_id}",
        "type": "collection",
        "entry": [
            # --- Patient ---
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": patient_id,
                    "name": [{"family": "Johnson", "given": ["Marcus", "A."]}],
                    "gender": "male",
                    "birthDate": "1966-03-14",
                    "address": [{"city": "Chicago", "state": "IL", "postalCode": "60601"}],
                }
            },
            # --- Conditions ---
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-dm2",
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {
                        "coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Type 2 diabetes mellitus"}],
                        "text": "Type 2 Diabetes Mellitus",
                    },
                    "onsetDateTime": "2014-06-01",
                    "subject": {"reference": f"Patient/{patient_id}"},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-htn",
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {
                        "coding": [{"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertension"}],
                        "text": "Hypertension",
                    },
                    "onsetDateTime": "2016-09-15",
                    "subject": {"reference": f"Patient/{patient_id}"},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-ckd",
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {
                        "coding": [{"system": "http://snomed.info/sct", "code": "433144002", "display": "Chronic kidney disease stage 3"}],
                        "text": "Chronic Kidney Disease, Stage 3",
                    },
                    "onsetDateTime": "2020-02-10",
                    "subject": {"reference": f"Patient/{patient_id}"},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-obesity",
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {
                        "coding": [{"system": "http://snomed.info/sct", "code": "414916001", "display": "Obesity"}],
                        "text": "Obesity (BMI 34.2)",
                    },
                    "onsetDateTime": "2018-01-01",
                    "subject": {"reference": f"Patient/{patient_id}"},
                }
            },
            # --- Current Medications ---
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "med-metformin",
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": {
                        "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "860975", "display": "Metformin 1000 MG"}],
                        "text": "Metformin 1000mg twice daily",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "authoredOn": "2014-06-01",
                    "dosageInstruction": [{"text": "1000mg orally twice daily with meals"}],
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "med-lisinopril",
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": {
                        "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "29046", "display": "Lisinopril 10 MG"}],
                        "text": "Lisinopril 10mg once daily",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "authoredOn": "2016-09-15",
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "med-glipizide",
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": {
                        "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "4815", "display": "Glipizide 5 MG"}],
                        "text": "Glipizide 5mg twice daily",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "authoredOn": "2019-03-01",
                }
            },
            # --- Requested Medication (the PA target) ---
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "med-semaglutide-requested",
                    "status": "draft",
                    "intent": "proposal",
                    "medicationCodeableConcept": {
                        "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "2200349", "display": "Semaglutide 1 MG/ML Injectable Solution"}],
                        "text": "Semaglutide (Ozempic) 0.5mg weekly subcutaneous injection",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "authoredOn": "2026-05-07",
                    "note": [{"text": "Requested for glycemic control given inadequate response to current regimen. Also addresses obesity and may provide renal protection."}],
                }
            },
            # --- Lab Results ---
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-hba1c",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c/Hemoglobin.total in Blood"}],
                        "text": "HbA1c",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "effectiveDateTime": "2026-04-15",
                    "valueQuantity": {"value": 8.9, "unit": "%", "system": "http://unitsofmeasure.org"},
                    "referenceRange": [{"high": {"value": 7.0, "unit": "%"}, "text": "Target < 7.0%"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-egfr",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "98979-8", "display": "Glomerular filtration rate"}],
                        "text": "eGFR",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "effectiveDateTime": "2026-04-15",
                    "valueQuantity": {"value": 42, "unit": "mL/min/1.73m2", "system": "http://unitsofmeasure.org"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-bmi",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "39156-5", "display": "Body mass index (BMI)"}],
                        "text": "BMI",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "effectiveDateTime": "2026-04-15",
                    "valueQuantity": {"value": 34.2, "unit": "kg/m2", "system": "http://unitsofmeasure.org"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-bp",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "55284-4", "display": "Blood pressure systolic and diastolic"}],
                        "text": "Blood Pressure",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "effectiveDateTime": "2026-04-20",
                    "component": [
                        {"code": {"coding": [{"code": "8480-6", "display": "Systolic"}]}, "valueQuantity": {"value": 148, "unit": "mmHg"}},
                        {"code": {"coding": [{"code": "8462-4", "display": "Diastolic"}]}, "valueQuantity": {"value": 92, "unit": "mmHg"}},
                    ],
                }
            },
            # --- Allergies ---
            {
                "resource": {
                    "resourceType": "AllergyIntolerance",
                    "id": "allergy-sulfa",
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {"coding": [{"system": "http://snomed.info/sct", "code": "387406002", "display": "Sulfonamide"}], "text": "Sulfa drugs"},
                    "reaction": [{"manifestation": [{"coding": [{"display": "Rash, urticaria"}]}], "severity": "moderate"}],
                    "patient": {"reference": f"Patient/{patient_id}"},
                }
            },
        ],
    }


def summarize_bundle_for_llm(bundle: dict) -> str:
    """
    Converts a FHIR bundle into a compact, readable clinical summary string
    for use in LLM prompts. Avoids sending raw JSON to the model.
    """
    lines = []
    patient_name = "Unknown"
    patient_dob = ""
    patient_gender = ""

    conditions = []
    medications = []
    labs = []
    allergies = []
    requested_med = None

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        rtype = resource.get("resourceType", "")

        if rtype == "Patient":
            name = resource.get("name", [{}])[0]
            given = " ".join(name.get("given", []))
            family = name.get("family", "")
            patient_name = f"{given} {family}".strip()
            patient_dob = resource.get("birthDate", "")
            patient_gender = resource.get("gender", "")

        elif rtype == "Condition":
            text = resource.get("code", {}).get("text", "")
            onset = resource.get("onsetDateTime", "")[:4] if resource.get("onsetDateTime") else ""
            if text:
                conditions.append(f"{text} (since {onset})" if onset else text)

        elif rtype == "MedicationRequest":
            text = resource.get("medicationCodeableConcept", {}).get("text", "")
            status = resource.get("status", "")
            if status == "draft" or resource.get("intent") == "proposal":
                requested_med = text
            elif text:
                medications.append(text)

        elif rtype == "Observation":
            code_text = resource.get("code", {}).get("text", "")
            val = resource.get("valueQuantity", {})
            value = val.get("value", "")
            unit = val.get("unit", "")
            date = resource.get("effectiveDateTime", "")[:10]
            # Handle blood pressure components
            if resource.get("component"):
                bp_vals = []
                for comp in resource["component"]:
                    cv = comp.get("valueQuantity", {})
                    bp_vals.append(str(cv.get("value", "")))
                labs.append(f"{code_text}: {'/'.join(bp_vals)} mmHg (on {date})")
            elif value:
                labs.append(f"{code_text}: {value} {unit} (on {date})")

        elif rtype == "AllergyIntolerance":
            text = resource.get("code", {}).get("text", "")
            reactions = []
            for r in resource.get("reaction", []):
                for m in r.get("manifestation", []):
                    for c in m.get("coding", []):
                        if c.get("display"):
                            reactions.append(c["display"])
            allergy_str = text
            if reactions:
                allergy_str += f" — reaction: {', '.join(reactions)}"
            allergies.append(allergy_str)

    lines.append(f"PATIENT: {patient_name}, DOB: {patient_dob}, Gender: {patient_gender}")
    lines.append(f"\nACTIVE CONDITIONS:\n" + "\n".join(f"  - {c}" for c in conditions))
    lines.append(f"\nCURRENT MEDICATIONS:\n" + "\n".join(f"  - {m}" for m in medications))
    if requested_med:
        lines.append(f"\nREQUESTED MEDICATION (pending prior authorization):\n  - {requested_med}")
    lines.append(f"\nRECENT LABS / VITALS:\n" + "\n".join(f"  - {l}" for l in labs))
    lines.append(f"\nALLERGIES:\n" + "\n".join(f"  - {a}" for a in allergies))

    return "\n".join(lines)
