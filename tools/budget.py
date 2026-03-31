#!/usr/bin/env python3
"""Token Budget — per-agent cost limits with circuit breakers.

Universal pain point: runaway agents burning $4+ on a single task.
No framework ships automatic cost limits. OATS does.

How it works:
- Each agent gets a token budget (input + output)
- The budget tracks consumption per-task and per-session
- At 85% usage, a WARNING fires (via hooks if configured)
- At 100%, a CIRCUIT BREAK fires — the agent is paused
- Cool-down period before the agent can resume
- Session-level budget caps total spend across all agents

Integrates with:
- Hooks engine: fires PreToolUse deny when budget exhausted
- Trust engine: budget overruns reduce trust score
- Orchestrator: reports budget status in health checks

Usage:
    tracker = BudgetTracker()
    tracker.set_budget("backend", tokens=200_000, cost_usd=1.50)
    tracker.set_budget("frontend", tokens=150_000, cost_usd=1.00)
    tracker.set_session_budget(tokens=500_000, cost_usd=5.00)

    # Record usage
    tracker.consume("backend", input_tokens=1500, output_tokens=800)

    # Check before tool use
    if not tracker.can_proceed("backend"):
        print("Budget exhausted — circuit break!")

CLI:
    python3 tools/budget.py set backend 200000 --cost 1.50
    python3 tools/budget.py consume backend 1500 800
    python3 tools/budget.py status
    python3 tools/budget.py check backend
    python3 tools/budget.py reset
"""

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


BUDGET_FILE = Path(".oats/budgets.json")

# Approximate costs per 1M tokens (Anthropic pricing, March 2026)
MODEL_COSTS = {
    "opus": {"input": 15.0, "output": 75.0},
    "sonnet": {"input": 3.0, "output": 15.0},
    "haiku": {"input": 0.80, "output": 4.0},
}


@dataclass
class AgentBudget:
    agent_id: str
    token_limit: int = 200_000
    cost_limit_usd: float = 2.0
    tokens_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    tasks_run: int = 0
    circuit_broken: bool = False
    broken_at: Optional[str] = None
    warnings_fired: int = 0
    model: str = "sonnet"


class BudgetTracker:
    """Per-agent token budgets with circuit breakers."""

    def __init__(self, state_file: str = None, warning_threshold: float = 0.85):
        self.state_file = Path(state_file) if state_file else BUDGET_FILE
        self.warning_threshold = warning_threshold
        self.agents: dict[str, AgentBudget] = {}
        self.session_token_limit: int = 500_000
        self.session_cost_limit: float = 5.0
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                for aid, bd in data.get("agents", {}).items():
                    self.agents[aid] = AgentBudget(**bd)
                self.session_token_limit = data.get("session_token_limit", 500_000)
                self.session_cost_limit = data.get("session_cost_limit", 5.0)
            except Exception:
                pass

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "agents": {aid: asdict(b) for aid, b in self.agents.items()},
            "session_token_limit": self.session_token_limit,
            "session_cost_limit": self.session_cost_limit,
            "updated_at": datetime.now().isoformat(),
        }
        self.state_file.write_text(json.dumps(data, indent=2))

    def set_budget(self, agent_id: str, tokens: int = 200_000,
                   cost_usd: float = 2.0, model: str = "sonnet"):
        """Set or update an agent's budget."""
        if agent_id in self.agents:
            self.agents[agent_id].token_limit = tokens
            self.agents[agent_id].cost_limit_usd = cost_usd
            self.agents[agent_id].model = model
        else:
            self.agents[agent_id] = AgentBudget(
                agent_id=agent_id,
                token_limit=tokens,
                cost_limit_usd=cost_usd,
                model=model,
            )
        self._save()

    def set_session_budget(self, tokens: int = 500_000, cost_usd: float = 5.0):
        """Set session-level budget cap across all agents."""
        self.session_token_limit = tokens
        self.session_cost_limit = cost_usd
        self._save()

    def consume(self, agent_id: str, input_tokens: int = 0,
                output_tokens: int = 0) -> dict:
        """Record token consumption. Returns status dict.

        Returns:
            {"ok": bool, "warning": bool, "circuit_break": bool, "message": str}
        """
        if agent_id not in self.agents:
            self.set_budget(agent_id)

        budget = self.agents[agent_id]

        if budget.circuit_broken:
            return {
                "ok": False, "warning": False, "circuit_break": True,
                "message": f"{agent_id} is circuit-broken since {budget.broken_at}",
            }

        budget.input_tokens += input_tokens
        budget.output_tokens += output_tokens
        budget.tokens_used += input_tokens + output_tokens
        budget.tasks_run += 1

        # Calculate cost
        rates = MODEL_COSTS.get(budget.model, MODEL_COSTS["sonnet"])
        budget.cost_usd = (
            budget.input_tokens * rates["input"] / 1_000_000 +
            budget.output_tokens * rates["output"] / 1_000_000
        )

        result = {"ok": True, "warning": False, "circuit_break": False, "message": ""}

        # Check agent budget
        token_pct = budget.tokens_used / max(1, budget.token_limit)
        cost_pct = budget.cost_usd / max(0.001, budget.cost_limit_usd)
        usage_pct = max(token_pct, cost_pct)

        if usage_pct >= 1.0:
            budget.circuit_broken = True
            budget.broken_at = datetime.now().isoformat()
            result = {
                "ok": False, "warning": False, "circuit_break": True,
                "message": f"CIRCUIT BREAK: {agent_id} at {usage_pct:.0%} "
                           f"({budget.tokens_used:,} tokens, ${budget.cost_usd:.2f})",
            }
        elif usage_pct >= self.warning_threshold:
            budget.warnings_fired += 1
            result = {
                "ok": True, "warning": True, "circuit_break": False,
                "message": f"WARNING: {agent_id} at {usage_pct:.0%} of budget "
                           f"({budget.tokens_used:,}/{budget.token_limit:,} tokens)",
            }

        # Check session budget
        total_tokens = sum(b.tokens_used for b in self.agents.values())
        total_cost = sum(b.cost_usd for b in self.agents.values())
        if total_tokens >= self.session_token_limit or total_cost >= self.session_cost_limit:
            result = {
                "ok": False, "warning": False, "circuit_break": True,
                "message": f"SESSION LIMIT: {total_tokens:,} tokens, ${total_cost:.2f} "
                           f"(limit: {self.session_token_limit:,} tokens, ${self.session_cost_limit:.2f})",
            }

        self._save()
        return result

    def can_proceed(self, agent_id: str) -> bool:
        """Quick check: can this agent run another task?"""
        if agent_id not in self.agents:
            return True
        budget = self.agents[agent_id]
        if budget.circuit_broken:
            return False
        # Check session limit
        total_tokens = sum(b.tokens_used for b in self.agents.values())
        total_cost = sum(b.cost_usd for b in self.agents.values())
        if total_tokens >= self.session_token_limit or total_cost >= self.session_cost_limit:
            return False
        return True

    def reset(self, agent_id: str = None):
        """Reset budget counters. If no agent specified, reset all."""
        if agent_id:
            if agent_id in self.agents:
                b = self.agents[agent_id]
                b.tokens_used = 0
                b.input_tokens = 0
                b.output_tokens = 0
                b.cost_usd = 0.0
                b.tasks_run = 0
                b.circuit_broken = False
                b.broken_at = None
                b.warnings_fired = 0
        else:
            for b in self.agents.values():
                b.tokens_used = 0
                b.input_tokens = 0
                b.output_tokens = 0
                b.cost_usd = 0.0
                b.tasks_run = 0
                b.circuit_broken = False
                b.broken_at = None
                b.warnings_fired = 0
        self._save()

    def status(self) -> dict:
        """Get full budget status."""
        total_tokens = sum(b.tokens_used for b in self.agents.values())
        total_cost = sum(b.cost_usd for b in self.agents.values())
        broken = [b.agent_id for b in self.agents.values() if b.circuit_broken]

        return {
            "agents": {aid: asdict(b) for aid, b in self.agents.items()},
            "session": {
                "tokens_used": total_tokens,
                "token_limit": self.session_token_limit,
                "cost_usd": round(total_cost, 4),
                "cost_limit": self.session_cost_limit,
                "pct": round(max(
                    total_tokens / max(1, self.session_token_limit),
                    total_cost / max(0.001, self.session_cost_limit),
                ) * 100, 1),
            },
            "circuit_broken": broken,
        }


def main():
    if len(sys.argv) < 2:
        print("Token Budget — per-agent cost limits with circuit breakers")
        print()
        print("Usage:")
        print("  budget.py set <agent> <tokens> [--cost <usd>] [--model opus|sonnet|haiku]")
        print("  budget.py consume <agent> <input_tokens> <output_tokens>")
        print("  budget.py check <agent>")
        print("  budget.py status")
        print("  budget.py reset [agent]")
        print("  budget.py session <tokens> <cost_usd>")
        return

    cmd = sys.argv[1]
    tracker = BudgetTracker()

    if cmd == "set":
        if len(sys.argv) < 4:
            print("Usage: budget.py set <agent> <tokens> [--cost <usd>]")
            return
        agent = sys.argv[2]
        tokens = int(sys.argv[3])
        cost = 2.0
        model = "sonnet"
        if "--cost" in sys.argv:
            cost = float(sys.argv[sys.argv.index("--cost") + 1])
        if "--model" in sys.argv:
            model = sys.argv[sys.argv.index("--model") + 1]
        tracker.set_budget(agent, tokens, cost, model)
        print(f"  {agent}: {tokens:,} tokens, ${cost:.2f} limit, model={model}")

    elif cmd == "consume":
        if len(sys.argv) < 5:
            print("Usage: budget.py consume <agent> <input_tokens> <output_tokens>")
            return
        result = tracker.consume(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
        if result["circuit_break"]:
            print(f"  !!! {result['message']}")
        elif result["warning"]:
            print(f"  *** {result['message']}")
        else:
            b = tracker.agents[sys.argv[2]]
            pct = b.tokens_used / max(1, b.token_limit) * 100
            print(f"  {sys.argv[2]}: {b.tokens_used:,}/{b.token_limit:,} tokens ({pct:.0f}%) ${b.cost_usd:.3f}")

    elif cmd == "check":
        if len(sys.argv) < 3:
            return
        ok = tracker.can_proceed(sys.argv[2])
        print(f"  {sys.argv[2]}: {'GO' if ok else 'BLOCKED'}")

    elif cmd == "status":
        s = tracker.status()
        session = s["session"]
        print(f"{'='*55}")
        print(f"  Session: {session['tokens_used']:,}/{session['token_limit']:,} tokens "
              f"({session['pct']:.1f}%) ${session['cost_usd']:.3f}/${session['cost_limit']:.2f}")
        if s["circuit_broken"]:
            print(f"  CIRCUIT BROKEN: {', '.join(s['circuit_broken'])}")
        print(f"{'='*55}")
        print(f"  {'Agent':12s} {'Tokens':>12s} {'Limit':>12s} {'%':>6s} {'Cost':>8s} {'Status':>10s}")
        print(f"  {'-'*62}")
        for aid, b in s["agents"].items():
            pct = b["tokens_used"] / max(1, b["token_limit"]) * 100
            status = "BROKEN" if b["circuit_broken"] else "warning" if pct >= 85 else "ok"
            print(f"  {aid:12s} {b['tokens_used']:>12,} {b['token_limit']:>12,} {pct:>5.0f}% "
                  f"${b['cost_usd']:>7.3f} {status:>10s}")

    elif cmd == "reset":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        tracker.reset(agent)
        print(f"  Reset {'all agents' if not agent else agent}")

    elif cmd == "session":
        if len(sys.argv) < 4:
            print("Usage: budget.py session <tokens> <cost_usd>")
            return
        tracker.set_session_budget(int(sys.argv[2]), float(sys.argv[3]))
        print(f"  Session budget: {int(sys.argv[2]):,} tokens, ${float(sys.argv[3]):.2f}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
