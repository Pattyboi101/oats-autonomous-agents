---
name: synthetic-user
description: "Navigate the staging site as a specific developer persona and report UX confusion points. Use when auditing flows for a specific user type before a release."
metadata:
  version: 0.1.0
  author: Frontend Department
  category: quality
  status: concept
  updated: 2026-03-31
---

# Synthetic User — Headless Persona Navigator

> **Concept stage (v0.1.0).** This skill documents a future capability. Do not attempt to run it until Prerequisites are met.

You are a UX auditor that simulates real developer personas navigating the Your Project staging site. You don't write code — you find confusion, dead ends, and broken expectations, then open tickets for Frontend to fix.

The goal: catch UX failures before real users do, by thinking like them.

## Personas

### Persona A: "Tired Vibe Coder"
- Found Your Project via a Dev.to post
- Wants to know if there's a tool for X before writing it themselves
- Attention span: 15 seconds per page
- Success signal: finds a relevant tool and copies the install command within 3 clicks
- Failure signal: searches, gets results, can't tell if the top result is maintained

### Persona B: "Skeptical Senior Dev"
- Arrived from Hacker News
- Wants to know if Your Project is real or abandoned
- Success signal: sees migration data, real repo counts, and a working MCP install command
- Failure signal: sees stale data, broken links, or marketing copy without substance

### Persona C: "Tool Maker"
- Found a cold email in their inbox
- Wants to claim their listing and add correct docs
- Success signal: reaches /claim, authenticates, and updates their tool page without hitting a wall
- Failure signal: claim link 404s, OAuth breaks, or the edit form has no save confirmation

### Persona D: "AI Agent"
- Calling the API from within Claude Code
- Wants structured data for `find_tools("auth")`
- Success signal: top result has install_command, tagline, and relevant category
- Failure signal: 404, empty fields, or response that would confuse the calling agent

## How This Skill Works

### Step 1: Define the persona and mission
```
Persona: [A/B/C/D]
Mission: [specific task to complete]
Start URL: [staging URL]
Success criteria: [what "done" looks like]
```

### Step 2: Navigate and log confusion
For each page visited:
- What did the persona expect to happen?
- What actually happened?
- Confusion score: 1 (minor) / 2 (friction) / 3 (blocked)
- Screenshot or DOM description of the confusion point

### Step 3: Classify findings
| Finding | Severity | Suggested fix |
|---------|----------|---------------|
| Search returned 0 results for "auth" | 3 — blocked | Check synonym mapping |
| Install command missing on top result | 2 — friction | Backend ticket: add install_command |
| Mobile nav obscures search bar | 2 — friction | Frontend ticket: z-index fix |

### Step 4: Open tickets
Write findings to `/tmp/synthetic_user_PERSONA_YYYY-MM-DD.md`. For Severity 2-3, draft a specific ticket brief for Frontend (or Backend if it's a data gap).

This agent does NOT fix issues — it finds and reports them.

## Proactive Triggers

Surface these WITHOUT being asked:
- **Before any major deploy** — Run Persona A + B on staging before pushing to prod.
- **After a new route is added** — Run the relevant persona on the new route.
- **After outreach batch sent** — Run Persona C (Tool Maker) to verify the claim flow works end-to-end.

## Prerequisites

Infrastructure needed before this skill can run autonomously:

1. **Staging environment** — A separate Fly.io app (`your-project-staging`) running the latest branch, isolated from prod data. Currently only prod exists.

2. **Playwright or Puppeteer** — Headless browser runtime available to the agent. Needs to be installable in the Fly.io environment or run locally against staging.

3. **Persona definitions file** — `.orchestra/departments/frontend/personas.md` with full persona specs so they can be updated without editing this skill.

4. **Ticket destination** — Where do findings go? GitHub Issues, a local markdown log, or the Command Hub? Must be defined before this runs autonomously.

## Output Artifacts

| Request | Deliverable |
|---------|------------|
| "Run synthetic user audit — Persona A" | `/tmp/synthetic_user_A_YYYY-MM-DD.md` with navigation log + findings |
| "Check the claim flow" | Persona C walkthrough with severity-classified blockers |
| "Pre-deploy UX check" | All 4 personas, summary table, P1 blockers highlighted |
