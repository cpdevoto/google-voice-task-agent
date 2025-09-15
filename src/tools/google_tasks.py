from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/tasks"]
CREDS = "secrets/google/credentials.json"
TOKEN = "secrets/google/token.json"


def _service():
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    return build("tasks", "v1", credentials=creds)


def default_tasklist_id():
    svc = _service()
    items = svc.tasklists().list(maxResults=50).execute().get("items", [])
    # Usually the first one is "Tasks"; fallback to '@default'
    return items[0]["id"] if items else "@default"


def create_task(title: str,
                notes: str | None = None, due_iso: str | None = None):
    svc = _service()
    body = {"title": title}
    if notes:
        body["notes"] = notes
    if due_iso:
        body["due"] = due_iso  # e.g., "2025-09-15T00:00:00Z"
    return svc.tasks().insert(
        tasklist=default_tasklist_id(), body=body).execute()
