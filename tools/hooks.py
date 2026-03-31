#!/usr/bin/env python3
"""Hooks — lifecycle event automation for OATS agents.

Inspired by Claude Code's hooks system. Deterministic lifecycle events
that fire before/after tool use, on task completion, session start/end,
and agent stop. Three execution types: command (shell), prompt (LLM),
and agent (subagent verification).

Key design from Claude Code:
- PreToolUse is the ONLY blocking hook (exit 2 = deny)
- Hooks run in parallel; identical commands auto-deduplicate
- Matchers filter by tool name, file path, or event source
- Stop hooks enforce quality gates (must pass before agent stops)

Lifecycle events:
    PreToolUse      — before a tool executes (can block with exit 2)
    PostToolUse     — after a tool completes
    TaskCreated     — when a new task is added
    TaskCompleted   — when a task is marked done (can block)
    SessionStart    — when an agent session begins
    SessionEnd      — when an agent session ends
    Stop            — before agent stops (quality gate)

Usage:
    # Load hooks from config
    engine = HookEngine.from_config(".oats/hooks.json")

    # Fire a hook
    results = engine.fire("PreToolUse", context={"tool": "Edit", "file": "main.py"})

    # Check if blocked
    if any(r["decision"] == "deny" for r in results):
        print("Tool use denied by hook")

Config format (.oats/hooks.json):
    {
      "PreToolUse": [
        {
          "matcher": {"tool": "Edit|Write"},
          "hooks": [
            {"type": "command", "command": "python3 .oats/hooks/lint-check.py {file}"},
            {"type": "command", "command": "grep -l 'TODO' {file} && exit 2 || exit 0"}
          ]
        }
      ],
      "Stop": [
        {
          "hooks": [
            {"type": "command", "command": "python3 smoke_test.py"},
            {"type": "command", "command": "python3 -m compileall src/ -q"}
          ]
        }
      ],
      "TaskCompleted": [
        {
          "matcher": {"owner": "backend"},
          "hooks": [
            {"type": "command", "command": "python3 agents/verification.py --commit HEAD"}
          ]
        }
      ]
    }
"""

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional


# Events that can BLOCK (exit code 2 = deny)
BLOCKING_EVENTS = {"PreToolUse", "TaskCompleted", "Stop"}

# All valid lifecycle events
VALID_EVENTS = {
    "PreToolUse", "PostToolUse",
    "TaskCreated", "TaskCompleted",
    "SessionStart", "SessionEnd",
    "Stop",
}


class HookResult:
    """Result from a single hook execution."""

    def __init__(self, hook_type: str, command: str, exit_code: int,
                 stdout: str = "", stderr: str = "", decision: str = "allow",
                 duration_ms: int = 0):
        self.hook_type = hook_type
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.decision = decision
        self.duration_ms = duration_ms

    def to_dict(self) -> dict:
        return {
            "hook_type": self.hook_type,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:500],
            "stderr": self.stderr[:500],
            "decision": self.decision,
            "duration_ms": self.duration_ms,
        }


class HookEngine:
    """Execute lifecycle hooks based on configuration."""

    def __init__(self, config: dict, project_dir: str = "."):
        self.config = config
        self.project_dir = Path(project_dir)
        self.history: list = []

    @classmethod
    def from_config(cls, config_path: str, project_dir: str = ".") -> "HookEngine":
        """Load hooks from a JSON config file."""
        path = Path(config_path)
        if path.exists():
            config = json.loads(path.read_text())
        else:
            config = {}
        return cls(config, project_dir)

    @classmethod
    def from_dict(cls, config: dict, project_dir: str = ".") -> "HookEngine":
        """Create from a dictionary."""
        return cls(config, project_dir)

    def fire(self, event: str, context: Optional[dict] = None) -> list:
        """Fire all hooks for a lifecycle event.

        Args:
            event: Lifecycle event name (e.g., "PreToolUse")
            context: Event context (tool name, file path, task info, etc.)

        Returns:
            List of HookResult dicts. Check for decision="deny" on blocking events.
        """
        if event not in VALID_EVENTS:
            raise ValueError(f"Unknown event: {event}. Valid: {VALID_EVENTS}")

        context = context or {}
        event_hooks = self.config.get(event, [])
        results = []

        for group in event_hooks:
            # Check matcher
            matcher = group.get("matcher", {})
            if not self._matches(matcher, context):
                continue

            # Collect hooks to run
            hooks = group.get("hooks", [])

            # Deduplicate identical commands
            seen_commands = set()
            unique_hooks = []
            for hook in hooks:
                cmd = hook.get("command", "")
                if cmd not in seen_commands:
                    seen_commands.add(cmd)
                    unique_hooks.append(hook)

            # Run hooks in parallel
            group_results = self._run_parallel(unique_hooks, context, event)
            results.extend(group_results)

            # For blocking events, stop on first deny
            if event in BLOCKING_EVENTS:
                if any(r["decision"] == "deny" for r in group_results):
                    break

        # Log
        self.history.append({
            "event": event,
            "context": context,
            "results": results,
            "timestamp": datetime.now().isoformat(),
        })

        return results

    def _matches(self, matcher: dict, context: dict) -> bool:
        """Check if context matches the hook matcher."""
        if not matcher:
            return True  # No matcher = match everything

        for key, pattern in matcher.items():
            value = context.get(key, "")
            if not value:
                return False
            # Support regex patterns (e.g., "Edit|Write")
            if not re.match(pattern, str(value)):
                return False

        return True

    def _run_parallel(self, hooks: list, context: dict, event: str) -> list:
        """Run hooks in parallel, collect results."""
        results = []

        if not hooks:
            return results

        with ThreadPoolExecutor(max_workers=min(len(hooks), 4)) as executor:
            futures = {}
            for hook in hooks:
                hook_type = hook.get("type", "command")
                if hook_type == "command":
                    future = executor.submit(self._run_command, hook, context, event)
                    futures[future] = hook
                # prompt and agent types would integrate with LLM — stub for now
                elif hook_type in ("prompt", "agent"):
                    results.append({
                        "hook_type": hook_type,
                        "command": hook.get("prompt", hook.get("command", "")),
                        "exit_code": 0,
                        "stdout": f"[{hook_type} hooks require LLM integration]",
                        "stderr": "",
                        "decision": "allow",
                        "duration_ms": 0,
                    })

            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result.to_dict())
                except Exception as e:
                    hook = futures[future]
                    results.append({
                        "hook_type": "command",
                        "command": hook.get("command", ""),
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": str(e),
                        "decision": "allow",  # Errors don't block by default
                        "duration_ms": 0,
                    })

        return results

    def _run_command(self, hook: dict, context: dict, event: str) -> HookResult:
        """Execute a command hook."""
        command = hook.get("command", "")

        # Template substitution: {file}, {tool}, {task_id}, etc.
        for key, value in context.items():
            command = command.replace(f"{{{key}}}", str(value))

        timeout = hook.get("timeout", 30)
        start = datetime.now()

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=self.project_dir,
                env={**os.environ, "OATS_EVENT": event,
                     **{f"OATS_{k.upper()}": str(v) for k, v in context.items()}}
            )

            duration = int((datetime.now() - start).total_seconds() * 1000)

            # Determine decision
            decision = "allow"
            if event in BLOCKING_EVENTS and result.returncode == 2:
                decision = "deny"

            return HookResult(
                hook_type="command",
                command=command,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                decision=decision,
                duration_ms=duration,
            )

        except subprocess.TimeoutExpired:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return HookResult(
                hook_type="command",
                command=command,
                exit_code=-1,
                stderr=f"Timeout after {timeout}s",
                decision="allow",  # Timeouts don't block
                duration_ms=duration,
            )

    def get_history(self, event: Optional[str] = None, limit: int = 20) -> list:
        """Get hook execution history."""
        history = self.history
        if event:
            history = [h for h in history if h["event"] == event]
        return history[-limit:]

    def save_history(self, path: str = ".oats/hook_history.json"):
        """Persist hook history to disk."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Keep last 200 entries
        out.write_text(json.dumps(self.history[-200:], indent=2))

    def validate_config(self) -> list:
        """Validate the hooks configuration."""
        errors = []

        for event, groups in self.config.items():
            if event not in VALID_EVENTS:
                errors.append(f"Unknown event: {event}")
                continue

            if not isinstance(groups, list):
                errors.append(f"{event}: expected list of hook groups")
                continue

            for i, group in enumerate(groups):
                hooks = group.get("hooks", [])
                if not hooks:
                    errors.append(f"{event}[{i}]: no hooks defined")

                for j, hook in enumerate(hooks):
                    hook_type = hook.get("type", "command")
                    if hook_type not in ("command", "prompt", "agent"):
                        errors.append(f"{event}[{i}].hooks[{j}]: unknown type '{hook_type}'")
                    if hook_type == "command" and not hook.get("command"):
                        errors.append(f"{event}[{i}].hooks[{j}]: missing command")

        return errors


def init_default_config(path: str = ".oats/hooks.json"):
    """Create a starter hooks config."""
    default = {
        "PreToolUse": [
            {
                "matcher": {"tool": "Edit|Write"},
                "hooks": [
                    {
                        "type": "command",
                        "command": "echo 'Pre-edit hook: {file}'",
                        "timeout": 5,
                    }
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "echo 'Stop hook: verifying before exit'",
                    }
                ],
            }
        ],
        "TaskCompleted": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "echo 'Task {task_id} completed by {owner}'",
                    }
                ],
            }
        ],
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "echo 'Session started at $(date)'",
                    }
                ],
            }
        ],
    }

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(default, indent=2))
    print(f"Default hooks config written to {path}")
    print(f"Events: {', '.join(default.keys())}")


def main():
    """CLI for managing hooks."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  hooks.py init                          # create default config")
        print("  hooks.py validate [config]             # validate config")
        print("  hooks.py fire <event> [key=value ...]  # fire an event")
        print("  hooks.py list                          # list configured hooks")
        print("  hooks.py history [event]               # show execution history")
        print()
        print(f"Events: {', '.join(sorted(VALID_EVENTS))}")
        print(f"Blocking: {', '.join(sorted(BLOCKING_EVENTS))}")
        return

    cmd = sys.argv[1]

    if cmd == "init":
        config_path = sys.argv[2] if len(sys.argv) > 2 else ".oats/hooks.json"
        init_default_config(config_path)

    elif cmd == "validate":
        config_path = sys.argv[2] if len(sys.argv) > 2 else ".oats/hooks.json"
        engine = HookEngine.from_config(config_path)
        errors = engine.validate_config()
        if errors:
            print(f"Validation errors ({len(errors)}):")
            for e in errors:
                print(f"  - {e}")
        else:
            events = list(engine.config.keys())
            total = sum(len(g.get("hooks", [])) for groups in engine.config.values() for g in groups)
            print(f"Config valid: {len(events)} events, {total} hooks")

    elif cmd == "fire":
        if len(sys.argv) < 3:
            print("Usage: hooks.py fire <event> [key=value ...]")
            return

        event = sys.argv[2]
        context = {}
        for arg in sys.argv[3:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                context[k] = v

        engine = HookEngine.from_config(".oats/hooks.json")
        results = engine.fire(event, context)

        for r in results:
            icon = "DENY" if r["decision"] == "deny" else "OK"
            print(f"  [{icon}] {r['command'][:60]} (exit={r['exit_code']}, {r['duration_ms']}ms)")
            if r["stdout"].strip():
                print(f"        stdout: {r['stdout'].strip()[:100]}")
            if r["stderr"].strip():
                print(f"        stderr: {r['stderr'].strip()[:100]}")

        denied = sum(1 for r in results if r["decision"] == "deny")
        if denied:
            print(f"\n{denied} hook(s) DENIED this action.")
            sys.exit(2)

    elif cmd == "list":
        engine = HookEngine.from_config(".oats/hooks.json")
        if not engine.config:
            print("No hooks configured. Run 'hooks.py init' to get started.")
            return

        for event, groups in engine.config.items():
            blocking = " [BLOCKING]" if event in BLOCKING_EVENTS else ""
            print(f"\n{event}{blocking}:")
            for group in groups:
                matcher = group.get("matcher", {})
                if matcher:
                    print(f"  matcher: {matcher}")
                for hook in group.get("hooks", []):
                    t = hook.get("type", "command")
                    cmd_str = hook.get("command", hook.get("prompt", ""))
                    print(f"    [{t}] {cmd_str[:70]}")

    elif cmd == "history":
        history_path = Path(".oats/hook_history.json")
        if not history_path.exists():
            print("No history yet.")
            return

        history = json.loads(history_path.read_text())
        event_filter = sys.argv[2] if len(sys.argv) > 2 else None

        if event_filter:
            history = [h for h in history if h["event"] == event_filter]

        for entry in history[-20:]:
            results = entry.get("results", [])
            denied = sum(1 for r in results if r.get("decision") == "deny")
            status = f"DENIED({denied})" if denied else "OK"
            print(f"  {entry['timestamp'][:19]} {entry['event']:20s} [{status}] "
                  f"({len(results)} hooks)")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
