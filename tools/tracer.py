#!/usr/bin/env python3
"""Tracer — record agent runs, replay deterministically for debugging.

Universal pain point: debugging multi-agent systems is hell. You can't
reproduce failures because LLM calls are non-deterministic. OATS solves
this with a trace/replay system.

Record mode: captures every event (tool calls, decisions, memory ops)
to a JSONL file with full input/output. Non-determinism (timestamps,
random IDs) is captured so replay is exact.

Replay mode: reads the trace file and replays events, letting you
step through what happened, find where things went wrong, and
understand agent decisions.

Follows OpenTelemetry GenAI Semantic Conventions (gen_ai.agent.id,
gen_ai.agent.name, gen_ai.usage.input_tokens) and OWASP Agent
Observability Standard (agent.thought, agent.reasoning).

Usage:
    # Start recording
    tracer = Tracer("run-001")
    tracer.record("backend", "tool_call", {"tool": "Edit", "file": "db.py"}, {"status": "ok"})
    tracer.record("backend", "decision", {"choice": "use redis"}, {"reason": "faster"})
    tracer.save()

    # Replay
    tracer = Tracer.load("run-001")
    for event in tracer.replay():
        print(event)

    # Analyze
    tracer.summary()
    tracer.timeline()
    tracer.find_failures()

CLI:
    python3 tools/tracer.py record <run-id> <agent> <kind> <input-json> <output-json>
    python3 tools/tracer.py replay <run-id>
    python3 tools/tracer.py summary <run-id>
    python3 tools/tracer.py timeline <run-id>
    python3 tools/tracer.py failures <run-id>
    python3 tools/tracer.py list
    python3 tools/tracer.py diff <run-id-1> <run-id-2>
"""

import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


TRACE_DIR = Path(".oats/traces")

VALID_KINDS = {
    "tool_call",      # agent used a tool (Edit, Bash, Read, etc.)
    "decision",       # agent made a choice between options
    "memory_read",    # agent loaded memory/context
    "memory_write",   # agent wrote to memory
    "message_send",   # agent sent message to another agent
    "message_recv",   # agent received message
    "task_start",     # agent started a task
    "task_complete",  # agent completed a task
    "task_fail",      # agent failed a task
    "hook_fire",      # lifecycle hook fired
    "budget_warn",    # budget warning
    "budget_break",   # circuit breaker fired
    "error",          # unexpected error
    "custom",         # user-defined event
}


@dataclass
class TraceEvent:
    run_id: str
    step: int
    agent: str
    kind: str
    input_data: dict
    output_data: dict
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    reasoning: str = ""  # OWASP AOS agent.reasoning
    metadata: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        return self.output_data.get("status", "unknown")

    @property
    def is_failure(self) -> bool:
        return self.kind in ("task_fail", "error", "budget_break") or \
               self.output_data.get("status") == "failed"


class Tracer:
    """Record and replay agent execution traces."""

    def __init__(self, run_id: str = None):
        self.run_id = run_id or f"run-{int(time.time())}"
        self.events: list[TraceEvent] = []
        self.step_counter = 0
        self.trace_file = TRACE_DIR / f"{self.run_id}.jsonl"

    def record(self, agent: str, kind: str, input_data: dict,
               output_data: dict, **kwargs) -> TraceEvent:
        """Record a single event."""
        self.step_counter += 1
        event = TraceEvent(
            run_id=self.run_id,
            step=self.step_counter,
            agent=agent,
            kind=kind,
            input_data=input_data,
            output_data=output_data,
            **kwargs,
        )
        self.events.append(event)

        # Append to file immediately (crash-safe)
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.trace_file, "a") as f:
            f.write(json.dumps(asdict(event)) + "\n")

        return event

    @classmethod
    def load(cls, run_id: str) -> "Tracer":
        """Load a trace from disk."""
        tracer = cls(run_id)
        trace_file = TRACE_DIR / f"{run_id}.jsonl"
        if not trace_file.exists():
            raise FileNotFoundError(f"Trace {run_id} not found at {trace_file}")

        with open(trace_file) as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    tracer.events.append(TraceEvent(**data))
                    tracer.step_counter = max(tracer.step_counter, data.get("step", 0))

        return tracer

    def replay(self, agent: str = None, kind: str = None):
        """Iterate through events, optionally filtered."""
        for event in self.events:
            if agent and event.agent != agent:
                continue
            if kind and event.kind != kind:
                continue
            yield event

    def summary(self) -> dict:
        """Get a summary of the trace."""
        agents = set()
        by_kind = {}
        by_agent = {}
        failures = 0
        total_tokens = 0
        total_cost = 0.0

        for e in self.events:
            agents.add(e.agent)
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
            by_agent[e.agent] = by_agent.get(e.agent, 0) + 1
            if e.is_failure:
                failures += 1
            total_tokens += e.tokens_in + e.tokens_out
            total_cost += e.cost_usd

        duration = 0
        if self.events:
            duration = self.events[-1].timestamp - self.events[0].timestamp

        return {
            "run_id": self.run_id,
            "events": len(self.events),
            "agents": sorted(agents),
            "by_kind": by_kind,
            "by_agent": by_agent,
            "failures": failures,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 4),
            "duration_sec": round(duration, 1),
        }

    def timeline(self, max_width: int = 60) -> str:
        """Generate a visual timeline of events."""
        if not self.events:
            return "Empty trace."

        lines = []
        agents = sorted(set(e.agent for e in self.events))

        for e in self.events:
            kind_icon = {
                "tool_call": "T", "decision": "D", "memory_read": "R",
                "memory_write": "W", "message_send": ">", "message_recv": "<",
                "task_start": "[", "task_complete": "]", "task_fail": "X",
                "hook_fire": "H", "budget_warn": "!", "budget_break": "B",
                "error": "E", "custom": ".",
            }.get(e.kind, "?")

            fail_marker = " !!!" if e.is_failure else ""
            desc = ""
            if e.kind == "tool_call":
                desc = e.input_data.get("tool", "")
            elif e.kind == "decision":
                desc = e.input_data.get("choice", "")[:30]
            elif e.kind in ("task_start", "task_complete", "task_fail"):
                desc = e.input_data.get("task_id", "")

            lines.append(f"  {e.step:>3d} [{kind_icon}] {e.agent:12s} {e.kind:16s} {desc:30s}{fail_marker}")

        return "\n".join(lines)

    def find_failures(self) -> list:
        """Find all failure events with context (2 events before each failure)."""
        failures = []
        for i, e in enumerate(self.events):
            if e.is_failure:
                context = self.events[max(0, i - 2):i]
                failures.append({
                    "event": e,
                    "context": context,
                    "step": e.step,
                    "agent": e.agent,
                    "kind": e.kind,
                    "output": e.output_data,
                })
        return failures

    def diff(self, other: "Tracer") -> list:
        """Compare two traces — find where they diverge."""
        diffs = []
        max_steps = max(len(self.events), len(other.events))

        for i in range(max_steps):
            e1 = self.events[i] if i < len(self.events) else None
            e2 = other.events[i] if i < len(other.events) else None

            if e1 is None:
                diffs.append({"step": i + 1, "type": "missing_in_first", "event": asdict(e2)})
            elif e2 is None:
                diffs.append({"step": i + 1, "type": "missing_in_second", "event": asdict(e1)})
            elif e1.agent != e2.agent or e1.kind != e2.kind:
                diffs.append({
                    "step": i + 1, "type": "diverged",
                    "first": f"{e1.agent}/{e1.kind}",
                    "second": f"{e2.agent}/{e2.kind}",
                })
            elif e1.output_data != e2.output_data:
                diffs.append({
                    "step": i + 1, "type": "different_output",
                    "agent": e1.agent, "kind": e1.kind,
                })

        return diffs


def main():
    if len(sys.argv) < 2:
        print("Tracer — record agent runs, replay for debugging")
        print()
        print("Usage:")
        print("  tracer.py record <run-id> <agent> <kind> '<input-json>' '<output-json>'")
        print("  tracer.py replay <run-id> [--agent <name>] [--kind <type>]")
        print("  tracer.py summary <run-id>")
        print("  tracer.py timeline <run-id>")
        print("  tracer.py failures <run-id>")
        print("  tracer.py diff <run-id-1> <run-id-2>")
        print("  tracer.py list")
        print()
        print(f"Event kinds: {', '.join(sorted(VALID_KINDS))}")
        return

    cmd = sys.argv[1]

    if cmd == "record":
        if len(sys.argv) < 7:
            print("Usage: tracer.py record <run-id> <agent> <kind> '<input>' '<output>'")
            return
        tracer = Tracer(sys.argv[2])
        # Load existing if appending
        if tracer.trace_file.exists():
            tracer = Tracer.load(sys.argv[2])
        inp = json.loads(sys.argv[5]) if sys.argv[5].startswith("{") else {"value": sys.argv[5]}
        out = json.loads(sys.argv[6]) if sys.argv[6].startswith("{") else {"value": sys.argv[6]}
        event = tracer.record(sys.argv[3], sys.argv[4], inp, out)
        print(f"  Step {event.step}: [{event.kind}] {event.agent}")

    elif cmd == "replay":
        if len(sys.argv) < 3:
            return
        tracer = Tracer.load(sys.argv[2])
        agent_filter = None
        kind_filter = None
        if "--agent" in sys.argv:
            agent_filter = sys.argv[sys.argv.index("--agent") + 1]
        if "--kind" in sys.argv:
            kind_filter = sys.argv[sys.argv.index("--kind") + 1]

        for e in tracer.replay(agent=agent_filter, kind=kind_filter):
            fail = " [FAIL]" if e.is_failure else ""
            print(f"  Step {e.step}: [{e.kind}] {e.agent}{fail}")
            if e.input_data:
                inp_str = json.dumps(e.input_data)[:80]
                print(f"    in:  {inp_str}")
            if e.output_data:
                out_str = json.dumps(e.output_data)[:80]
                print(f"    out: {out_str}")

    elif cmd == "summary":
        if len(sys.argv) < 3:
            return
        tracer = Tracer.load(sys.argv[2])
        s = tracer.summary()
        print(f"Run: {s['run_id']}")
        print(f"Events: {s['events']} | Failures: {s['failures']} | Duration: {s['duration_sec']}s")
        print(f"Tokens: {s['total_tokens']:,} | Cost: ${s['total_cost']:.4f}")
        print(f"Agents: {', '.join(s['agents'])}")
        print(f"\nBy kind:")
        for k, v in sorted(s["by_kind"].items(), key=lambda x: -x[1]):
            print(f"  {k:20s} {v}")
        print(f"\nBy agent:")
        for a, v in sorted(s["by_agent"].items(), key=lambda x: -x[1]):
            print(f"  {a:15s} {v} events")

    elif cmd == "timeline":
        if len(sys.argv) < 3:
            return
        tracer = Tracer.load(sys.argv[2])
        print(tracer.timeline())

    elif cmd == "failures":
        if len(sys.argv) < 3:
            return
        tracer = Tracer.load(sys.argv[2])
        failures = tracer.find_failures()
        if not failures:
            print("No failures found.")
            return
        print(f"{len(failures)} failure(s):\n")
        for f in failures:
            print(f"  Step {f['step']}: [{f['kind']}] {f['agent']}")
            print(f"    Output: {json.dumps(f['output'])[:100]}")
            if f["context"]:
                print(f"    Context (preceding events):")
                for c in f["context"]:
                    print(f"      Step {c.step}: [{c.kind}] {c.agent}")

    elif cmd == "diff":
        if len(sys.argv) < 4:
            print("Usage: tracer.py diff <run-id-1> <run-id-2>")
            return
        t1 = Tracer.load(sys.argv[2])
        t2 = Tracer.load(sys.argv[3])
        diffs = t1.diff(t2)
        if not diffs:
            print("Traces are identical.")
        else:
            print(f"{len(diffs)} difference(s):")
            for d in diffs[:20]:
                if d["type"] == "diverged":
                    print(f"  Step {d['step']}: DIVERGED — {d['first']} vs {d['second']}")
                elif d["type"] == "different_output":
                    print(f"  Step {d['step']}: different output — {d['agent']}/{d['kind']}")
                else:
                    print(f"  Step {d['step']}: {d['type']}")

    elif cmd == "list":
        if not TRACE_DIR.exists():
            print("No traces.")
            return
        for f in sorted(TRACE_DIR.glob("*.jsonl")):
            lines = sum(1 for _ in open(f))
            size = f.stat().st_size
            print(f"  {f.stem:25s} {lines:>5d} events  {size:>8,} bytes")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
