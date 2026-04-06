---
name: meeting
description: Facilitate a structured meeting between the user and all orchestra agents — agenda, discussion, notes, action items written to department briefing files. Run this when the task queue is empty to keep the system autonomous.
argument-hint: "[topic] OR 'close' to end the current meeting"
---

# Meeting Skill

Orchestrate a structured meeting between the user and the OATS orchestra via claude-peers. Produces persistent meeting notes and writes action items directly to department briefing files. This is the core mechanism for autonomous operation — when there is no work to do, call a meeting instead of stopping.

## Detecting Intent

- `$ARGUMENTS` is `close` → run **Close Meeting**
- `$ARGUMENTS` is empty → ask the user for the topic
- Otherwise → run **Start Meeting**

---

## Start Meeting

### Step 1 — Create the Notes File

Pick a filename from the topic: lowercase, hyphens, max 4 words.
Create `.orchestra/meetings/YYYY-MM-DD-[slug].md`:

```markdown
# Meeting: [Topic]
**Date:** YYYY-MM-DD HH:MM
**Status:** In Progress
**Attendees:** User (chair), [list online agents from list_peers]

---

## Agenda
[Topic description from $ARGUMENTS]

---

## Discussion

### [Agent 1]
_Awaiting response_

### [Agent 2]
_Awaiting response_

### [Agent N]
_Awaiting response_

---

## User Notes
_(add observations, decisions, follow-up questions here)_

---

## Action Items
_(populated at close)_
```

### Step 2 — Send Invites via claude-peers

First call `list_peers` to see who is online. Only invite agents that are online.

**To the CEO / lead agent** (strategic framing, not tasks):
```
[MEETING] Topic: [topic] | Agenda: [description] | As CEO, please share: strategic priority of this, risks, what success looks like, and your verdict (pursue/challenge/pass). Reply with [MEETING RESPONSE] when ready.
```

**To each department agent:**
```
[MEETING] Topic: [topic] | Agenda: [description] | Please share: (1) your department's perspective and concerns, (2) opportunities you see in your area, (3) specific tasks you're willing to own. Reply with [MEETING RESPONSE] when ready.
```

Tell the user: "Meeting invites sent. Agents are thinking — check back in a few minutes or watch your agent windows directly. Use `/meeting close` when responses are in."

### Step 3 — Collect Responses

When the user says responses are in (or after a reasonable wait), call `check_messages` to pull replies.

For each `[MEETING RESPONSE]` reply received:
- Paste it into the notes file under the correct agent heading
- Replace `_Awaiting response_` with their actual response
- Note any conflicts or gaps

If an agent is offline, leave `_Unavailable this session_` under their heading.

### Step 4 — Facilitate

Once initial responses are in, read for:
- **Conflicts** — agents disagreeing → flag under User Notes, ask follow-up
- **Gaps** — nobody addressed something important → prompt a specific agent
- **Decisions needed** — user needs to make a call → surface it clearly

Send follow-ups to specific agents:
```
[MEETING FOLLOW-UP] Question: [question]
```

---

## Close Meeting

### Step 1 — Extract Action Items

Read all responses. Extract concrete tasks. Format each as:
```
- [ ] [Task description] | Owner: [agent/dept] | Priority: [high/med/low] | By: [next session / YYYY-MM-DD]
```

Group by owner. Keep unowned items as "User to decide."

### Step 2 — Write to Briefing Files

For each agent/department that has tasks, append to `.orchestra/departments/[dept]/briefing.md`:
```markdown
## Meeting: [topic] — [date]
[tasks for this dept]
```

Do not overwrite existing tasks. Append only.

### Step 3 — Update Notes File

- Change `**Status:** In Progress` → `**Status:** Complete`
- Fill in the `## Action Items` section with the final grouped list

### Step 4 — Send Close Summary via claude-peers

```
[MEETING CLOSE] Topic: [topic] | Summary: [2-3 sentences] | Your tasks have been written to your briefing.md — check and acknowledge. Full notes: .orchestra/meetings/[filename]
```

### Step 5 — Report to User

```
Meeting closed. Notes: .orchestra/meetings/[filename]

Action items assigned:
  [Agent 1] : [n tasks]
  [Agent 2] : [n tasks]
  ...

Written to each department's briefing.md.
```

---

## When to Call a Meeting

The meeting system is what makes OATS truly autonomous. Agents should call a meeting when:

- The task queue is empty and there is no obvious next action
- A decision is needed that requires input from multiple departments
- Something broke and a post-mortem is needed
- A new feature or direction needs to be designed before building

Do not stop and wait. Call a meeting instead.

---

## Meeting Types

| Type | Good for |
|------|----------|
| **Sprint planning** | Start of a work session — "What should we build next?" |
| **Feature design** | Before building something new — "Design: [feature]" |
| **Strategy** | Big picture direction — "Strategy: [area] — where should we focus?" |
| **Post-mortem** | After something broke — "Post-mortem: [incident] — cause + prevention" |
| **Bug triage** | Multiple issues to prioritize — "Triage: [list] — what to fix first?" |
| **Brainstorm** | Open-ended ideas — "Ideas for [area]: what could we do?" |
| **Idle** | No work in queue — "What should we improve autonomously?" |

---

## Tips

- **Not all agents may be online** — proceed without offline agents.
- **CEO is strategic gate** — always get CEO input before closing strategy meetings.
- **Meeting files are permanent** — stored in `.orchestra/meetings/` as a searchable record.
- **Keep it focused** — if a new topic comes up, note it and schedule separately.
- **The idle meeting is the most important** — it's what prevents the system from stalling.
