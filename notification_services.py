import logging
import os
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class PushoverClient:
    """Minimal client for the Pushover notification service."""

    API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(
        self,
        app_token: Optional[str] = None,
        user_key: Optional[str] = None,
    ) -> None:
        self.app_token = app_token or os.getenv("PUSHOVER_APP_TOKEN")
        self.user_key = user_key or os.getenv("PUSHOVER_USER_KEY")

    def is_configured(self) -> bool:
        return bool(self.app_token and self.user_key)

    async def send_message(
        self,
        message: str,
        title: str = "Voice Assistant Notification",
        priority: int = 0,
        url: Optional[str] = None,
    ) -> Dict[str, str]:
        if not self.is_configured():
            raise RuntimeError("Pushover credentials are not configured.")

        payload = {
            "token": self.app_token,
            "user": self.user_key,
            "message": message,
            "title": title,
            "priority": priority,
        }
        if url:
            payload["url"] = url

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self.API_URL, data=payload)
            response.raise_for_status()
            logger.info("Pushover notification sent")
            return response.json()


class SendGridClient:
    """Lightweight SendGrid integration via the REST API."""

    API_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_sender: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("SENDGRID_API_KEY")
        self.default_sender = default_sender or os.getenv("SENDGRID_SENDER")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.default_sender)

    async def send_email(
        self,
        to_email: str,
        subject: str,
        content: str,
        sender_email: Optional[str] = None,
    ) -> Dict[str, str]:
        if not self.is_configured() and not (self.api_key and sender_email):
            raise RuntimeError("SendGrid credentials or sender email are not configured.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "personalizations": [
                {
                    "to": [{"email": to_email}],
                    "subject": subject,
                }
            ],
            "from": {"email": sender_email or self.default_sender},
            "content": [{"type": "text/plain", "value": content}],
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self.API_URL, headers=headers, json=payload)
            response.raise_for_status()
            logger.info("SendGrid email sent to %s", to_email)
            # SendGrid returns empty body on success; emulate a useful payload
            return {"status": "queued"}
