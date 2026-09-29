# Product Understanding: AttendanceAI

> Status: Draft v1. Everything marked **(hypothesis)** must be validated with real schools
> before we treat it as fact. See `product-discovery.md`.

## 1. The problem in one paragraph

When a student is absent, someone at the school has to find out why. Today that means a
teacher or office staff phoning parents one by one, or sending an SMS that most parents ignore.
It is slow, inconsistent, and rarely recorded in a structured way. Worse, the calls that matter
most (a child who is seriously ill, or a child who is missing without the parent knowing) are
buried in the same pile as routine absences.

## 2. What AttendanceAI is

An AI voice assistant that **automatically phones a parent when a student is marked absent**,
asks in the parent's own language why the child is absent, understands the answer, and writes
structured information back into the school's records. It escalates urgent cases to a human.

## 3. What AttendanceAI is NOT

- Not a general-purpose chatbot.
- Not a replacement for teachers or the school office. It removes routine phone work and
  surfaces the cases a human must handle.
- Not a full school ERP. It sits beside whatever the school already uses.
- Not a decision maker. It never approves leave, gives medical advice, or blames anyone.

## 4. Who uses it

| Person | What they want | What they do with the product |
|---|---|---|
| **Teacher** | Mark attendance quickly, stop chasing parents | Marks students absent, sees call results on a dashboard |
| **Parent** | A short, polite call in their language, no hassle | Answers the phone, says why the child is absent |
| **Principal / admin** | Visibility, safety, fewer complaints | Sees summaries, gets alerts for emergencies and patterns |
| **School IT / office** | Something safe and simple to run | Loads student and parent data, manages settings |

## 5. Value proposition (hypothesis)

- **For the school:** saves staff hours every day, gives a complete reason for every absence,
  and flags emergencies quickly.
- **For parents:** one clear call instead of repeated messages, in the language they speak.
- **For safety:** an absent child with no explanation gets noticed the same day.

## 6. MVP scope (what "done" means for the first sellable version)

**In scope**
1. Teacher marks a student absent.
2. System calls the parent's registered number.
3. AI introduces itself, confirms it is speaking to the right person, and asks the reason.
4. AI understands the reply and extracts: **reason, expected return date, priority**.
5. Attendance record is updated with the structured result.
6. Teacher sees call status, summary and transcript on a dashboard.
7. Handles no answer, busy, wrong person, refusal, and unclear answers gracefully.

**Out of scope for the MVP (but planned later)**
Emergency escalation flows, multiple languages beyond the first, parent Q&A, WhatsApp,
email, analytics, multiple agents. The full roadmap is in `development-roadmap.md`.

## 7. Success metrics (hypothesis, targets to be set with schools)

| Metric | Why it matters |
|---|---|
| % of absence calls that reach a parent | Basic reach |
| % of answered calls with a correctly extracted reason | Core accuracy |
| Emergency recall (real emergencies we correctly flagged) | Safety, the metric that matters most |
| Time from "marked absent" to "reason recorded" | The core promise |
| Cost per completed call | Decides whether the business works |
| Parent complaints or opt-outs | Trust |
| Staff minutes saved per day | What the school is paying for |

## 8. Business model hypotheses

Not decided. Options to test with schools:
- Per-student per month fee.
- Per-completed-call fee (usage based).
- One-time setup fee plus a monthly support fee.

Because the code is open source, revenue will most likely come from **hosting, setup,
support and integrations**, not from selling the code itself.

## 9. Alternatives the school already has

| Alternative | Weakness we exploit |
|---|---|
| Teacher or office staff phone parents | Slow, inconsistent, unrecorded |
| SMS or app notifications | Low response rate, one-way |
| WhatsApp messages | Parents may not reply, unstructured |
| School ERP apps | Usually notify, rarely converse |

Our edge is a **two-way conversation in the parent's language that ends in structured data**.

## 10. Key risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| Speech accuracy on Indian languages over phone audio | Wrong understanding means wrong records | Measure per language, escalate low-confidence cases to a human |
| Missing a real emergency | Highest-stakes failure | Conservative escalation, measure recall, human review |
| Privacy of children's data and call recordings | Legal and trust risk | Minimal data, consent, no real data in free-tier APIs, verify DPDP requirements |
| Telecom rules for automated calls in India | Could block calling entirely | Verify current rules before any real school pilot |
| Parents distrust automated calls | Low pickup | Clear school-branded introduction, short calls, option to speak to a human |
| Cost per call too high | Business fails | Track cost per call from day one |
| Wrong person answers | Privacy breach | Confirm identity before mentioning the child's details |

## 11. Principles we build by

1. **Human in the loop.** The AI handles routine cases and hands off the rest.
2. **Say less when unsure.** Never reveal a child's details until the caller is confirmed.
3. **Structured output, always.** Every call ends as validated data, not just a recording.
4. **Measure everything.** Accuracy, latency, cost, and emergency recall.
5. **Providers are replaceable.** Speech, LLM and telephony sit behind interfaces.

## 12. Glossary

- **STT**: speech-to-text. **TTS**: text-to-speech.
- **VAD**: voice activity detection, deciding when someone is speaking.
- **Barge-in**: the parent interrupting the AI while it is talking.
- **Turn detection / endpointing**: deciding the parent has finished their sentence.
- **Extraction**: turning free speech into structured fields.
- **Escalation**: handing a case to a human (teacher or principal).
- **DPDP**: India's Digital Personal Data Protection Act.