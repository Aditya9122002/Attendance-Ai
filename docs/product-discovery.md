# Product Discovery: Requirements Gathering

> Purpose: turn our assumptions into facts by talking to real schools **before** we over-build.
> Two or three short conversations with a school will change the roadmap more than a week of coding.

## 1. Our current assumptions (to validate)

| # | Assumption | How we will check | Status |
|---|---|---|---|
| A1 | Schools spend real staff time phoning parents about absences | Ask how many calls, how long, who does it | Untested |
| A2 | Parents will answer and talk to an automated caller | Pilot pickup rate | Untested |
| A3 | Most parents can be reached on one registered number | Ask about data quality | Untested |
| A4 | A school will pay for this | Ask about budget and pricing | Untested |
| A5 | Teachers can mark absence digitally, or will | Ask how attendance is taken today | Untested |
| A6 | Hindi and Marathi phone-call accuracy is good enough | Measure on recorded test audio | Untested |
| A7 | Schools want to keep their existing system | Ask what software they use | Untested |

## 2. Who to talk to

- Principal or owner (decision maker, budget, risk)
- Vice-principal or administrator (daily operations)
- Two or three class teachers (attendance workflow)
- Office or front-desk staff (who actually makes the calls)
- Two or three parents (would they accept this call?)
- The person who manages IT or the school software, if one exists

## 3. Questions for the principal or administrator

**Current process**
1. How is student attendance taken today (paper, app, ERP)?
2. When a student is absent, what happens next? Who calls, and when?
3. Roughly how many absences per day? How many calls does that lead to?
4. How much staff time does this take daily?
5. What happens when nobody reaches the parent?
6. Have you had a case where an absence turned out to be serious?

**Pain and value**
7. What is the most annoying part of this today?
8. If this worked perfectly, what would change for you?
9. What would make you not trust it?

**Buying**
10. Who decides on new tools, and what is the process?
11. What do you pay for similar tools (attendance apps, SMS, ERP)?
12. Would you prefer monthly per-student pricing, per-call pricing, or a fixed fee?
13. Would you run a free pilot for a few weeks? What would success look like?

**Safety and trust**
14. Are you comfortable with an AI calling parents? Under what conditions?
15. Who should be alerted for an emergency, and how quickly?
16. Are there parent groups who must not be called (custody issues, language needs, etc.)?

## 4. Questions for teachers and office staff

1. Walk me through what you do from marking attendance to speaking to a parent.
2. What do parents usually say? What are the common reasons?
3. What information do you actually want recorded?
4. What time of day are calls made, and what time is too late?
5. How do you handle parents who do not answer?
6. Would you check a dashboard? On phone or computer?
7. What would you never want an automated system to say?

## 5. Questions for parents

1. Do you usually answer calls from the school? Which times work best?
2. Which language do you prefer for a call?
3. How would you feel about an automated call that speaks your language?
4. What would make you hang up or feel annoyed?
5. What should the call absolutely not do?

## 6. Data we need from a school

| Data | Notes |
|---|---|
| Student list: name, class, section, roll number | Fake data for all development |
| Parent or guardian name, phone, preferred language | Number quality matters a lot |
| Backup contact | For emergencies |
| Attendance source | Where absences will come from |
| Calling window | For example, 9 AM to 6 PM on school days |
| Holiday calendar | Avoid calls on holidays |
| School name as parents know it | Used in the greeting |

## 7. Compliance and legal checklist (verify with current sources)

We are handling children's data and making automated calls. Before any real school pilot,
verify each item against **current** rules, and consider a short review by a lawyer:

- [ ] India's Digital Personal Data Protection Act: consent, children's data rules, retention, deletion
- [ ] Telecom rules for automated or promotional versus service calls, and any registration required
- [ ] Twilio's current requirements for calling Indian numbers (caller ID, restrictions, cost)
- [ ] Call recording disclosure and consent
- [ ] Where data is stored and processed, and what the AI providers do with it
- [ ] Paid API tiers with proper data terms instead of free tiers
- [ ] Parent opt-out mechanism
- [ ] School agreement covering who owns the data and who is responsible

## 8. Pilot plan (proposal)

1. **Demo first.** Show a recorded or live demo using fake data and your own phone.
2. **Shadow mode.** For one to two weeks, the system runs alongside the school's normal process.
   Compare its extracted reasons against what staff learn.
3. **Limited live pilot.** One class or grade, a few weeks, staff review every result.
4. **Measure.** Pickup rate, extraction accuracy, emergency recall, staff time saved, parent feedback.
5. **Decide.** Expand, adjust, or stop.

## 9. Decisions still open

| Question | Needed by |
|---|---|
| Which language ships first (Hindi, Marathi, or English)? | Stage 6 |
| Single school or multi-school from day one? (We chose `school_id` on every table.) | Stage 1 |
| How do absences arrive: manual entry, CSV upload, or integration with a school system? | Stage 1 |
| Retention period for recordings and transcripts | Before pilot |
| Pricing model | After first school conversations |
| Who receives emergency alerts, and by what channel (call, SMS, WhatsApp)? | Version 2 |

## 10. How to record what you learn

After each conversation, add a short note here:

```
### YYYY-MM-DD, School name (or "anonymous"), role of person
- What they do today:
- Biggest pain:
- What excited them:
- What worried them:
- Assumptions this confirmed or broke:
- Follow-ups:
```

Update the assumptions table in section 1 whenever a conversation confirms or breaks one.

## 11. Discovery log

_(add entries here)_