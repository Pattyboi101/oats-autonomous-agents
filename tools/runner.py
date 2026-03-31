#!/usr/bin/env python3
"""Agent Runner — execute any agent with full instrumentation.

The missing glue: runs any OATS agent wrapped with tracing, budget
tracking, trust scoring, and lifecycle hooks. One command, full
observability.

Without the runner, each tool is standalone. With it, every agent
run is automatically:
- Traced (tools/tracer.py) — recorded for replay and debugging
- Budget-tracked (tools/budget.py) — circuit breaks if cost exceeds limit
- Trust-scored (tools/trust.py) — outcomes update agent reputation
- Hook-gated (tools/hooks.py) — lifecycle events fire at each stage

Usage:
    # Run an agent with full instrumentation
    python3 tools/runner.py agents/verification.py --full

    # Run with specific agent identity (for trust/budget tracking)
    python3 tools/runner.py agents/chaos_monkey.py --as devops --budget 100000

    # Run a custom command as a tracked agent task
    python3 tools/runner.py --cmd "python3 smoke_test.py" --as qa --task "smoke-test"

    # Dry run — show what would happen without executing
    python3 tools/runner.py agents/dream.py --dry-run
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.tracer import Tracer
from tools.budget import BudgetTracker
from tools.trust import TrustEngine
from tools.hooks import HookEngine


class AgentRunner:
    """Execute agents with full instrumentation."""

    def __init__(self, agent_name: str = "unknown"):
        self.agent_name = agent_name
        self.tracer = Tracer(f"run-{agent_name}-{int(time.time())}")
        self.budget = BudgetTracker()
        self.trust = TrustEngine()
        self.hooks = HookEngine.from_config(".oats/hooks.json")

    def run(self, command: list, task_id: str = None,
            budget_limit: int = 200_000, timeout: int = 300) -> dict:
        """Run a command as a tracked agent task.

        Args:
            command: Command to execute (e.g., ["python3", "agents/verification.py"])
            task_id: Task identifier for tracking
            budget_limit: Token budget for this run
            timeout: Max seconds before kill

        Returns:
            dict with run results, trace ID, and status
        """
        task_id = task_id or f"task-{int(time.time())}"
        run_id = self.tracer.run_id

        print(f"Agent Runner: {self.agent_name}")
        print(f"  Run ID:  {run_id}")
        print(f"  Task:    {task_id}")
        print(f"  Command: {' '.join(command)}")
        print(f"  Budget:  {budget_limit:,} tokens")
        print()

        # Ensure agent is registered
        self.trust.register(self.agent_name)
        self.budget.set_budget(self.agent_name, tokens=budget_limit)

        # Pre-check: can this agent proceed?
        if not self.budget.can_proceed(self.agent_name):
            self.tracer.record(self.agent_name, "budget_break",
                               {"task_id": task_id}, {"status": "blocked"})
            print("  BLOCKED: agent budget exhausted")
            return {"status": "blocked", "reason": "budget_exhausted", "run_id": run_id}

        # Fire SessionStart hook
        hook_results = self.hooks.fire("SessionStart", {"agent": self.agent_name})

        # Fire PreToolUse hook (treat the whole agent run as a "tool use")
        pre_results = self.hooks.fire("PreToolUse", {
            "tool": "AgentRun",
            "agent": self.agent_name,
            "task_id": task_id,
        })
        if any(r.get("decision") == "deny" for r in pre_results):
            self.tracer.record(self.agent_name, "hook_fire",
                               {"event": "PreToolUse", "decision": "deny"},
                               {"status": "denied"})
            print("  DENIED by PreToolUse hook")
            return {"status": "denied", "reason": "hook_denied", "run_id": run_id}

        # Record task start
        self.tracer.record(self.agent_name, "task_start",
                           {"task_id": task_id, "command": command},
                           {"status": "started"})

        # Execute
        start_time = time.time()
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "OATS_RUN_ID": run_id,
                     "OATS_AGENT": self.agent_name,
                     "OATS_TASK": task_id},
            )

            duration = time.time() - start_time
            success = result.returncode == 0

            # Record tool call
            self.tracer.record(
                self.agent_name, "tool_call",
                {"tool": "subprocess", "command": command},
                {
                    "status": "ok" if success else "failed",
                    "returncode": result.returncode,
                    "stdout_lines": result.stdout.count("\n"),
                    "stderr_lines": result.stderr.count("\n"),
                },
                duration_ms=int(duration * 1000),
            )

            # Estimate token usage (rough: 4 chars per token)
            output_chars = len(result.stdout) + len(result.stderr)
            est_tokens = output_chars // 4
            budget_result = self.budget.consume(self.agent_name, 0, est_tokens)

            if budget_result.get("warning"):
                self.tracer.record(self.agent_name, "budget_warn",
                                   {"message": budget_result["message"]}, {})
                print(f"  WARNING: {budget_result['message']}")

            # Record completion
            if success:
                self.tracer.record(self.agent_name, "task_complete",
                                   {"task_id": task_id},
                                   {"status": "completed", "duration_ms": int(duration * 1000)})
                self.trust.record_outcome(self.agent_name, task_id, reward=0.5)
                reward_label = "+0.5"
            else:
                self.tracer.record(self.agent_name, "task_fail",
                                   {"task_id": task_id},
                                   {"status": "failed", "returncode": result.returncode,
                                    "stderr": result.stderr[:500]})
                self.trust.record_outcome(self.agent_name, task_id, reward=-0.3)
                reward_label = "-0.3"

            # Fire PostToolUse hook
            self.hooks.fire("PostToolUse", {
                "tool": "AgentRun",
                "agent": self.agent_name,
                "task_id": task_id,
                "success": success,
            })

            # Fire TaskCompleted hook
            if success:
                self.hooks.fire("TaskCompleted", {
                    "agent": self.agent_name,
                    "task_id": task_id,
                })

            # Print summary
            status_icon = "OK" if success else "FAIL"
            trust_score = self.trust.agents[self.agent_name].score
            print(f"  Result:  [{status_icon}] exit={result.returncode} ({duration:.1f}s)")
            print(f"  Trust:   {trust_score:.3f} ({reward_label})")
            print(f"  Trace:   {run_id}")

            if not success and result.stderr:
                print(f"  Error:   {result.stderr[:200]}")

            return {
                "status": "completed" if success else "failed",
                "returncode": result.returncode,
                "duration_sec": round(duration, 1),
                "trust_score": trust_score,
                "run_id": run_id,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            self.tracer.record(self.agent_name, "error",
                               {"message": f"Timeout after {timeout}s"},
                               {"status": "failed"})
            self.trust.record_outcome(self.agent_name, task_id, reward=-0.5)
            print(f"  TIMEOUT after {timeout}s")
            return {"status": "timeout", "run_id": run_id}

        except Exception as e:
            self.tracer.record(self.agent_name, "error",
                               {"message": str(e)},
                               {"status": "failed"})
            self.trust.record_outcome(self.agent_name, task_id, reward=-0.5)
            print(f"  ERROR: {e}")
            return {"status": "error", "error": str(e), "run_id": run_id}


def main():
    if len(sys.argv) < 2:
        print("Agent Runner — execute agents with full instrumentation")
        print()
        print("Usage:")
        print("  runner.py <script> [args...]              # run a Python agent")
        print("  runner.py --cmd '<command>' [options]      # run any command")
        print()
        print("Options:")
        print("  --as <name>         Agent identity (default: script name)")
        print("  --task <id>         Task identifier")
        print("  --budget <tokens>   Token budget (default: 200000)")
        print("  --timeout <secs>    Max runtime (default: 300)")
        print("  --dry-run           Show config without executing")
        return

    # Split runner args from agent args at first non-flag argument
    runner_args = []
    agent_args = []
    hit_script = False
    for arg in sys.argv[1:]:
        if hit_script:
            agent_args.append(arg)
        elif arg.endswith(".py") or (not arg.startswith("--") and "." in arg):
            hit_script = True
            agent_args.append(arg)
        else:
            runner_args.append(arg)

    # Parse runner args
    agent_name = None
    task_id = None
    budget = 200_000
    timeout = 300
    dry_run = False
    command = []

    i = 0
    while i < len(runner_args):
        arg = runner_args[i]
        if arg == "--as" and i + 1 < len(runner_args):
            agent_name = runner_args[i + 1]; i += 2
        elif arg == "--task" and i + 1 < len(runner_args):
            task_id = runner_args[i + 1]; i += 2
        elif arg == "--budget" and i + 1 < len(runner_args):
            budget = int(runner_args[i + 1]); i += 2
        elif arg == "--timeout" and i + 1 < len(runner_args):
            timeout = int(runner_args[i + 1]); i += 2
        elif arg == "--dry-run":
            dry_run = True; i += 1
        elif arg == "--cmd" and i + 1 < len(runner_args):
            command = runner_args[i + 1].split(); i += 2
        else:
            i += 1

    # Build command from agent args
    if agent_args and not command:
        if agent_args[0].endswith(".py"):
            command = ["python3"] + agent_args
            if not agent_name:
                agent_name = Path(agent_args[0]).stem
        else:
            command = agent_args

    if not command:
        print("No command specified.")
        return

    if not agent_name:
        agent_name = "agent"

    if dry_run:
        print(f"Dry run:")
        print(f"  Agent:   {agent_name}")
        print(f"  Command: {' '.join(command)}")
        print(f"  Budget:  {budget:,} tokens")
        print(f"  Timeout: {timeout}s")
        print(f"  Task:    {task_id or 'auto-generated'}")
        return

    runner = AgentRunner(agent_name)
    result = runner.run(command, task_id=task_id, budget_limit=budget, timeout=timeout)

    sys.exit(0 if result.get("status") == "completed" else 1)


if __name__ == "__main__":
    main()
