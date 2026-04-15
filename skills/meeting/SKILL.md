---
name: meeting
description: "Facilitate a structured CONVERSATIONAL meeting between department agents via claude-peers — named phases (Diverge, Clarify, Challenge, Build, Stress Test, Converge, Decide) with state machine navigation. Agents push back on each other and build on each other's ideas. Minimum path: Diverge → Challenge → Build → Stress Test. Early exit only after Stress Test. NOT for simple task dispatch (use orchestra-management). NOT for solo research (use rd-architect)."
metadata:
  version: 3.0.0
  author: Master Agent
  category: management
  updated: 2026-04-07
---

# Meeting — Phase-Based Agent Debate

You are the chair. Run a real meeting — a state machine, not a survey. Agents diverge ideas, challenge each other, build on what survives, and stress test before anything becomes an action. The chair navigates phases autonomously, can skip optional ones, repeat phases generating value, or loop back when a later phase reveals something that needs earlier work.

---

## Before Starting

- Are departments online? `list_peers` — need at least 3 for a useful meeting
- Is there an open meeting already? Check `meetings/` — don't duplicate
- What specific decision needs to be made? Clarify before creating the file

---

## How This Skill Works

- **Mode 1: Start Meeting** — topic provided → create file, run Diverge, facilitate through phases until satisfied or closed
- **Mode 2: Close Meeting** — user says "close" → extract actions, write briefings, broadcast summary
- **Mode 3: Mid-Meeting Injection** — user adds a point mid-discussion → route to relevant agents as targeted prompt without restarting the phase

---

## Phase System

| Phase | Purpose | Mandatory? |
|-------|---------|-----------|
| **Diverge** | All ideas on the table — no criticism yet | **Yes** |
| **Clarify** | Surface assumptions, define terms, resolve ambiguity | Optional |
| **Challenge** | Push back, expose tensions, stress-test assumptions | **Yes** |
| **Build** | Develop the strongest ideas that survived Challenge | **Yes** |
| **Stress Test** | Attack the emerging consensus — try to break it | **Yes** |
| **Converge** | Find genuine agreement, surface remaining gaps | Optional |
| **Decide** | Lead agent resolves anything still genuinely unresolved | Only if unresolved |

**Minimum required path:** Diverge → Challenge → Build → Stress Test

**`[SATISFIED]` and `[CLOSE MEETING]` flags are ignored until Stress Test completes.** Collect them, note them, do not act on them.

---

## Agent Flags

Agents write these in their responses to signal navigation needs:

| Flag | Meaning | Chair Action |
|------|---------|-------------|
| `[NEEDS CLARIFY: X]` | X needs defining before I can contribute fully | Insert Clarify phase |
| `[BACK TO CHALLENGE: reason]` | Build surfaced a new tension that needs challenging | Loop to Challenge |
| `[BACK TO BUILD: reason]` | Stress Test revealed a better approach worth developing | Loop to Build |
| `[NEEDS RESEARCH: X]` | I need current data on X before proceeding | Chair searches, prepends findings to next phase |
| `[SATISFIED]` | Nothing more to add — happy with direction | Count; close if all satisfied (after Stress Test) |
| `[CLOSE MEETING: reason]` | Lead/CEO: meeting has run its course | Close immediately (only after Stress Test) |

---

## State Machine

```
Diverge (mandatory)
  → [Clarify]? — insert if [NEEDS CLARIFY] flags or agents talking past each other
  → Challenge (mandatory)
       ↑ ← loop back if Build surfaces [BACK TO CHALLENGE]
  → Build (mandatory)
       ↑ ← loop back if Stress Test surfaces [BACK TO BUILD]
  → Stress Test (mandatory)
  → [Converge]? — insert if unresolved disagreements remain
  → [Decide]? — insert if Converge still has unresolved conflict
  → Close
```

**Only surface to the user when the meeting closes.**

---

## Research Integration

| When | What | How |
|------|------|-----|
| **R0 — Pre-meeting** | Chair researches before Diverge; findings go in every agent's prompt | WebSearch/WebFetch, 3-5 bullets |
| **In-phase** | Agents search before writing their position | Tell agents: "Search before writing if you need current data" |
| **Between-phase sprint** | Chair runs searches from `[NEEDS RESEARCH: X]` flags | Prepend findings to next phase prompt |

---

## Step 1 — Create Meeting File

Path: `meetings/YYYY-MM-DD-[topic-slug].md`

```markdown
# Meeting: [Topic]
**Date:** YYYY-MM-DD HH:MM
**Status:** Diverge
**Phases run:** []
**Attendees:** [Chair], [Departments online]

---

## Agenda
[Topic + the specific decision or question to resolve]

---

## Phase: Diverge

### [Dept 1]
_Awaiting response_

### [Dept 2]
_Awaiting response_

[one section per department]

---

## [Further phases added dynamically]

---

## Chair Notes
_Navigation decisions, tensions, calls the user needs to make_

---

## Action Items
_Populated at close_
```

---

## Step 1b — R0: Pre-Meeting Research (optional, recommended for external topics)

Before sending Diverge, do 3-5 searches. Prepend a brief to every Diverge message:

```
**Research brief:**
- [Finding 1]
- [Finding 2]
- [Finding 3]
Shared context — you may also search before writing.
```

---

## Step 2 — Phase: Diverge (mandatory)

Send to all agents simultaneously:

**To strategic/lead agent:**
```
[MEETING — DIVERGE] Topic: [topic]

Generate ideas — no criticism yet. Answer:
1. Strategic read: what's the real opportunity or problem?
2. Two or three concrete moves we could make
3. The thing nobody's said yet that we should be considering
4. One assumption you want to challenge in the next phase

Write under "### [your dept]" in meetings/[file]. Stake a real position.
After writing, check_messages immediately.

Write [NEEDS CLARIFY: X] if something needs defining. Write [SATISFIED] at any point if happy (noted, not acted on until after Stress Test).
```

**To department agents:**
```
[MEETING — DIVERGE] Topic: [topic]

Generate ideas — no criticism yet. Answer:
1. Your honest take — what's the real problem or opportunity from your angle?
2. What you'd build, propose, or change
3. What another department is probably going to miss
4. One assumption you want to challenge later

Write under "### [your dept]" in meetings/[file]. Stake real positions — others respond in Challenge.
After writing, check_messages immediately.

Write [NEEDS CLARIFY: X] if something needs defining. Write [SATISFIED] at any point if happy (noted, not acted on until after Stress Test).
```

---

## Step 3 — Phase: Clarify (optional)

**Run if:** Diverge produced `[NEEDS CLARIFY]` flags or agents are talking past each other.
**Skip if:** Diverge responses were clear.

Add section:
```markdown
## Phase: Clarify

**Clarifications needed:**
- [X from Dept A]

### Chair clarifications
[Definitions or decisions on contested terms]
```

Send to agents who need clarification:
```
[MEETING — CLARIFY] Topic: [topic]

Before Challenge, clarifying:
- [X]: [definition / decision]

Does this change your Diverge position? Update if needed. After writing, check_messages immediately.
```

---

## Step 4 — Phase: Challenge (mandatory)

Read all Diverge responses. Find 3-5 **genuine tensions** — direct contradictions, incompatible assumptions, things one agent flagged as critical that others ignored.

Add section:
```markdown
## Phase: Challenge

**Tensions identified:**

**T1: [Label]** — [Dept A] says [X], [Dept B] says [Y]. Incompatible.
**T2: [Label]** — Lead assumes [A] but [Dept C] read is [B].

### [Dept A] + [Dept B] respond to T1
_Awaiting response_
```

Send **targeted** messages — only agents in genuine conflict:
```
[MEETING — CHALLENGE] Topic: [topic]

Respond to these tensions directly:

**T1: [Label]**
[Dept B] said: "[exact quote]"
Your position was: "[exact quote]"
Who's right and why? Be direct — "X is wrong because Y."

Write under "### [your dept] responds to T1". After writing, check_messages immediately.
Write [BACK TO CHALLENGE: reason] in a later phase if you hit a new tension.
Write [SATISFIED] if happy (noted, not acted on until after Stress Test).
```

Report tensions to user before sending.

**Loop back:** If Build responses contain `[BACK TO CHALLENGE: reason]`, add a new Challenge section, route only affected agents, resolve, then continue to Build.

---

## Step 5 — Phase: Build (mandatory)

Take the strongest surviving ideas and develop them into concrete proposals.

Add section:
```markdown
## Phase: Build

**Surviving ideas to develop:**
- [Idea A from Dept X — survived T1 challenge]
- [Idea B from lead — unchallenged, needs development]
```

Send to all (or targeted):
```
[MEETING — BUILD] Topic: [topic]

Challenge is done. Strongest surviving ideas:
- [Idea A]
- [Idea B]

Your job: develop one further, or propose how to combine them. Don't critique — build.
Be concrete: what does this look like in practice? What's the first step?

Write under "## Phase: Build / ### [your dept]". After writing, check_messages immediately.
Write [BACK TO CHALLENGE: reason] if you hit a new tension.
Write [SATISFIED] if happy (noted, not acted on until after Stress Test).
```

**Loop back:** If Build responses contain `[BACK TO CHALLENGE: reason]`, run targeted Challenge, then return to Build.

---

## Step 6 — Phase: Stress Test (mandatory)

When Build has produced a concrete direction, attack it before committing.

Add section:
```markdown
## Phase: Stress Test

**Direction under attack:** [specific description]
```

Send to all:
```
[MEETING — STRESS TEST] Topic: [topic]

A direction is forming: [description]

Your job: attack it. Find holes, bad assumptions, things that will go wrong in practice. Don't defend it — break it.
If you've tried and it held up, say why and flag [SATISFIED].

Write under "## Phase: Stress Test / ### [your dept]". After writing, check_messages immediately.

Write [BACK TO BUILD: reason] if Stress Test reveals a genuinely better approach worth developing.
Write [CLOSE MEETING: reason] (lead/strategic agent only) if the meeting has run its course.
Write [SATISFIED] if the direction survived your scrutiny.
```

**Loop back:** If `[BACK TO BUILD: reason]` is flagged, add new Build section, develop, run Stress Test again.

**Close triggers now active:**
- Lead/CEO writes `[CLOSE MEETING: reason]` → close immediately
- All agents write `[SATISFIED]` → close immediately
- User says "close" → close immediately
- Otherwise → Converge if unresolved, close if clear consensus

---

## Step 7 — Phase: Converge (optional)

**Run if:** Stress Test ended with remaining genuine disagreements.
**Skip if:** Clear consensus and most agents satisfied.

```
[MEETING — CONVERGE] Topic: [topic]

Here's where we are after Stress Test: [summary]

What do you actually agree on? What's still genuinely unresolved — be specific.

Write under "## Phase: Converge / ### [your dept]". After writing, check_messages immediately.
Flag [SATISFIED] when done. Lead agent: flag [CLOSE MEETING: reason] to close now.
```

---

## Step 8 — Phase: Decide (only if unresolved)

Only if genuine unresolved conflict remains. Send to lead/strategic agent only:

```
[MEETING — DECIDE] Topic: [topic]

Still genuinely unresolved:
- [Item 1: what's the disagreement]
- [Item 2: what's the disagreement]

Read the full meeting file. Give a verdict:
1. On [Item 1]: the right call is [X] because [Y]
2. On [Item 2]: the right call is [X] because [Y]
3. What [user] needs to decide (if anything you can't call)

Write under "## Phase: Decide". Verdict, not summary. After writing, check_messages immediately.
```

---

## Close Meeting

**1. Extract actions** — concrete tasks only:
```
- [ ] [Task] | Owner: [Dept] | Priority: high/med/low | By: [date]
```

**2. Write to briefing files** — append per department:
```markdown
## Meeting: [topic] — [date]
- [ ] [task]
```

**3. Update meeting file:** Status → `Closed`, Phases run → fill list, fill Action Items.

**4. Broadcast:**
```
[MEETING CLOSE] [topic] | Decided: [2-3 sentences] | Tasks in briefing.md | Notes: meetings/[file]
```

**5. Report to user:**
```
Meeting closed. Phases: [Diverge → Challenge → Build → Stress Test → ...]

Decided: [key decisions]
Unresolved (your call): [anything left]

Actions: [Dept A] [n] | [Dept B] [n] | ...
```

---

## Proactive Triggers

- **Only 1 agent responded to Diverge** → flag before Challenge. Not enough for a real meeting.
- **All Diverge responses agree completely** → "Everyone agrees — skip to Build, or run Challenge to pressure-test the consensus?"
- **Lead agent hasn't responded** → don't close a strategy meeting without them.
- **`[SATISFIED]` from all agents** → close immediately (only after Stress Test).
- **Genuine tension in Challenge not routed** → catch it. Don't let real disagreements get buried.

---

## Meeting Type → Suggested Phase Path

| Type | Phase Path | Notes |
|------|-----------|-------|
| Sprint planning | Diverge → Challenge → Build → Stress Test | Full minimum path |
| Feature design | Diverge → Challenge → Build → Stress Test | Build designs it, Stress Test breaks it |
| Strategy / big bets | All phases | Converge + Decide critical for major calls |
| Post-mortem | Diverge → Challenge → Build → Stress Test | Build develops fixes, Stress Test attacks them |
| Partnership pitch | Diverge → Challenge → Build → Stress Test | Stress Test attacks the pitch before it goes out |
| Quick align | Diverge → Challenge | Only if topic is narrow and consensus forms fast |

---

## Related Skills

- **orchestra-management**: For task dispatch. NOT for debates or decisions.
- **rd-architect**: For deep research before a meeting — run this first if you need data.
- **deploy-safely**: If the meeting produces a deploy decision, run after.
- **review-checklist**: For reviewing work produced after meeting decisions.
