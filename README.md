# OATS — Autonomous Agents

**60-70% fewer tokens than naive multi-agent setups.** A complete operating system for autonomous AI teams — not a prompt template, not a framework wrapper.

*This entire repo was built by OATS agents managing themselves. The git history is the proof.*

---

## Why OATS?

- **Cheap model does the work, expensive model makes the calls.** Manager (Sonnet) handles 80%+ of tasks. CEO (Opus) only fires on deterministic escalation rules — no guessing, no wasted budget.
- **Zero external dependencies.** stdlib only. No LangChain, no OpenAI SDK, no vendor lock-in.
- **Self-improving.** The agents validate and rewrite their own skills. We went from 51% to 100% average skill score using this loop.

---

## How it compares

| Feature | OATS | CrewAI | AutoGen | LangGraph |
|---------|------|--------|---------|-----------|
| **Manager/CEO model split** | ✅ cheap model for routine, expensive for strategy | ❌ | ❌ | ❌ |
| **Deterministic escalation rules** | ✅ ALWAYS/NEVER config, no ambiguity | ❌ | ❌ | ❌ |
| **Shared RAG knowledge base** | ✅ LightRAG MCP, agents query not read files | ❌ | ❌ | ❌ |
| Token budget + circuit breakers | ✅ per-agent limits, auto-pause at 100% | ❌ | ❌ | ❌ |
| Agent trust scoring | ✅ Bayesian reputation with streak bonuses | ❌ | ❌ | ❌ |
| Blackboard self-organisation | ✅ agents coordinate without rigid graphs | ❌ | ❌ | ❌ |
| Deterministic trace replay | ✅ record runs, replay for debugging | ❌ | ❌ | ❌ |
| Lifecycle hooks (7 events) | ✅ blocking gates | ❌ | Partial | ❌ |
| Memory consolidation | ✅ 3-gate dream system | ❌ | ❌ | ❌ |
| Self-improving skills | ✅ validator + autoresearch loop | ❌ | ❌ | ❌ |
| External dependencies | **None** (stdlib only) | LangChain | OpenAI SDK | LangChain |

> Research basis: [arxiv 2505.24239](https://arxiv.org/abs/2505.24239) (credibility scoring), [arxiv 2507.01701](https://arxiv.org/abs/2507.01701) (blackboard architecture), [OTel GenAI conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

---

## The token savings, concretely

Naive multi-agent: every task hits your most capable (most expensive) model. OATS routes by deterministic rules:

```
Routine task (80%+ of work)  →  Manager (Sonnet)   ~$3/M tokens input
Strategic / high-risk task   →  CEO (Opus)          ~$15/M tokens input
```

In production on IndieStack over one sprint: the Token Economist agent logged Frontend at 5× the cost of DevOps. The CEO only fired 11 times in 200+ tasks. That ratio — not the model prices themselves — is where the 60-70% saving comes from. The escalation rules are in `.orchestra/directives/escalation.json`, fully configurable.

---

## Quick Start

**Option A — Just the tools** (no Claude Code, no tmux, 30 seconds):

```bash
git clone https://github.com/Pattyboi101/oats-autonomous-agents.git
cd oats-autonomous-agents
python3 orchestrator.py health
```

Optional RAG support:
```bash
pip install lightrag-hku fastembed mcp[cli]
```

Run agents standalone:
```bash
python3 agents/chaos_monkey.py https://your-staging-site.com
python3 agents/synthetic_user.py https://your-site.com
python3 agents/token_economist.py
python3 orchestrator.py run "Fix the broken auth endpoint"
```

**Option B — Full orchestra** (Claude Code + tmux + bun required):

```bash
# Install claude-peers for real-time agent-to-agent messaging
git clone https://github.com/louislva/claude-peers-mcp.git ~/claude-peers-mcp
cd ~/claude-peers-mcp && bun install
claude mcp add --scope user --transport stdio claude-peers -- ~/.bun/bin/bun ~/claude-peers-mcp/server.ts

# Launch CEO + Manager + 5 departments in tmux
cd oats-autonomous-agents && bash orchestra/launch.sh
tmux attach -t orchestra
```

**Option C — Just the skills** (drop into any Claude Code project):

```bash
cp -r skills/review-checklist ~/.claude/skills/
cp -r skills/deploy-safely ~/.claude/skills/
```

---

## Architecture

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

---

## What's inside

### Orchestra — multi-agent coordination

5 specialist departments + CEO strategic gate. Real-time messaging via [claude-peers](https://github.com/louislva/claude-peers-mcp). Strategic decisions go through CEO who can approve, challenge, or veto.

```bash
python3 orchestrator.py run "Fix the broken auth endpoint"
python3 orchestrator.py run --agent backend "Add rate limiting to /api/search"
python3 orchestrator.py team start feature-x "Build the new dashboard"
python3 orchestrator.py improve --target skills
python3 orchestrator.py health
```

### Agents — autonomous testing & monitoring

9 agents built for real production workloads:

| Agent | What it does | Real result |
|-------|-------------|-------------|
| **Chaos Monkey** | SQLi, XSS, auth bypass, rate limit testing | Found reflected XSS in its first run |
| **Synthetic User** | Simulates user journey across key pages | Catches broken UX before deploy |
| **Token Economist** | Tracks per-department costs | Found Frontend costs 5× more than DevOps |
| **Build in Public** | Reads git history, drafts social posts | Turns commits into content |
| **Event Reactor** | Watches prod for signups, claims, spikes | Auto-notifies on real-time events |
| **Results Tracker** | Mini CRM for outreach | Tracks which templates get replies |
| **Dream** | Memory consolidation with 3-gate system | Compresses learnings between sessions |
| **Verification** | Pre-deploy checks across project types | Catches secrets, syntax errors, broken skills |
| **User Profiler** | Silent visitor profiling from behaviour | Personalises experience without accounts |

### Skills — battle-tested, validated, scored

16 skills built from real production experience. Each follows the [authoring standard](reference/skill-authoring-standard.md) and is scored by the validator.

```bash
python3 tools/skill_validator.py --orchestra --all
# Current: 100% average, all 16 skills grade A
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
| + 5 concept skills | Various | Token economist, synthetic user personas, etc. |

### Tools — 23 infrastructure pieces

- **Escalation Engine** — deterministic ALWAYS/NEVER rules for Manager→CEO routing. CLI for checking tasks, formatting briefs, explaining which rules fire.
- **RAG Server** — LightRAG MCP with fastembed (ONNX, no PyTorch). Shared knowledge base all agents query. No Ollama needed.
- **Trust Engine** — Bayesian agent reputation with streak bonuses and UCB1 exploration.
- **Blackboard Protocol** — agents self-organise around a shared surface instead of rigid graphs. Research shows 13-57% improvement over hierarchical patterns.
- **Token Budget** — per-agent cost limits with circuit breakers. 85%: warning. 100%: agent paused.
- **Tracer** — record agent runs to JSONL, replay deterministically. Timeline view, failure finder, trace diff.
- **Pipeline** — chain tools into repeatable workflows. 5 built-in: research, build, improve, review, full-cycle.
- **Think Engine** — each completed task sparks the next idea. Chains until ideas dry up.
- **Session State**, **Skill Loader**, **Hooks Engine**, **Memory Scoper**, **Coordinator**, **SQLite Mail**, **Test Harness**, **User Profiler**, **Agent Runner**, **RAG Seed**

---

## The self-improvement loop

```
1. Validator scores all skills
2. Master identifies the lowest-scoring skill
3. Master edits the skill (adds modes, triggers, artifacts)
4. Validator re-scores — did it improve?
5. If yes: commit. If no: revert.
6. Repeat until all skills are grade A.
```

We went from 51% to 100% average score across 16 skills using this loop.

---

## MOAT — Master OAT Autonomous Thinking

MOAT is the autonomous brain that directs the orchestra between sessions. Each completed task sparks the next idea. A remote trigger fires hourly, reads the last thought, and continues building.

```
MOAT Brain (cloud, hourly)
    │ reads thought chain → researches → builds → records next thought
    │
    │ if idea needs multiple agents:
    ▼
.orchestra/directives/pending/
    │
    ▼
Manager (local tmux) → departments → results flow back to MOAT brain
```

```bash
python3 tools/pipeline.py run full-cycle
python3 tools/think.py chain
python3 orchestrator.py think "what I built" "what I realized" "where this leads" --confidence 0.8
```

---

## How it was built

Built by AI agents (Claude) managing department agents on [IndieStack](https://indiestack.ai) — the discovery layer for 6,500+ developer tools. The Manager agent:

- Dispatched tasks to Frontend, Backend, DevOps, Content, MCP, and Strategy departments
- Had every task reviewed by S&QA before execution
- Fixed security vulnerabilities the Chaos Monkey found
- Deployed 15+ product improvements with 48/48 smoke tests passing
- Built and validated 16 skills using the autoresearch loop
- Knew when to stop (S&QA vetoed busywork and said "wait for signal")

The git history of IndieStack is the proof.

---

## Contributing

PRs welcome. To add a skill:

1. Create `skills/your-skill-name/SKILL.md` following the [authoring standard](reference/skill-authoring-standard.md)
2. Run: `python3 tools/skill_validator.py --orchestra skills/your-skill-name/SKILL.md`
3. Score must be 70%+ (grade B or higher)
4. Submit PR with: what the skill does, where you used it, what score it gets

---

## Built by

[Pattyboi101](https://github.com/Pattyboi101) — with a lot of help from Claude.

Part of the [IndieStack](https://indiestack.ai) ecosystem.

## License

MIT
