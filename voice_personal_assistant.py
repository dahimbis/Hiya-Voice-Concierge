import asyncio
import base64
import inspect
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from database import CalendarEvent, Conversation, DatabaseManager, init_database
from notification_services import PushoverClient, SendGridClient
from calendar_service import GoogleCalendarClient
from run_voice_agent import run_voice_agent

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None

logger = logging.getLogger(__name__)

# Ensure tables exist when module is imported.
init_database()


@dataclass
class VoiceInteractionResult:
    transcription: str
    response_text: str
    audio_path: Optional[str]
    intent: str
    confidence: float
    calendar_events: List[Dict[str, Any]] = field(default_factory=list)
    notifications: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SpeechService:
    """Handles speech-to-text and text-to-speech with OpenAI models."""

    def __init__(
        self,
        stt_model: str = "whisper-1",
        tts_model: str = "gpt-4o-mini-tts",
        tts_voice: str = "alloy",
    ) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key and OpenAI else None
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.output_dir = Path("output/audio")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def is_configured(self) -> bool:
        return self.client is not None

    async def transcribe(self, audio_path: str) -> str:
        if not self.is_configured():
            raise RuntimeError("Speech service is not configured. Provide OPENAI_API_KEY.")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file {audio_path} not found.")

        def _transcribe() -> str:
            with open(audio_path, "rb") as audio_file:
                result = self.client.audio.transcriptions.create(
                    model=self.stt_model,
                    file=audio_file,
                    response_format="text",
                )
            return result

        return await asyncio.to_thread(_transcribe)

    async def synthesize(self, text: str) -> Optional[str]:
        if not self.is_configured():
            return None
        if not text.strip():
            return None

        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        output_path = self.output_dir / f"assistant_{timestamp}.mp3"

        def _synthesize() -> str:
            request_args: Dict[str, Any] = {
                "model": self.tts_model,
                "voice": self.tts_voice,
                "input": text,
            }

            try:
                create_fn = self.client.audio.speech.with_streaming_response.create
                supported_params = set(inspect.signature(create_fn).parameters)
            except (AttributeError, TypeError, ValueError):
                create_fn = None
                supported_params = set()

            if "format" in supported_params:
                request_args["format"] = "mp3"
            elif "audio_format" in supported_params:
                request_args["audio_format"] = "mp3"

            # Try streaming first (when supported and stable).
            if create_fn is not None:
                try:
                    ctx = create_fn(**request_args)
                except TypeError as exc:
                    # Retry without format arguments if they are unsupported.
                    request_args.pop("format", None)
                    request_args.pop("audio_format", None)
                    try:
                        ctx = create_fn(**request_args)
                    except TypeError:
                        logger.warning("Streaming TTS unsupported, falling back to non-streaming: %s", exc)
                        ctx = None
                if ctx is not None:
                    with ctx as response:
                        response.stream_to_file(output_path)
                    return str(output_path)

            # Fallback: non-streaming API (works on older SDKs).
            non_stream_args = {k: v for k, v in request_args.items() if k in {"model", "voice", "input"}}
            response = self.client.audio.speech.create(**non_stream_args)
            audio_payload = getattr(response, "audio", None)
            if not audio_payload and hasattr(response, "data"):
                first = response.data[0] if response.data else None
                audio_payload = getattr(first, "audio", None) if first else None
            if not audio_payload and isinstance(response, dict):
                audio_payload = response.get("audio")

            if isinstance(audio_payload, bytes):
                audio_bytes = audio_payload
            else:
                audio_bytes = base64.b64decode(audio_payload) if audio_payload else b""

            with open(output_path, "wb") as audio_file:
                audio_file.write(audio_bytes)

            return str(output_path)

        try:
            return await asyncio.to_thread(_synthesize)
        except Exception as exc:  # pragma: no cover - best effort
            logger.error("Failed to synthesize speech: %s", exc, exc_info=True)
            return None


class VoicePersonalAssistant:
    """Core orchestrator that ties together intent parsing and tool execution."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.db = DatabaseManager()
        self.speech = SpeechService()
        self.calendar_client = GoogleCalendarClient()
        self.pushover_client = PushoverClient()
        self.sendgrid_client = SendGridClient()

    async def handle_audio(self, audio_path: str) -> VoiceInteractionResult:
        errors: List[str] = []
        try:
            transcription = await self.speech.transcribe(audio_path)
        except Exception as exc:
            logger.exception("Transcription failed")
            transcription = ""
            errors.append(f"Transcription failed: {exc}")

        if not transcription:
            transcription = "I could not transcribe your audio. Please try again."
        else:
            logger.info("Transcription result: %s", transcription)

        agent_result = await run_voice_agent(transcription, user_id=str(self.user_id))
        intent = agent_result.get("intent", "unknown")
        confidence = float(agent_result.get("confidence", 0.0))
        parameters = agent_result.get("parameters", {}) or {}
        follow_up = agent_result.get("follow_up")

        execution = await self._execute_intent(intent, parameters, follow_up)
        errors.extend(execution.get("errors", []))

        response_text = execution.get("response_text") or agent_result.get(
            "summary", "I processed your request."
        )
        calendar_events = execution.get("calendar_events", [])
        notifications = execution.get("notifications", [])

        audio_output = await self.speech.synthesize(response_text)

        self._persist_conversation(
            transcription=transcription,
            response=response_text,
            intent=intent,
            confidence=confidence,
        )

        return VoiceInteractionResult(
            transcription=transcription,
            response_text=response_text,
            audio_path=audio_output,
            intent=intent,
            confidence=confidence,
            calendar_events=calendar_events,
            notifications=notifications,
            errors=errors,
        )

    async def _execute_intent(
        self,
        intent: str,
        parameters: Dict[str, Any],
        follow_up: Optional[str],
    ) -> Dict[str, Any]:
        intent = intent or "unknown"
        handlers = {
            "calendar_lookup": self._handle_calendar_lookup,
            "push_notification": self._handle_push_notification,
            "send_email": self._handle_send_email,
            "smalltalk": self._handle_smalltalk,
            "clarification": self._handle_clarification,
        }
        handler = handlers.get(intent, self._handle_unknown)
        return await handler(parameters, follow_up)

    async def _handle_calendar_lookup(
        self, parameters: Dict[str, Any], follow_up: Optional[str]
    ) -> Dict[str, Any]:
        keyword = parameters.get("keyword") or parameters.get("subject")
        within_days = parameters.get("within_days", 7)
        max_results = parameters.get("max_results", 5)

        response_text = ""
        events: List[Dict[str, Any]] = []
        errors: List[str] = []

        if not self.calendar_client.is_configured():
            errors.append(
                "Google Calendar integration is not configured. "
                "Set GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON."
            )
        else:
            try:
                events = self.calendar_client.list_upcoming_events(
                    query=keyword, within_days=int(within_days), max_results=int(max_results)
                )
                response_text = self._format_calendar_response(events, keyword)
                self._sync_calendar_events(events)
            except Exception as exc:  # pragma: no cover
                logger.exception("Calendar lookup failed")
                errors.append(f"Calendar lookup failed: {exc}")

        if not response_text and not errors:
            response_text = "I could not find any matching events in your calendar."

        return {
            "response_text": response_text,
            "calendar_events": events,
            "notifications": [],
            "errors": errors,
        }

    async def _handle_push_notification(
        self, parameters: Dict[str, Any], follow_up: Optional[str]
    ) -> Dict[str, Any]:
        message = parameters.get("message") or parameters.get("content")
        title = parameters.get("title") or "Reminder from Hiya Assistant"
        priority = int(parameters.get("priority", 0))
        errors: List[str] = []
        notifications: List[Dict[str, Any]] = []

        if not message:
            return {
                "response_text": "What would you like me to include in the push notification?",
                "calendar_events": [],
                "notifications": [],
                "errors": [],
            }

        if not self.pushover_client.is_configured():
            errors.append("Pushover credentials are not configured.")
        else:
            try:
                result = await self.pushover_client.send_message(
                    message=message, title=title, priority=priority
                )
                notifications.append({"channel": "pushover", "result": result})
            except Exception as exc:  # pragma: no cover
                logger.exception("Pushover notification failed")
                errors.append(f"Pushover notification failed: {exc}")

        response_text = (
            "I sent your push notification." if not errors else "I could not send the push notification."
        )
        return {
            "response_text": response_text,
            "calendar_events": [],
            "notifications": notifications,
            "errors": errors,
        }

    async def _handle_send_email(
        self, parameters: Dict[str, Any], follow_up: Optional[str]
    ) -> Dict[str, Any]:
        to_email = parameters.get("to_email") or parameters.get("recipient")
        subject = parameters.get("subject") or "Update from Hiya Assistant"
        body = parameters.get("body") or parameters.get("message")
        errors: List[str] = []
        notifications: List[Dict[str, Any]] = []

        if not to_email:
            return {
                "response_text": "Who should I email? Please provide an email address.",
                "calendar_events": [],
                "notifications": [],
                "errors": [],
            }

        if not body:
            return {
                "response_text": "What would you like me to say in the email?",
                "calendar_events": [],
                "notifications": [],
                "errors": [],
            }

        if not self.sendgrid_client.is_configured():
            errors.append("SendGrid credentials are not configured.")
        else:
            try:
                result = await self.sendgrid_client.send_email(
                    to_email=to_email,
                    subject=subject,
                    content=body,
                )
                notifications.append({"channel": "sendgrid", "result": result})
            except Exception as exc:  # pragma: no cover
                logger.exception("SendGrid email failed")
                errors.append(f"SendGrid email failed: {exc}")

        response_text = (
            "I sent the email as requested." if not errors else "I could not send the email."
        )
        return {
            "response_text": response_text,
            "calendar_events": [],
            "notifications": notifications,
            "errors": errors,
        }

    async def _handle_smalltalk(
        self, parameters: Dict[str, Any], follow_up: Optional[str]
    ) -> Dict[str, Any]:
        response_text = parameters.get("reply") or "Happy to help! What else can I do for you?"
        return {
            "response_text": response_text,
            "calendar_events": [],
            "notifications": [],
            "errors": [],
        }

    async def _handle_clarification(
        self, parameters: Dict[str, Any], follow_up: Optional[str]
    ) -> Dict[str, Any]:
        question = follow_up or parameters.get("question") or "Could you clarify what you need?"
        return {
            "response_text": question,
            "calendar_events": [],
            "notifications": [],
            "errors": [],
        }

    async def _handle_unknown(
        self, parameters: Dict[str, Any], follow_up: Optional[str]
    ) -> Dict[str, Any]:
        return {
            "response_text": "I'm not sure how to help with that yet, but I'm learning every day!",
            "calendar_events": [],
            "notifications": [],
            "errors": [],
        }

    def _format_calendar_response(self, events: List[Dict[str, Any]], keyword: Optional[str]) -> str:
        if not events:
            return "I didn't find any upcoming events that match your request."

        keyword_text = f" related to {keyword}" if keyword else ""
        lines = [f"Here are your next {len(events)} events{keyword_text}:"]

        for event in events:
            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
            summary = event.get("summary", "Untitled event")
            location = event.get("location")
            start_display = self._format_datetime(start)
            end_display = self._format_datetime(end) if end else ""
            entry = f"- {summary} on {start_display}"
            if end_display and end_display != start_display:
                entry += f" until {end_display}"
            if location:
                entry += f" at {location}"
            lines.append(entry)

        return "\n".join(lines)

    def _format_datetime(self, value: Optional[str]) -> str:
        if not value:
            return "an unspecified time"
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%b %d at %I:%M %p")
        except ValueError:
            return value

    def _sync_calendar_events(self, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        with self.db.get_session() as session:
            for event in events:
                external_id = event.get("id")
                if not external_id:
                    continue
                start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
                end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
                start_dt = self._parse_datetime(start)
                end_dt = self._parse_datetime(end) if end else None
                record = (
                    session.query(CalendarEvent)
                    .filter_by(user_id=self.user_id, external_id=external_id)
                    .one_or_none()
                )
                if record:
                    record.title = event.get("summary", record.title)
                    record.description = event.get("description", record.description)
                    record.start_time = start_dt or record.start_time
                    record.end_time = end_dt or record.end_time
                else:
                    session.add(
                        CalendarEvent(
                            user_id=self.user_id,
                            external_id=external_id,
                            title=event.get("summary", "Untitled event"),
                            description=event.get("description"),
                            start_time=start_dt or datetime.utcnow(),
                            end_time=end_dt,
                        )
                    )

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _persist_conversation(
        self, transcription: str, response: str, intent: str, confidence: float
    ) -> None:
        with self.db.get_session() as session:
            session.add(
                Conversation(
                    user_id=self.user_id,
                    user_message=transcription,
                    ai_response=response,
                    intent=intent,
                    confidence=int(confidence * 100),
                )
            )
