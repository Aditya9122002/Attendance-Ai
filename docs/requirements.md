## Requirements

** Functional ** 

Teacher marks a student absent (dashboard/API), which emits an event.
The system calls the parent, runs a natural conversation, and handles no-answer, busy, wrong number, and callbacks.
An LLM extracts structured data (reason, expected return date, priority) and the database is updated.
Emergency detection, then escalation to the teacher, principal, or both.
Multilingual: English, Hindi, Marathi, Tamil, Gujarati.
Parent Q&A: homework and pending items (tool calling against the DB), then school policies, holidays, PTM, and circulars (RAG).
WhatsApp and email channels.
Analytics dashboard, plus multiple agents (Attendance, Homework, Fee, Transport, Admin).

Non-functional

Latency: the pause between the parent finishing speaking and the AI starting to reply should feel natural, roughly under 1-1.5 s. We'll set a formal budget in latency-budget.md.
Reliability: retries, idempotent calls (never double-call a parent), and graceful fallback if STT/LLM/TTS fails.
Observability: structured logs, per-call traces, and metrics for latency, cost per call, and extraction accuracy.
Evaluation: a labeled test set per language, with measured extraction accuracy, WER for STT, and escalation recall.
Privacy and compliance: you're handling children's data and call recordings. Check India's DPDP Act, telecom rules for automated outbound calls (registration and DLT requirements), and consent/recording disclosure. I'd verify these with current sources before Stage 6.
Cost control: per-call cost tracking, since telephony, STT, LLM, and TTS all bill per minute or token.

Tech stack and accounts

Core: Python 3.12+, uv, FastAPI, Pydantic, Ruff, Pytest, asyncio.
Data: Postgres and Alembic migrations (Redis later for call state and queues).
Voice: a telephony provider with India support (options: Exotel, Plivo, Twilio, Knowlarity), a streaming STT that handles Indian languages, a TTS with Indian voices, and an LLM with structured output and tool calling. I'd compare these hands-on in their stages rather than pick now.
Later: a vector DB (pgvector is a good fit since we already run Postgres), a WhatsApp Business API provider, and an email service.
Ops: Docker, GitHub Actions CI, and a metrics/tracing stack.

Knowledge you'll build: async Python, audio basics (PCM, sample rate, codecs), WebSockets, state machines, prompt and schema design, evaluation methods, and basic distributed-systems concepts.