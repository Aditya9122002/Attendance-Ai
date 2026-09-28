Stage	Focus	Deliverable	Exit criteria
0. Foundations	uv, repo, Ruff, Pytest, FastAPI /health, config, logging	Running skeleton with CI	Tests and lint pass in CI
1. Domain and data	Postgres schema (students, parents, attendance, call attempts, conversations), async DB access, migrations, "mark absent" API, absent-event emission	Teacher API that emits events	Event fires exactly once per absence
2. LLM layer (text-only)	Prompting, structured output, function calling, guardrails, first eval set	Transcript in, validated JSON out, DB updated	Measured extraction accuracy on a test set
3. Conversation manager	State machine (greet, ask reason, confirm, close), retries, clarification	Text chat simulating the whole parent call	Handles vague, off-topic, and refusal replies
4. Audio fundamentals	PCM, sample rate, 8 kHz μ-law (telephony), VAD, WebSocket streaming	Local mic-to-speaker loop with VAD	You can explain every byte format
5. Speech	Streaming STT, turn detection/endpointing, TTS, barge-in (interruptions)	Voice conversation on your laptop	Latency measured per stage against the budget
6. Telephony, MVP complete	Outbound calls, media streams, no-answer/busy handling, call logging	Teacher marks absent, parent gets a real call, DB updates	V1 done end-to-end
7. Agent hardening (V2)	Retry policy, callbacks, memory, emergency detection, escalation, principal and teacher notifications	Reliable agent with an escalation path	Emergency recall measured on eval set
8. Multilingual (V3)	Language detection, per-language STT/TTS/prompts, code-switching (Hinglish)	Five languages working	Per-language eval scores
9. Data and knowledge (V4, V5)	Homework tools, then RAG over policies, calendar, PTM, circulars	Parent asks questions and gets grounded answers	Retrieval and answer-faithfulness eval
10. Channels (V6, V7)	WhatsApp and email behind a channel abstraction	Same agent logic across voice, WhatsApp, and email	New channel added without touching agent code
11. Analytics and production (V8)	Dashboard, Docker, Redis, Postgres tuning, monitoring, metrics, deployment guide	Deployed system with dashboards	Load test and failure drills pass
12. Multi-agent (V9)	Router/supervisor plus Homework, Fee, Transport, and Admin agents	Multiple agents sharing tools and memory	Routing accuracy eval