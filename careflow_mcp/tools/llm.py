"""
Shared LLM helper - Gemini 2.5 Flash via Google Generative Language API.
Supports two auth modes:
  1. Local dev: reads vertex_key.json file (set GOOGLE_APPLICATION_CREDENTIALS)
  2. Railway/Cloud: reads GOOGLE_CREDENTIALS_JSON env var (JSON string)
"""
import os
import json
import logging
import requests
import google.auth.transport.requests
from google.oauth2 import service_account

from config import GOOGLE_APPLICATION_CREDENTIALS, LLM_MODEL, LLM_MAX_TOKENS

logger = logging.getLogger("careflow.llm")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_cached_credentials = None


def _load_credentials() -> service_account.Credentials:
    """Load service account credentials from file or env var."""
    scopes = [
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/generative-language",
    ]

    # Priority 1: JSON string in env var (for Railway/cloud deployment)
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        logger.info("Loaded credentials from GOOGLE_CREDENTIALS_JSON env var")
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)

    # Priority 2: File path (for local dev with vertex_key.json)
    creds_path = GOOGLE_APPLICATION_CREDENTIALS
    if not os.path.isabs(creds_path):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        creds_path = os.path.join(base_dir, creds_path)

    if os.path.exists(creds_path):
        logger.info(f"Loaded credentials from file: {creds_path}")
        return service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)

    raise RuntimeError(
        "No Google credentials found. Set GOOGLE_CREDENTIALS_JSON env var "
        f"or place vertex_key.json at: {creds_path}"
    )


def _get_access_token() -> str:
    """Get a fresh OAuth2 access token, refreshing if needed."""
    global _cached_credentials

    if _cached_credentials is None:
        _cached_credentials = _load_credentials()

    auth_req = google.auth.transport.requests.Request()
    if not _cached_credentials.valid:
        logger.info("Refreshing expired OAuth2 token...")
        _cached_credentials.refresh(auth_req)

    return _cached_credentials.token


def _try_model(model_name: str, token: str, system_prompt: str, user_prompt: str) -> str:
    """Attempt a single Gemini model call. Raises on any failure."""
    url = f"{GEMINI_API_BASE}/{model_name}:generateContent"
    logger.info(f"Calling Gemini: model={model_name} prompt_len={len(user_prompt)}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "parts": [{"text": user_prompt}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": LLM_MAX_TOKENS,
            "temperature": 0.3,
        },
    }

    response = requests.post(url, headers=headers, json=payload, timeout=90)

    if not response.ok:
        logger.error(f"Gemini API error [{model_name}]: status={response.status_code} body={response.text[:500]}")
        response.raise_for_status()

    data = response.json()
    logger.info(f"Gemini response received, keys={list(data.keys())}")

    if "candidates" not in data:
        logger.error(f"No candidates in Gemini response: {json.dumps(data)[:500]}")
        raise RuntimeError(f"Gemini returned no candidates: {data.get('promptFeedback', data)}")

    candidate = data["candidates"][0]
    finish_reason = candidate.get("finishReason", "UNKNOWN")
    logger.info(f"Gemini finish_reason={finish_reason}")

    if finish_reason not in ("STOP", "MAX_TOKENS"):
        logger.error(f"Gemini unexpected finish reason: {finish_reason} full={json.dumps(candidate)[:500]}")
        raise RuntimeError(f"Gemini generation stopped unexpectedly: {finish_reason}")

    text = candidate["content"]["parts"][0]["text"]
    logger.info(f"Gemini text length: {len(text)} chars")
    return text


def llm_call(system_prompt: str, user_prompt: str) -> str:
    """
    Call the Gemini LLM with fallback model support.
    Returns the generated text or raises RuntimeError if all models fail.
    """
    token = _get_access_token()

    models_to_try = [LLM_MODEL, "gemini-2.0-flash", "gemini-1.5-flash"]
    last_exc = None

    for model in models_to_try:
        try:
            return _try_model(model, token, system_prompt, user_prompt)
        except Exception as exc:
            logger.warning(f"Model {model} failed: {exc}")
            last_exc = exc
            # Refresh token before trying next model
            try:
                token = _get_access_token()
            except Exception:
                pass

    raise RuntimeError(f"All Gemini models failed. Last error: {last_exc}")
