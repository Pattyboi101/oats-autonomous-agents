# OATS — Autonomous Agents

**Autonomously made by OATS autonomous agents.**

*This entire framework — the orchestra, the skills, the testing agents, the validator — was built by AI agents managing themselves. The git history proves it. We ate our own dogfood and it tasted great.*

---

## What is this?

Everything you need to run AI agents as an autonomous team. Not a skill list. Not a prompt template. A complete operating system for multi-agent coordination.

```
You (human)
    │
    ▼
Manager (Sonnet) ─── handles 80%+ of work, fast & cheap
    │
    ├── escalation rules fire? ──▶ CEO (Opus) ─── approve / challenge / veto
    │                                   │
    │                                   ▼
    │                              verdict returned
    │
    ▼
Department Agents ─── execute in parallel
    │                  (can escalate directly to CEO)
    ▼
Testing Agents ─── verify the work
    │
    ▼
Shared RAG ─── agents query knowledge, not read full files
```

The Manager/CEO split saves 60-70% on tokens by running routine work on a cheaper model while preserving strategic quality. Escalation rules are deterministic (ALWAYS/NEVER lists) — no ambiguity about what needs senior review.

Built in production on [IndieStack](https://indiestack.ai). Not theory. Not a demo. A system that ships real products while the founders sleep.

## Why OATS over CrewAI / AutoGen / LangGraph?

| Feature | OATS | CrewAI | AutoGen | LangGraph |
|---------|------|--------|---------|-----------|
| **Manager/CEO model split** | **Yes** — cheap model for routine, expensive for strategy | No | No | No |
| **Deterministic escalation rules** | **Yes** — ALWAYS/NEVER lists, config-driven | No | No | No |
| **Shared RAG knowledge base** | **Yes** — LightRAG MCP, agents query not read | No | No | No |
| Agent trust scoring | **Yes** — Bayesian reputation with streak bonuses | No | No | No |
| Blackboard protocol | **Yes** — agents self-organize, no rigid graphs | No | No | No |
| Token budget + circuit breakers | **Yes** — per-agent limits, auto-pause at 100% | No | No | No |
| Deterministic trace replay | **Yes** — record runs, replay for debugging | No | No | No |
| Lifecycle hooks | **Yes** — 7 events, blocking gates | No | Partial | No |
| Memory consolidation with gates | **Yes** — 3-gate dream system | No | No | No |
| Self-improving skills | **Yes** — validator + autoresearch loop | No | No | No |
| Autonomous thought chains | **Yes** — agent generates its own next steps | No | No | No |
| Context budget optimizer | **Yes** — data-driven context pruning | No | No | No |
| Workflow pipelines | **Yes** — chain tools into repeatable cycles | No | No | Partial |
| Silent user profiling | **Yes** | No | No | No |
| Iterative test harness | **Yes** | No | No | No |
| Zero external dependencies | **Yes** — stdlib only (RAG optional) | No (LangChain) | No (OpenAI SDK) | No (LangChain) |

These aren't incremental improvements. Manager/CEO model allocation, deterministic escalation, shared RAG, trust scoring, blackboard coordination, and deterministic replay are **features that don't exist in any other open-source agent framework** as of April 2026. Based on research from [arxiv 2505.24239](https://arxiv.org/abs/2505.24239) (credibility scoring), [arxiv 2507.01701](https://arxiv.org/abs/2507.01701) (blackboard architecture), and [OTel GenAI conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

## What's inside

### Orchestra — multi-agent coordination

**Manager/CEO architecture:** Manager (Sonnet) handles routine work — task decomposition, single-department dispatch, direct coding. CEO (Opus) is a persistent strategic gate, consulted only when deterministic escalation rules fire. Departments can escalate directly to the CEO for complex technical issues.

5 specialist departments + CEO strategic gate. Real-time communication via [claude-peers](https://github.com/louislva/claude-peers-mcp). Strategic decisions go through the CEO who can approve, challenge, or veto.

```bash
# One-shot dispatch
python3 orchestrator.py run "Fix the broken auth endpoint"

# Dispatch to a specific agent
python3 orchestrator.py run --agent backend "Add rate limiting to /api/search"

# Start a team
python3 orchestrator.py team start feature-x "Build the new dashboard"

# Self-improvement loop
python3 orchestrator.py improve --target skills

# System health check
python3 orchestrator.py health

# Persistent mode (living agents in tmux)
orchestra/launch.sh
```

The S&QA agent caught a bug in our outreach emails before 13 real people clicked broken links. It vetoed duplicate busywork that would have wasted $4 in compute. It told the Master agent to stop building and wait for user feedback. That's what a real quality gate looks like.

### Agents — autonomous testing & monitoring

9 agents built for real production workloads:

| Agent | What it does | How we use it |
|-------|-------------|--------------|
| **Chaos Monkey** | SQLi, XSS, auth bypass, rate limit testing | Found reflected XSS in its first run |
| **Synthetic User** | Simulates user journey across key pages | Catches broken UX before deploy |
| **Build in Public** | Reads git history, drafts social posts | Turns commits into content |
| **Token Economist** | Tracks per-department costs | Found Frontend costs 5x more than DevOps |
| **Event Reactor** | Watches prod for signups, claims, spikes | Auto-notifies on real-time events |
| **Results Tracker** | Mini CRM for outreach | Tracks which templates get replies |
| **Dream** | Memory consolidation with 3-gate system | Compresses learnings between sessions |
| **Verification** | Pre-deploy checks across project types | Catches secrets, syntax errors, broken skills |
| **User Profiler** | Silent visitor profiling from behavior | Personalizes experience without accounts |

### Skills — battle-tested, validated, scored

16 skills built from real production experience. Each one follows the [authoring standard](reference/skill-authoring-standard.md) and scores against our validator.

```bash
# Validate all skills
python3 tools/skill_validator.py --orchestra --all

# Current score: 100% average, all 16 skills grade A
```

| Skill | Department | What it does |
|-------|-----------|-------------|
| Orchestra Management | Master | Dispatch protocol, when to stop |
| R&D Architect | Master | Autoresearch loop + hype filter |
| Token Economist | Master | Cost analysis patterns |
| Review Checklist | Strategy | Structured S&QA framework |
| Deploy Safely | DevOps | Pre/post deploy with gotchas |
| Chaos Monkey | DevOps | Security testing patterns |
| Synthetic User | Frontend | Persona-based UX testing |
| Build in Public | Content | Git to social content pipeline |
| F-String HTML Safety | Frontend | XSS prevention patterns |
| Outreach Copy | Content | Email/social templates + voice |
| Production Data Patch | Backend | Safe SSH database updates |
| + 5 more concept skills | Various | Token economist, synthetic user personas, etc. |

### Tools — 23 quality infrastructure tools

- **Escalation Engine** *(new)* — deterministic ALWAYS/NEVER rules for Manager-to-CEO routing. Config-driven, CLI for checking tasks, formatting CEO briefs, and explaining which rules fire. Replaces ad-hoc "review everything" patterns.
- **RAG Server** *(new)* — LightRAG MCP server with fastembed (ONNX, no PyTorch). Shared knowledge base all agents can query. Passthrough LLM for instant operation (no Ollama needed). 4 tools: query, store, store_document, delete.
- **RAG Seed** *(new)* — Auto-discovers knowledge files from standard OATS locations and indexes them. Supports manual paths and dry-run mode.
- **Skill Validator** — unified validator with three modes: structure validation, multi-dimensional quality scoring with letter grades, and orchestra skill validation
- **Session State** — persistent state that survives restarts
- **Skill Loader** — discover, search, and install skills from multiple sources (local, department, user-level, GitHub)
- **Hooks Engine** — lifecycle event automation (PreToolUse, PostToolUse, Stop, TaskCompleted) with command/prompt/agent execution types and blocking gates
- **Memory Scoper** — three-tier memory hierarchy (user/project/department) with path-scoped rules, context budgeting, and health checks for bloat/staleness
- **Coordinator** — parallel worker dispatch with synthesis: decompose task, workers analyze independently, lead synthesizes into RECOMMENDATION.md
- **Trust Engine** — agent reputation scoring with Bayesian updates, streak bonuses, UCB1 exploration, and trust-weighted output aggregation. No other framework has this.
- **Blackboard Protocol** — agents self-organize around a shared coordination surface instead of rigid orchestration graphs. Research shows 13-57% improvement over hierarchical patterns.
- **Token Budget** — per-agent cost limits with circuit breakers. At 85% usage: warning. At 100%: agent paused. Session-level caps prevent runaway spend across all agents.
- **Tracer** — record agent runs to JSONL, replay deterministically for debugging. Timeline view, failure finder with context, trace diff between runs. Follows OTel GenAI + OWASP AOS conventions.
- **Agent Runner** — execute any agent with full instrumentation (tracing + budget + trust + hooks in one command)
- **Pipeline** — chain tools into repeatable workflows with reaction engine (auto-retry + escalation). 5 built-in pipelines: research, build, improve, review, full-cycle.
- **SQLite Mail** — inter-agent messaging with group addresses (@all, @builders), threaded conversations, and priority levels. WAL mode, 1-5ms queries.
- **Think Engine** — autonomous ideation: each completed task sparks the next idea. Thoughts chain together until ideas genuinely dry up.
- **Test Harness** — iterative test runner that validates agent outputs against expected results, with retry logic and diff reporting
- **User Profiler** — silent visitor profiling from behavioral signals, builds user context without requiring accounts or logins

## Quick Start

### Option A: Full orchestra (recommended)

Prerequisites: [Claude Code](https://claude.ai/claude-code) v2.1.80+, [bun](https://bun.sh), [claude-peers](https://github.com/louislva/claude-peers-mcp), [tmux](https://github.com/tmux/tmux)

```bash
# Clone
git clone https://github.com/Pattyboi101/oats-autonomous-agents.git
cd oats-autonomous-agents

# Install claude-peers
git clone https://github.com/louislva/claude-peers-mcp.git ~/claude-peers-mcp
cd ~/claude-peers-mcp && bun install
claude mcp add --scope user --transport stdio claude-peers -- ~/.bun/bin/bun ~/claude-peers-mcp/server.ts

# Launch the orchestra (CEO + Manager + 5 departments)
orchestra/launch.sh
tmux attach -t orchestra

# Optional: launch with shared RAG knowledge base
pip install lightrag-hku fastembed mcp[cli]
python3 tools/rag_seed.py           # index knowledge files
RAG=1 orchestra/launch.sh           # all agents get RAG MCP tools
```

### Option B: Just the skills

```bash
# Copy any skill to your Claude Code skills directory
cp -r skills/review-checklist ~/.claude/skills/
cp -r skills/deploy-safely ~/.claude/skills/
```

### Option C: Just the agents

```bash
# Run any agent standalone
python3 agents/chaos_monkey.py https://your-staging-site.com
python3 agents/synthetic_user.py https://your-site.com
python3 agents/build_in_public.py
python3 agents/token_economist.py
```

### Option D: Just the tools (trust, blackboard, budget, escalation, RAG, tracer)

```bash
# Quickstart — sets up sample config and runs diagnostics
bash quickstart.sh

# Escalation engine — should this task go to the CEO?
python3 tools/escalation.py check "Refactor the payment handler" --files payments.py
python3 tools/escalation.py explain "Add rate limiting to search"
python3 tools/escalation.py rules
python3 tools/escalation.py brief "New pricing tier" --recommendation "Use Stripe meters"

# RAG knowledge base — shared context for all agents
pip install lightrag-hku fastembed mcp[cli]
python3 tools/rag_seed.py --dry-run          # see what would be indexed
python3 tools/rag_seed.py                     # index everything
python3 tools/rag_server.py                   # run as MCP server

# Trust, blackboard, budget, tracer
python3 tools/trust.py register backend frontend devops
python3 tools/trust.py record backend task-001 0.8
python3 tools/trust.py leaderboard

python3 tools/blackboard.py create session-1 "How should we implement caching?"
python3 tools/blackboard.py post session-1 backend proposal "Use Redis"

python3 tools/budget.py set backend 200000 --cost 1.50
python3 tools/budget.py status

python3 tools/tracer.py summary run-001
python3 tools/tracer.py timeline run-001
```

## The self-improvement loop

This is what makes OATS different from a skill list. The agents improve themselves:

```
1. Validator scores all skills
2. Master identifies the lowest-scoring skill
3. Master edits the skill (adds modes, triggers, artifacts)
4. Validator re-scores — did it improve?
5. If yes: commit. If no: revert.
6. Repeat until all skills are grade A.
```

We went from 51% to 100% average score across 16 skills using this loop. The Karpathy autoresearch pattern, applied to agent behavior instead of model training.

## MOAT — Master OAT Autonomous Thinking

MOAT is the autonomous brain that directs an orchestra of agents. It thinks in chains — each completed task sparks the next idea. Between sessions, a remote trigger fires hourly, reads the last thought, and continues building.

```
MOAT Brain (cloud, hourly)
    │ reads thought chain → researches → builds → records next thought
    │
    │ if idea needs multiple agents:
    ▼
.orchestra/directives/pending/
    │
    ▼
Manager (Sonnet, local tmux)
    ├── CEO (Opus, veto power)
    ├── Frontend / Backend / DevOps / Content / MCP
    └── results flow back to MOAT brain
```

The thought chain runs until ideas genuinely dry up. If the brain is uninspired, it searches the web — the internet is limitless inspiration.

```bash
# Run the MOAT full cycle
python3 tools/pipeline.py run full-cycle

# See the thought chain
python3 tools/think.py chain

# Generate a new thought
python3 orchestrator.py think "what I built" "what I realized" "where this leads" --confidence 0.8
```

## How it was built

This framework was built by AI agents (Claude) managing department agents on [IndieStack](https://indiestack.ai). The Manager agent:

- Dispatched tasks to Frontend, Backend, DevOps, Content, MCP, and Strategy departments
- Had every task reviewed by S&QA before execution
- Fixed security vulnerabilities the Chaos Monkey found
- Sent 24 outreach emails to real tool makers
- Deployed 15+ product improvements with 48/48 smoke tests passing
- Built and validated 16 skills using the autoresearch loop
- Knew when to stop (S&QA vetoed busywork and said "wait for signal")

The git history of IndieStack is the proof. This README was not written by a human.

## Contributing

PRs welcome. To add a skill:

1. Create `skills/your-skill-name/SKILL.md` following the [authoring standard](reference/skill-authoring-standard.md)
2. Run the validator: `python3 tools/skill_validator.py --orchestra skills/your-skill-name/SKILL.md`
3. Score must be 70%+ (grade B or higher)
4. Submit PR with: what the skill does, where you used it, what score it gets

## Built by

[Pattyboi101](https://github.com/Pattyboi101) — with a lot of help from Claude.

Part of the [IndieStack](https://indiestack.ai) ecosystem — the discovery layer between AI coding agents and 8,000+ developer tools.

## License

MIT
