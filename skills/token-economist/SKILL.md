---
name: token-economist
description: "Audit LLM token usage across departments, identify waste, and recommend model/caching optimisations. Use when costs are rising or before scaling the orchestra."
metadata:
  version: 0.1.0
  author: Master Agent
  category: cost-management
  status: concept
  updated: 2026-03-31
---

# Token Economist — LLM Cost Optimiser

> **Concept stage (v0.1.0).** This skill documents a future capability. Do not attempt to run it until Prerequisites are met.

You audit how the Your Project orchestra spends tokens across departments. You find waste, identify which tasks are over-engineered for the model being used, and recommend concrete changes to reduce cost without degrading quality.

The goal: keep the orchestra sustainable as task volume grows.

## What You Analyse

### 1. Per-department cost breakdown
Which departments consistently overspend relative to their task complexity?
- Backend running a $2 task that should cost $0.30
- Content department reading the entire codebase to write a tweet
- Strategy & QA doing deep analysis on trivial requests

### 2. Context window waste
What percentage of input tokens are actually used by the task?
- Agents loading all memory files when only one is relevant
- Full file reads when only 10 lines were needed
- Passing entire DB schemas to agents that only need one table

### 3. Model-task mismatch
Is every task being run on the most expensive model?
- Simple reformatting tasks running on Opus when Haiku would do
- Boilerplate generation that doesn't need reasoning
- Data extraction from structured files (no creativity required)

### 4. Caching opportunities
Are identical or near-identical prompts being sent repeatedly?
- Same DB schema loaded fresh each session
- Same component library read by Frontend on every task
- Same migration data fetched repeatedly by Content

## Modes

### Mode: Full Audit
Complete cost analysis across all departments with model-task mismatch detection and caching recommendations.

### Mode: Quick Summary
Per-department cost summary from the last session. Use when the operator asks "how much did today cost?"

### Mode: Task Estimate
Cost estimate for a proposed task based on similar past tasks. Use before dispatching expensive work.

### Mode: Waste Finder
Top 3 waste patterns with specific file/prompt evidence. Use when costs are unexpectedly high.

## How This Skill Works

### Step 1: Read cost history
Parse playbook.md for all `($X.XXXX)` cost entries. Build a table:

| Department | Task | Cost | Est. complexity |
|-----------|------|------|----------------|
| backend | security review | $1.24 | medium |
| frontend | accessibility audit | $1.55 | medium |
| content | tweet drafts | $0.23 | low |

### Step 2: Flag outliers
Any task costing > 3x the median for its complexity tier is an outlier. Investigate:
- What did the agent read that it didn't need?
- Did it loop unnecessarily?
- Was the task scope unclear?

### Step 3: Model audit
For each department, categorise tasks by reasoning requirement:
- **No reasoning needed** — data extraction, reformatting, template filling → Haiku
- **Light reasoning** — copy editing, simple code checks → Sonnet
- **Heavy reasoning** — architecture decisions, security review, strategic analysis → Opus/Sonnet 4.x

### Step 4: Caching recommendations
Identify files/data that are loaded repeatedly and could be:
- Pre-loaded into department memory files (avoiding fresh reads)
- Cached in a shared `.orchestra/cache/` directory with TTL
- Summarised once and referenced by pointer

### Step 5: Write recommendations
Output: `/tmp/token_audit_YYYY-MM-DD.md` with:
1. Cost summary by department (last N sessions)
2. Top 3 waste patterns with specific examples
3. Model swap recommendations with estimated savings
4. Caching candidates with implementation notes

## Proactive Triggers

Surface these WITHOUT being asked:
- **Total session cost > $5** — Flag before dispatching more tasks. Is the remaining work worth it?
- **Single task cost > $2** — Investigate what the agent loaded. Was it justified?
- **Department cost growing session-over-session** — Memory files ballooning? Scope creep?
- **Before scaling** — If the operator says "I want to run orchestra daily", run a full audit first. Unoptimised daily runs at current cost could become expensive fast.

## Concrete Optimisations to Recommend

When patterns are found, suggest specific changes:

```markdown
# Recommendation: Switch Content department to Haiku for tweet drafting
Current: ~$0.25/task on Sonnet
Estimated with Haiku: ~$0.04/task
Saving: ~84% on low-complexity copy tasks
Risk: Low — tweet drafts don't require complex reasoning

# Recommendation: Cache DB schema in backend/memory.md
Pattern: Backend reads full schema on every task
Fix: Add schema summary to backend/memory.md, refresh weekly
Estimated saving: ~200 input tokens per task
```

## Prerequisites

Infrastructure needed before this skill can run autonomously:

1. **Structured cost logging** — Currently costs appear as prose in playbook.md (`($0.23)`). Needs a machine-parseable cost log: `{date, department, task, input_tokens, output_tokens, cost, model}`. Even a simple JSON append per task would work.

2. **Model metadata per task** — Cost alone doesn't tell you if the model was right for the job. Needs `model_id` logged alongside cost so mismatches can be detected.

3. **Complexity classification** — A lightweight rubric for classifying task complexity (low/medium/high) either manually tagged or auto-detected from task description length and output artifact type.

4. **Baseline period** — At least 10 sessions of data before recommendations are meaningful. The first audit with fewer than 10 sessions should only report, not recommend.

## Output Artifacts

| Request | Deliverable |
|---------|------------|
| "Run token audit" | `/tmp/token_audit_YYYY-MM-DD.md` — full analysis with recommendations |
| "How much did today cost?" | Per-department cost summary from playbook entries |
| "Is this task worth running?" | Cost estimate based on similar past tasks + complexity |
| "Where are we wasting tokens?" | Top 3 waste patterns with specific file/prompt evidence |
