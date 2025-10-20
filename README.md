# Hiya Voice Concierge

In today’s fast-paced world, people often struggle to manage their schedules, meetings, and travel plans while juggling work and personal life. Most voice assistants only provide surface-level help, they can answer questions but rarely take meaningful action.

**Hiya Voice Concierge** was designed to change that.

It is a **secure, intelligent, voice-first assistant** built entirely in Python. It listens, understands, and performs actions like checking your calendar, sending email reminders, or triggering push notifications, all through a single voice command.

The goal of this project is to demonstrate how a **fully functional AI concierge** can be implemented end-to-end with modern APIs, agentic reasoning, and seamless voice integration

---

## Job to Be Done

Modern professionals and travelers often juggle multiple responsibilities from business meetings and family events to travel logistics and health appointments. Managing all these tasks across different apps can be time-consuming and distracting.

**Hiya Voice Concierge** solves this by enabling true multitasking through voice.

With a single voice command, users can:
- Check flight schedules and upcoming calendar events.
- Send quick email or push notifications for follow-ups.
- Get reminders about work or personal tasks.
- Continue working hands-free while the assistant manages background actions.

**Goal:**  
Empower users to manage their day-to-day life, meetings, travel, and communication — through one intelligent, voice-controlled assistant that handles everything seamlessly.

---

## Key Features

- **Voice Interaction** — Converts speech to text using `whisper-1`, then responds using `gpt-4o-mini-tts` for natural voice output.  
- **Intent Understanding** — Uses `gpt-4o-mini` to classify user intent and extract structured parameters for tool execution.  
- **Calendar Integration** — Connects to Google Calendar (via service account or OAuth) to fetch flight, meeting, or appointment details.  
- **Notifications** — Sends reminders via Pushover and emails through SendGrid.  
- **Secure Multi-User Support** — Includes JWT authentication and SQLite persistence for each user’s data and history.  
- **Error Resilience** — Provides detailed error feedback and stores all audio logs for traceability.  
- **End-to-End Orchestration** — Built entirely in Python, with modular components for easy debugging and extension.

---

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

    # Google Calendar 
   GOOGLE_CALENDAR_CLIENT_ID= PUT_YOUR_ID_HERE
   GOOGLE_CALENDAR_CLIENT_SECRET= ENTER_YOUR_SECRET_KEY
   
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


## Next Steps

- **Expand Intent Coverage**  
  Add new intent categories such as travel bookings, weather updates, and health reminders to improve real-world usability.

- **Introduce Automated Evaluation and RAG**  
  Implement automated replay tests and Retrieval-Augmented Generation (RAG) for deeper contextual understanding and memory.

- **Deployment Enhancements**  
  Deploy the system to Hugging Face Spaces or Render with persistent database storage and OAuth-based user login.

---

## CrewAI Development Workflow

This project was developed using a **CrewAI agentic workflow**, where each AI agent represented a specific engineering role within the development process:

- **Engineering Lead** — Designed the backend architecture, defined class structure, and prepared the system design.  
- **Backend Engineer** — Implemented the backend logic and integrations according to the design.  
- **Frontend Engineer** — Built the Gradio-based user interface for end-to-end testing and demonstration.  
- **Test Engineer** — Developed automated unit tests to validate backend functions and ensure reliability.

This **modular, multi-agent development approach** ensured consistent quality, reduced human bottlenecks, and demonstrated the effectiveness of coordinated AI-driven engineering collaboration.

