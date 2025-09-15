import os
from google_auth_oauthlib.flow import InstalledAppFlow
# from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/tasks"]
CREDS = "secrets/google/credentials.json"
TOKEN = "secrets/google/token.json"


def main():
    os.makedirs("secrets/google", exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(CREDS, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN, "w") as f:
        f.write(creds.to_json())
    print("Saved token to", TOKEN)


if __name__ == "__main__":
    main()
