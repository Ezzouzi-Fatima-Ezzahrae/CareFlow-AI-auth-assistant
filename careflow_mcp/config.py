"""
CareFlow MCP Server - Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Google Vertex AI - Gemini models via service account
VERTEX_PROJECT_ID = os.getenv("VERTEX_PROJECT_ID", "gen-lang-client-0130300517")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "vertex_key.json")

FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "https://hapi.fhir.org/baseR4")
MCP_SERVER_HOST = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
MCP_SERVER_PORT = int(os.getenv("PORT", os.getenv("MCP_SERVER_PORT", "8000")))

# Gemini 2.5 Flash
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
LLM_MAX_TOKENS = 8192

# SHARP context header names (Prompt Opinion spec)
SHARP_PATIENT_ID_HEADER = "x-sharp-patient-id"
SHARP_FHIR_BASE_URL_HEADER = "x-sharp-fhir-base-url"
SHARP_FHIR_TOKEN_HEADER = "x-sharp-fhir-token"
