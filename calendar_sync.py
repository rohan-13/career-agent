"""Phase 5: Google Calendar sync for approved + registered events."""
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.json"

TZ_MAP = {"ET": "America/New_York", "CT": "America/Chicago", "MT": "America/Denver", "PT": "America/Los_Angeles", "UTC": "UTC"}


def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def add_to_calendar(event):
    service = get_service()
    start_dt = f"{event['date']}T{event['time'] or '09:00'}:00"
    tz = TZ_MAP.get(event.get("timezone") or "ET", "America/New_York")
    body = {
        "summary": f"[CAREER] {event['company']} — {event['title']}",
        "description": f"{event['description']}\n\nRSVP: {event['url']}\nSource: {event['source']}",
        "location": event["location"],
        "start": {"dateTime": start_dt, "timeZone": tz},
        "end": {"dateTime": start_dt, "timeZone": tz},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 1440},
                {"method": "popup", "minutes": 60},
            ],
        },
    }
    service.events().insert(calendarId="primary", body=body).execute()
    print(f"✓ Added to calendar: {event['title']}")
