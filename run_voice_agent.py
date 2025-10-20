import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None

load_dotenv()

logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("VOICE_AGENT_MODEL", "gpt-4o-mini")


def _build_openai_client() -> Optional["OpenAI"]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None
    return OpenAI(api_key=api_key)


CLIENT = _build_openai_client()


async def run_voice_agent(user_message: str, user_id: str = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Call the configured LLM to classify the user's request.

    Returns a JSON structure with the predicted intent and parameters.
    """
    if CLIENT is None:
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "parameters": {},
            "explanation": "OpenAI client is not configured. Provide OPENAI_API_KEY.",
        }

    system_prompt = (
        "You assist a voice-enabled concierge named Hiya Flyer Companion. "
        "Classify the user's utterance into an actionable intent. "
        "Supported intents: 'calendar_lookup', 'send_email', 'push_notification', "
        "'smalltalk', 'clarification', 'unknown'. "
        "When relevant, extract structured parameters such as temporal windows, keywords, "
        "recipient information, channels (email, push), and any follow up question necessary "
        "to fulfill the task. "
        "Always respond with JSON that adheres to the provided schema."
    )

    schema = {
        "name": "intent_schema",
        "schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "confidence": {"type": "number"},
                "parameters": {"type": "object"},
                "follow_up": {
                    "type": ["string", "null"],
                    "description": "Clarifying question if additional information is required.",
                },
                "summary": {"type": "string"},
            },
            "required": ["intent", "confidence", "parameters"],
            "additionalProperties": False,
        },
    }

    def _call_openai() -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "model": MODEL_NAME,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

        # Some OpenAI client versions do not yet support response_format; retry without it if needed.
        use_response_format = True
        params["response_format"] = {"type": "json_schema", "json_schema": schema}

        try:
            response = CLIENT.responses.create(**params)
        except TypeError as exc:
            if "unexpected keyword argument 'response_format'" not in str(exc):
                raise
            params.pop("response_format", None)
            use_response_format = False
            response = CLIENT.responses.create(**params)

        payload = response.output_text

        if not use_response_format:
            logger.warning("Voice agent falling back without response_format. Raw output: %s", payload)

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {
                "intent": "unknown",
                "confidence": 0.0,
                "parameters": {},
                "follow_up": "I could not parse the model response. Could you rephrase?",
                "summary": payload,
            }
        else:
            # Normalize missing fields so downstream logic doesn't crash when schema isn't enforced.
            if not isinstance(data, dict):
                return {
                    "intent": "unknown",
                    "confidence": 0.0,
                    "parameters": {},
                    "follow_up": "I received an unexpected reply. Please try again.",
                    "summary": payload,
                }
            data.setdefault("parameters", {})
            data.setdefault("confidence", 0.0)
            data.setdefault("summary", payload)
            return data

    return await asyncio.to_thread(_call_openai)
