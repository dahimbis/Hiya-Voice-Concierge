import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import gradio as gr
import jwt
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

from database import Conversation, DatabaseManager, User, init_database
from voice_personal_assistant import VoiceInteractionResult, VoicePersonalAssistant

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY", "replace-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

db_manager = DatabaseManager()
init_database()


class AuthenticationError(Exception):
    """Raised when authentication fails."""


class AuthenticationManager:
    def create_access_token(self, data: Dict, expires_delta: Optional[timedelta] = None) -> str:
        payload = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        payload.update({"exp": expire})
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def verify_token(self, token: str) -> Dict:
        try:
            decoded_token = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            if datetime.fromtimestamp(decoded_token["exp"]) <= datetime.utcnow():
                raise AuthenticationError("Token expired.")
            return decoded_token
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Token is invalid.") from exc


auth_manager = AuthenticationManager()


def register_user(username: str, email: str, password: str, confirm_password: str) -> Dict:
    if not username or len(username) < 3 or len(username) > 20 or not username.replace("_", "").isalnum():
        return {"success": False, "message": "Username must be 3-20 characters and alphanumeric."}
    if password != confirm_password:
        return {"success": False, "message": "Passwords do not match."}
    if len(password) < 8:
        return {"success": False, "message": "Password must be at least 8 characters long."}

    with db_manager.get_session() as session:
        existing = (
            session.query(User)
            .filter((User.username == username) | (User.email == email))
            .one_or_none()
        )
        if existing:
            return {"success": False, "message": "An account with that username or email already exists."}

        try:
            user = User(username=username, email=email, password_hash=User.hash_password(password))
            session.add(user)
            logger.info("Registered new user %s", username)
            return {"success": True, "message": "Registration successful. You can log in now."}
        except SQLAlchemyError as exc:
            logger.error("Registration failed: %s", exc, exc_info=True)
            return {"success": False, "message": "Registration failed. Please try again."}


def user_login(username_or_email: str, password: str) -> Dict:
    with db_manager.get_session() as session:
        user = (
            session.query(User)
            .filter((User.username == username_or_email) | (User.email == username_or_email))
            .one_or_none()
        )
        if user and user.verify_password(password):
            token = auth_manager.create_access_token({"sub": user.username})
            user.last_login = datetime.utcnow()
            return {"success": True, "access_token": token, "username": user.username, "user_id": user.id}
    return {"success": False, "message": "Invalid username, email, or password."}


def get_user_from_token(token: str) -> Dict:
    if not token:
        raise AuthenticationError("Missing access token. Please log in.")

    decoded = auth_manager.verify_token(token)
    username = decoded.get("sub")

    with db_manager.get_session() as session:
        user = session.query(User).filter_by(username=username).one_or_none()
        if not user:
            raise AuthenticationError("User not found.")
        return {"id": user.id, "username": user.username, "email": user.email, "is_active": user.is_active}


def get_recent_conversations(user_id: int, limit: int = 5) -> List[Conversation]:
    with db_manager.get_session() as session:
        return (
            session.query(Conversation)
            .filter_by(user_id=user_id)
            .order_by(Conversation.timestamp.desc())
            .limit(limit)
            .all()
        )


def register_interface(username, email, password, confirm_password, terms) -> str:
    if not terms:
        return "You must accept the terms of service."
    result = register_user(username, email, password, confirm_password)
    return result["message"]


def login_interface(username_or_email, password) -> Tuple[str, Optional[str], Optional[str]]:
    result = user_login(username_or_email, password)
    if result["success"]:
        greeting = f"Welcome back, {result['username']}!"
        return greeting, result["access_token"], result["username"]
    return result["message"], None, None


def dashboard_interface(access_token) -> str:
    try:
        user = get_user_from_token(access_token)
    except AuthenticationError as exc:
        return str(exc)

    conversations = get_recent_conversations(user["id"], limit=5)
    if not conversations:
        return f"Welcome to your dashboard, {user['username']}! No recent activity yet."

    lines = [f"Welcome to your dashboard, {user['username']}!", "", "Recent conversations:"]
    for convo in conversations:
        timestamp = convo.timestamp.strftime("%b %d %I:%M %p")
        lines.append(f"[{timestamp}] You: {convo.user_message}")
        lines.append(f" - Assistant: {convo.ai_response}")
    return "\n".join(lines)


def _format_calendar_for_json(events: List[Dict]) -> List[Dict]:
    formatted = []
    for event in events:
        formatted.append(
            {
                "summary": event.get("summary"),
                "start": event.get("start"),
                "end": event.get("end"),
                "location": event.get("location"),
                "status": event.get("status"),
                "htmlLink": event.get("htmlLink"),
            }
        )
    return formatted


def _format_notifications_for_json(items: List[Dict]) -> List[Dict]:
    formatted = []
    for item in items:
        formatted.append({"channel": item.get("channel"), "status": item.get("result")})
    return formatted


async def voice_assistant_interface(audio_input, access_token):
    if not access_token:
        return (
            "Authentication required.",
            "Please log in to use the voice assistant.",
            None,
            [],
            [],
            "unauthenticated",
            0.0,
            "You must log in before using the assistant.",
        )
    if not audio_input:
        return (
            "",
            "Please provide an audio recording to process.",
            None,
            [],
            [],
            "no_audio",
            0.0,
            "",
        )

    try:
        user = get_user_from_token(access_token)
    except AuthenticationError as exc:
        return (
            "",
            str(exc),
            None,
            [],
            [],
            "unauthenticated",
            0.0,
            str(exc),
        )

    assistant = VoicePersonalAssistant(user_id=user["id"])
    result: VoiceInteractionResult = await assistant.handle_audio(audio_input)

    errors = "\n".join(result.errors) if result.errors else ""
    calendar_json = _format_calendar_for_json(result.calendar_events)
    notification_json = _format_notifications_for_json(result.notifications)
    confidence_pct = round(result.confidence * 100, 1)

    return (
        result.transcription,
        result.response_text,
        result.audio_path,
        calendar_json,
        notification_json,
        result.intent,
        confidence_pct,
        errors,
    )


def build_interface() -> gr.Blocks:
    with gr.Blocks(theme=gr.themes.Soft(), title="Hiya Voice Concierge") as demo:
        gr.Markdown("## Hiya Voice Concierge\nPlan trips, track appointments, and stay informed with voice.")

        access_token_state = gr.State()
        active_username_state = gr.State()

        with gr.Tabs():
            with gr.TabItem("Authentication"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### Register")
                        register_username = gr.Textbox(label="Username", placeholder="Choose a username")
                        register_email = gr.Textbox(label="Email", placeholder="name@email.com")
                        register_password = gr.Textbox(label="Password", type="password")
                        register_confirm = gr.Textbox(label="Confirm Password", type="password")
                        register_terms = gr.Checkbox(label="I accept the Terms of Service")
                        register_button = gr.Button("Register", variant="primary")
                        register_status = gr.Textbox(label="Registration Status", interactive=False)

                        register_button.click(
                            fn=register_interface,
                            inputs=[register_username, register_email, register_password, register_confirm, register_terms],
                            outputs=register_status,
                        )

                    with gr.Column():
                        gr.Markdown("### Login")
                        login_username_or_email = gr.Textbox(label="Username or Email")
                        login_password = gr.Textbox(label="Password", type="password")
                        login_button = gr.Button("Login", variant="primary")
                        login_status = gr.Textbox(label="Login Status", interactive=False)

                        login_button.click(
                            fn=login_interface,
                            inputs=[login_username_or_email, login_password],
                            outputs=[login_status, access_token_state, active_username_state],
                        )

            with gr.TabItem("Dashboard"):
                gr.Markdown("### User Dashboard")
                dashboard_button = gr.Button("Load Dashboard", variant="primary")
                dashboard_output = gr.Textbox(label="Dashboard Overview", interactive=False, lines=8)

                dashboard_button.click(
                    fn=dashboard_interface,
                    inputs=[access_token_state],
                    outputs=dashboard_output,
                )

            with gr.TabItem("Voice Assistant"):
                gr.Markdown("### Voice Interaction")
                gr.Markdown(
                    "Record a request (e.g., *\"What are my upcoming flights this week?\"*). "
                    "The assistant transcribes, reasons, and performs integrated actions."
                )

                audio_input = gr.Audio(sources=["microphone"], type="filepath", label="Record your voice")
                process_button = gr.Button("Process Voice Command", variant="primary")
                reset_button = gr.Button("Reset", variant="secondary")

                transcription_output = gr.Textbox(label="Transcription", interactive=False, lines=2)
                response_output = gr.Textbox(label="Assistant Response", interactive=False, lines=4)
                audio_output = gr.Audio(label="Assistant Audio", type="filepath", interactive=False, autoplay=True)

                with gr.Accordion("Action Details", open=False):
                    intent_output = gr.Textbox(label="Detected Intent", interactive=False)
                    confidence_output = gr.Number(label="Intent Confidence (%)", interactive=False, precision=1)
                    calendar_output = gr.JSON(label="Calendar Events")
                    notifications_output = gr.JSON(label="Notifications")
                    error_output = gr.Textbox(label="Errors", interactive=False, lines=2)

                process_button.click(
                    fn=voice_assistant_interface,
                    inputs=[audio_input, access_token_state],
                    outputs=[
                        transcription_output,
                        response_output,
                        audio_output,
                        calendar_output,
                        notifications_output,
                        intent_output,
                        confidence_output,
                        error_output,
                    ],
                )

                reset_button.click(
                    fn=lambda: ("", "", None, [], [], "", 0.0, ""),
                    inputs=None,
                    outputs=[
                        transcription_output,
                        response_output,
                        audio_output,
                        calendar_output,
                        notifications_output,
                        intent_output,
                        confidence_output,
                        error_output,
                    ],
                )

        gr.Markdown("---\n Hiya Hiya-Voice-Concierge")

    return demo


app = build_interface()


if __name__ == "__main__":
    app.launch(share=False, server_port=int(os.getenv("PORT", "7860")))
