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
Master Agent ─── decomposes task
    │
    ▼
Strategy & QA ─── approve / challenge / veto
    │
    ▼
Department Agents ─── execute in parallel
    │
    ▼
Testing Agents ─── verify the work
    │
    ▼
Memory + Playbook ─── agents remember and improve
```

Built in production on [IndieStack](https://indiestack.ai). Not theory. Not a demo. A system that ships real products while the founders sleep.

## What's inside

### Orchestra — multi-agent coordination
6 specialist departments + S&QA gating. Real-time communication via [claude-peers](https://github.com/louislva/claude-peers-mcp). Every task goes through a Strategy & QA agent that can approve, challenge, or veto before any work executes.

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

| Agent | What it does | How we use it |
|-------|-------------|--------------|
| **Chaos Monkey** | SQLi, XSS, auth bypass, rate limit testing | Found reflected XSS in its first run |
| **Synthetic User** | Simulates user journey across key pages | Catches broken UX before deploy |
| **Build in Public** | Reads git history, drafts social posts | Turns commits into content |
| **Token Economist** | Tracks per-department costs | Found Frontend costs 5x more than DevOps |
| **Event Reactor** | Watches prod for signups, claims, spikes | Auto-notifies on real-time events |
| **Results Tracker** | Mini CRM for outreach | Tracks which templates get replies |

### Skills — battle-tested, validated, scored

16 skills built from real production experience. Each one follows the [authoring standard](reference/skill-authoring-standard.md) and scores against our validator.

```bash
# Validate all skills
python3 tools/orchestra_skill_validator.py --all

# Current score: 86% average, all operational skills grade A
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

### Tools — quality infrastructure

- **Skill Validator** — scores skills against the authoring standard (frontmatter, modes, triggers, artifacts)
- **Quality Scorer** — multi-dimensional skill quality assessment
- **Session State** — persistent state that survives restarts
- **Skill Loader** — discover, search, and install skills from multiple sources (local, department, user-level, GitHub)
- **Team Coordinator** — agent team management with shared task lists, dependency tracking, file-locked task claiming, and message routing
- **Hooks Engine** — lifecycle event automation (PreToolUse, PostToolUse, Stop, TaskCompleted) with command/prompt/agent execution types and blocking gates
- **Memory Scoper** — three-tier memory hierarchy (user/project/department) with path-scoped rules, context budgeting, and health checks for bloat/staleness
- **Coordinator** — parallel worker dispatch with synthesis: decompose task, workers analyze independently, lead synthesizes into RECOMMENDATION.md
- **Trust Engine** — agent reputation scoring with Bayesian updates, streak bonuses, UCB1 exploration, and trust-weighted output aggregation. No other framework has this.
- **Blackboard Protocol** — agents self-organize around a shared coordination surface instead of rigid orchestration graphs. Research shows 13-57% improvement over hierarchical patterns.

## Quick Start

### Option A: Full orchestra (recommended)

Prerequisites: [Claude Code](https://claude.ai/claude-code) v2.1.80+, [bun](https://bun.sh), [claude-peers](https://github.com/louislva/claude-peers-mcp), [tmux](https://github.com/tmux/tmux)

```bash
# Clone
git clone https://github.com/oatcake21/oats-autonomous-agents.git
cd oats-autonomous-agents

# Install claude-peers
git clone https://github.com/louislva/claude-peers-mcp.git ~/claude-peers-mcp
cd ~/claude-peers-mcp && bun install
claude mcp add --scope user --transport stdio claude-peers -- ~/.bun/bin/bun ~/claude-peers-mcp/server.ts

# Launch the orchestra
orchestra/launch.sh
tmux attach -t orchestra
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

We went from 51% to 93% average score across 15 skills in one session using this loop. The Karpathy autoresearch pattern, applied to agent behavior instead of model training.

## How it was built

This framework was built by an AI agent (Claude) managing 6 department agents on [IndieStack](https://indiestack.ai) over 3 days. The Master agent:

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
2. Run the validator: `python3 tools/orchestra_skill_validator.py skills/your-skill-name/SKILL.md`
3. Score must be 70%+ (grade B or higher)
4. Submit PR with: what the skill does, where you used it, what score it gets

## Built by

[oatcake21](https://github.com/oatcake21) — with a lot of help from Claude.

Part of the [IndieStack](https://indiestack.ai) ecosystem — the discovery layer between AI coding agents and 3,100+ developer tools.

## License

MIT
