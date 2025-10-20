import asyncio
from unittest.mock import AsyncMock

import pytest

import voice_personal_assistant
from voice_personal_assistant import VoiceInteractionResult, VoicePersonalAssistant


@pytest.mark.asyncio
async def test_handle_audio_transcription_failure(monkeypatch):
    assistant = VoicePersonalAssistant(user_id=1)

    monkeypatch.setattr(assistant.speech, "transcribe", AsyncMock(side_effect=RuntimeError("failure")))
    monkeypatch.setattr(
        voice_personal_assistant,
        "run_voice_agent",
        AsyncMock(return_value={"intent": "smalltalk", "confidence": 1.0, "parameters": {}, "summary": "hello"}),
    )
    monkeypatch.setattr(
        assistant,
        "_execute_intent",
        AsyncMock(return_value={"response_text": "fallback", "calendar_events": [], "notifications": [], "errors": []}),
    )
    monkeypatch.setattr(assistant.speech, "synthesize", AsyncMock(return_value=None))

    result = await assistant.handle_audio("does_not_exist.wav")
    assert isinstance(result, voice_personal_assistant.VoiceInteractionResult)
    assert "Transcription failed" in result.errors[0]
    assert result.response_text == "fallback"


@pytest.mark.asyncio
async def test_handle_audio_success_flow(monkeypatch, tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake-audio")

    assistant = VoicePersonalAssistant(user_id=7)

    monkeypatch.setattr(assistant.speech, "transcribe", AsyncMock(return_value="Check my flights next week"))
    monkeypatch.setattr(
        voice_personal_assistant,
        "run_voice_agent",
        AsyncMock(
            return_value={
                "intent": "calendar_lookup",
                "confidence": 0.8,
                "parameters": {"keyword": "flight", "within_days": 7},
                "summary": "Checking your flights.",
            }
        ),
    )
    monkeypatch.setattr(
        assistant,
        "_execute_intent",
        AsyncMock(
            return_value={
                "response_text": "Here are your next flights.",
                "calendar_events": [{"summary": "Flight to SFO"}],
                "notifications": [],
                "errors": [],
            }
        ),
    )
    monkeypatch.setattr(assistant.speech, "synthesize", AsyncMock(return_value=str(audio_path)))

    result = await assistant.handle_audio(str(audio_path))

    assert result.intent == "calendar_lookup"
    assert result.transcription == "Check my flights next week"
    assert result.calendar_events == [{"summary": "Flight to SFO"}]
    assert result.audio_path == str(audio_path)


def test_format_datetime():
    assistant = VoicePersonalAssistant(user_id=1)
    formatted = assistant._format_datetime("2024-10-19T18:00:00Z")
    assert "Oct" in formatted
