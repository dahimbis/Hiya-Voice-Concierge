import json
import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - optional dependency
    service_account = None
    build = None


class GoogleCalendarClient:
    """Wrapper around Google Calendar API with service-account support."""

    SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> None:
        self.credentials_path = credentials_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        self.delegated_user = delegated_user or os.getenv("GOOGLE_CALENDAR_DELEGATED_USER")
        self.calendar_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")

        if not self.credentials_path and os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"):
            # Support embedding credentials via environment variable
            self.credentials_path = self._write_embedded_credentials(
                os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            )

        self._service = None

    def is_configured(self) -> bool:
        return bool(self.credentials_path and service_account and build)

    def _write_embedded_credentials(self, json_payload: str) -> str:
        path = os.path.join(os.getcwd(), ".service_account.json")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json_payload)
        return path

    @lru_cache(maxsize=1)
    def _get_credentials(self):
        if not self.is_configured():
            raise RuntimeError(
                "Google Calendar credentials are not configured or google-api-python-client is missing."
            )
        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_path, scopes=self.SCOPES
        )
        if self.delegated_user:
            credentials = credentials.with_subject(self.delegated_user)
        return credentials

    def _get_service(self):
        if self._service is None:
            credentials = self._get_credentials()
            self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    def list_upcoming_events(
        self,
        query: Optional[str] = None,
        within_days: int = 7,
        max_results: int = 5,
    ) -> List[Dict]:
        """Return upcoming events optionally filtered by a keyword."""
        if not self.is_configured():
            raise RuntimeError("Google Calendar client is not configured.")

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=within_days)).isoformat() + "Z"

        service = self._get_service()
        events_result = service.events().list(
            calendarId=self.calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
            q=query,
        ).execute()
        events = events_result.get("items", [])
        logger.debug("Fetched %s events from Google Calendar", len(events))
        return events
