## Hiya Voice Concierge

**Job to be done:** As a frequent traveler juggling work and family commitments, I want to confirm what flights and appointments are coming up and trigger any follow-up tasks with a quick voice command, so that I can stay ahead of changes without opening multiple apps.

This proof-of-concept demonstrates a secure, voice-first concierge that triages a user's spoken requests, checks the calendar for travel or healthcare commitments, and pushes proactive follow-ups through Pushover and SendGrid. It is built to support the collaborative coding exercise by keeping all orchestration logic inside the repository—no no-code tools, and every integration is wired through Python.

### Key Capabilities
- **End-to-end voice loop** using OpenAI Whisper (`whisper-1`) for speech-to-text and `gpt-4o-mini-tts` for text-to-speech. If an API key is not provided the assistant gracefully degrades and surfaces actionable errors.
- **LLM orchestration** via `gpt-4o-mini` (configurable) to classify intents, extract structured parameters, and decide whether clarification is required before calling tools.
- **Calendar tool-calling** backed by Google Calendar (service-account or delegated OAuth) to answer “upcoming flights/doctor visits” style questions. Results are synchronised into the local database for auditability.
- **Notification fan-out** with first-class Pushover and SendGrid integrations so the assistant can nudge a traveler on mobile and send a follow-up email—credentials are loaded from environment variables.
- **Secure multi-user persistence** using SQLite by default (drop-in replacement via `DATABASE_URL`) plus JWT-based authentication so dashboards and conversation history are scoped to the viewer.
- **Conversation resilience** with contextual error messages, clarification prompts, and full logging to `output/audio/` for playback inside the Gradio UI.

### Repository Layout
```
app.py                     # Gradio UI + auth + voice tab orchestration
voice_personal_assistant.py# Core agent orchestrator and tool integrations
run_voice_agent.py         # LLM-powered intent parser (OpenAI Responses API)
calendar_service.py        # Google Calendar client
notification_services.py   # Pushover & SendGrid wrappers
database.py                # SQLAlchemy models and session manager
requirements.txt           # Python dependencies
README.md                  # This file
```

### Running the Demo
1. **Install dependencies**
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Configure environment** (create a `.env` file in the repo root):
   ```
   SECRET_KEY=super-secret-string
   OPENAI_API_KEY=sk-...
   VOICE_AGENT_MODEL=gpt-4o-mini

    # Google Calendar (choose one of the following approaches)
   GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service-account.json
   GOOGLE_CALENDAR_ID=primary
   GOOGLE_CALENDAR_DELEGATED_USER=your.email@domain.com
   # or embed the JSON:
   # GOOGLE_SERVICE_ACCOUNT_JSON={"type": "...", ...}

   # Notifications
   PUSHOVER_APP_TOKEN=...
   PUSHOVER_USER_KEY=...
   SENDGRID_API_KEY=...
   SENDGRID_SENDER=hiya-assistant@example.com

   # Optional overrides
   DATABASE_URL=sqlite:///voice_assistant.db
   ACCESS_TOKEN_EXPIRE_MINUTES=1440
   ```
3. **Launch Gradio**
   ```bash
   python app.py
   ```
4. Register a user, log in, and interact through the **Voice Assistant** tab. The UI shows:
   - Live transcription and natural language response
   - Audio playback of the assistant’s reply
   - A breakdown of calendar events, notifications, and any errors

### Technical Notes
- **Orchestration:** `VoicePersonalAssistant` coordinates the speech service, intent parser, and tool execution. Each intent handler returns both a human-readable response and machine-readable artefacts so downstream evaluation/analytics can plug in easily.
- **Error handling:** Every integration raises descriptive runtime errors captured in the UI. For example, missing Google credentials trigger a helpful banner instead of silent failure.
- **Evaluation hooks:** Conversation history, detected intents, and tool responses are stored in SQLite (`voice_assistant.db`). This enables offline scoring, success-rate tracking, and debugging during the live collaborative exercise.
- **Extensibility:** Add new tools by registering another handler inside `_execute_intent`. Because intent parsing already returns structured `parameters`, wiring additional APIs (e.g., rebooking workflows) is straightforward.


### Next Steps
1. Expand intent coverage (e.g., rebooking, loyalty point queries) with a tool registry.
2. Add automated evaluation scripts that replay recorded utterances against the assistant and verify downstream actions.
3. Layer in RAG over travel itineraries or email inboxes using vector search for richer memory.

