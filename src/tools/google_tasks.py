# src/tools/google_tasks.py

from __future__ import annotations

import json
import os
from typing import Optional, Dict, Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/tasks"]

# Local fallback file paths (used only when env vars are not present)
CREDS_FILE_FALLBACK = "secrets/google/credentials.json"
TOKEN_FILE_FALLBACK = "secrets/google/token.json"

# Environment variable names that Cloud Run receives via --update-secrets
ENV_TOKEN = "GOOGLE_TOKEN_FILE"
ENV_CREDS = "GOOGLE_CREDENTIALS_FILE"


def _load_json_from_env_or_file(env_name: str, local_path: str) -> Dict[str, Any]:
    """
    Load JSON from an environment variable (Cloud Run path) or a local file (dev path).
    The env var is expected to contain the *entire JSON document* as a string.
    """
    raw = os.environ.get(env_name)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"{env_name} is set but is not valid JSON: {e}") from e

    # Local development fallback
    with open(local_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_credentials() -> Credentials:
    """
    Construct google.oauth2.credentials.Credentials using either:
      - JSON from env vars (Cloud Run), or
      - local files under secrets/google (dev).
    If token.json doesn't include client_id/client_secret/token_uri, merge from credentials.json.
    """
    token_info = _load_json_from_env_or_file(ENV_TOKEN, TOKEN_FILE_FALLBACK)

    # Some token.json files (from quickstarts) already include these; if not, merge from client creds.
    need_client_bits = not all(
        k in token_info for k in ("client_id", "client_secret", "token_uri")
    )
    if need_client_bits:
        creds_info = _load_json_from_env_or_file(ENV_CREDS, CREDS_FILE_FALLBACK)
        installed = creds_info.get("installed") or creds_info.get("web") or {}
        token_info.setdefault("client_id", installed.get("client_id"))
        token_info.setdefault("client_secret", installed.get("client_secret"))
        token_info.setdefault("token_uri", installed.get("token_uri", "https://oauth2.googleapis.com/token"))

    # Build Credentials object
    creds = Credentials(
        token=token_info.get("token"),
        refresh_token=token_info.get("refresh_token"),
        client_id=token_info.get("client_id"),
        client_secret=token_info.get("client_secret"),
        token_uri=token_info.get("token_uri", "https://oauth2.googleapis.com/token"),
        scopes=SCOPES,
    )

    # If token is expired and we have a refresh_token, refresh in-memory (Cloud Run cannot persist)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds


def _service():
    """
    Build the Google Tasks API client.
    cache_discovery=False avoids writing to a cache directory (good for serverless).
    """
    creds = _build_credentials()
    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def default_tasklist_id() -> str:
    """
    Returns the first task list id if available, otherwise '@default'.
    """
    svc = _service()
    items = svc.tasklists().list(maxResults=50).execute().get("items", []) or []
    return items[0]["id"] if items else "@default"


def create_task(title: str, notes: Optional[str] = None, due_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a task in the user's default task list.
    - title: task title (required)
    - notes: optional notes/body
    - due_iso: optional RFC3339 timestamp, e.g. "2025-09-15T00:00:00Z"
    """
    svc = _service()
    body: Dict[str, Any] = {"title": title}
    if notes:
        body["notes"] = notes
    if due_iso:
        body["due"] = due_iso

    return svc.tasks().insert(tasklist=default_tasklist_id(), body=body).execute()
