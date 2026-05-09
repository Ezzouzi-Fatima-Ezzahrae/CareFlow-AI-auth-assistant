"""
Shared context variables for passing SHARP headers from HTTP request into tool handlers.
"""
import contextvars

sharp_patient_id_var = contextvars.ContextVar('sharp_patient_id', default='')
sharp_fhir_base_url_var = contextvars.ContextVar('sharp_fhir_base_url', default='')
sharp_fhir_token_var = contextvars.ContextVar('sharp_fhir_token', default='')
