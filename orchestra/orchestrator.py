#!/usr/bin/env python3
"""
Your Project Agent Orchestrator

Decomposes tasks into department assignments, routes them through S&QA review,
dispatches to specialist agents in parallel, and tracks everything.

Usage:
    python3 .orchestra/orchestrator.py "your task here"
    python3 .orchestra/orchestrator.py --simple "your task here"
"""

import asyncio
import curses
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent          # .orchestra/
PROJECT_DIR = BASE_DIR.parent
CONFIG_PATH = BASE_DIR / "config.json"
MASTER_CLAUDE_MD = BASE_DIR / "master" / "CLAUDE.md"
MEMORY_DIR = BASE_DIR / "memory"
PLAYBOOK_PATH = MEMORY_DIR / "playbook.md"
HISTORY_DIR = BASE_DIR / "history"
LOGS_DIR = BASE_DIR / "logs"
DEPTS_DIR = BASE_DIR / "departments"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    department: str
    status: str                     # done | blocked | error | vetoed
    output: str = ""
    files_changed: list[str] = field(default_factory=list)
    summary: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    duration_ms: int = 0
    is_error: bool = False
    raw_json: dict = field(default_factory=dict)


@dataclass
class Department:
    key: str
    name: str
    emoji: str
    model: str
    allowed_paths: list[str]
    description: str
    claude_md: str = ""
    memory: str = ""
    briefing: str = ""
    # Runtime state
    status: str = "idle"            # idle | reviewing | working | done | blocked | error | vetoed
    current_task: str = ""
    result: Optional[AgentResult] = None
    process: Optional[asyncio.subprocess.Process] = None


# ---------------------------------------------------------------------------
# Status icons
# ---------------------------------------------------------------------------

STATUS_ICONS = {
    "idle":      "\U0001f4a4",   # 💤
    "reviewing": "\U0001f50d",   # 🔍
    "working":   "\u26a1",       # ⚡
    "done":      "\u2705",       # ✅
    "blocked":   "\U0001f6ab",   # 🚫
    "error":     "\u274c",       # ❌
    "vetoed":    "\U0001f6b7",   # 🚷
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    def __init__(self) -> None:
        self.config: dict = {}
        self.departments: dict[str, Department] = {}
        self.run_id: str = ""
        self.total_cost: float = 0.0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.budget_cap: float = 5.0
        self.messages: list[str] = []
        self._load_config()

    # ---- initialisation ---------------------------------------------------

    def _load_config(self) -> None:
        with open(CONFIG_PATH) as f:
            self.config = json.load(f)
        self.budget_cap = self.config.get("budget_cap_usd", 5.0)
        models = self.config.get("models", {})

        for key, dept_cfg in self.config.get("departments", {}).items():
            claude_md = self._read_file(DEPTS_DIR / key / "CLAUDE.md")
            memory = self._read_file(MEMORY_DIR / f"{key}.md")
            dept = Department(
                key=key,
                name=dept_cfg["name"],
                emoji=dept_cfg.get("emoji", ""),
                model=models.get(key, "sonnet"),
                allowed_paths=dept_cfg.get("allowed_paths", []),
                description=dept_cfg.get("description", ""),
                claude_md=claude_md,
                memory=memory,
            )
            self.departments[key] = dept

    @staticmethod
    def _read_file(path: Path) -> str:
        try:
            return path.read_text()
        except FileNotFoundError:
            return ""

    # ---- system prompt builder -------------------------------------------

    def _build_system_prompt(self, dept: Department) -> str:
        parts: list[str] = []
        if dept.claude_md:
            parts.append(dept.claude_md)
        if dept.memory:
            parts.append(f"## Department Memory\n{dept.memory}")
        if dept.briefing:
            parts.append(f"## Current Briefing\n{dept.briefing}")

        # Load any skills from skills/ directory
        skills_dir = DEPTS_DIR / dept.key / "skills"
        if skills_dir.is_dir():
            for skill_file in sorted(skills_dir.glob("*.md")):
                parts.append(f"## Skill: {skill_file.stem}\n{skill_file.read_text()}")

        return "\n\n---\n\n".join(parts)

    # ---- agent spawning ---------------------------------------------------

    async def run_agent(
        self, dept_key: str, task: str, *, is_master: bool = False
    ) -> AgentResult:
        """Spawn a claude -p subprocess and parse the JSON result."""
        dept = self.departments.get(dept_key)
        model = "opus" if is_master else (dept.model if dept else "sonnet")
        system_prompt = ""

        if is_master:
            system_prompt = self._read_file(MASTER_CLAUDE_MD)
            playbook = self._read_file(PLAYBOOK_PATH)
            if playbook:
                system_prompt += f"\n\n## Playbook\n{playbook}"
        elif dept:
            system_prompt = self._build_system_prompt(dept)

        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--model", model,
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--tools", "Bash,Edit,Read,Glob,Grep,Write",
        ]
        if system_prompt:
            cmd += ["--system-prompt", system_prompt]
        cmd.append(task)

        dept_label = dept_key if not is_master else "master"
        log_dir = LOGS_DIR / self.run_id
        log_dir.mkdir(parents=True, exist_ok=True)

        result = AgentResult(department=dept_label, status="error")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_DIR),
            )
            if dept and not is_master:
                dept.process = proc

            stdout_bytes, stderr_bytes = await proc.communicate()
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Write raw output log
            log_path = log_dir / f"{dept_label}.json"
            log_path.write_text(stdout or stderr)

            if proc.returncode != 0 and not stdout.strip():
                result.output = stderr or f"Process exited with code {proc.returncode}"
                result.is_error = True
                return result

            # Parse the outer JSON envelope
            envelope = json.loads(stdout)

            result.cost_usd = float(envelope.get("cost_usd", 0) or envelope.get("total_cost_usd", 0) or 0)
            usage = envelope.get("usage", {})
            result.input_tokens = int(usage.get("input_tokens", 0))
            result.output_tokens = int(usage.get("output_tokens", 0))
            result.cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))
            result.duration_ms = int(envelope.get("duration_ms", 0))
            result.is_error = bool(envelope.get("is_error", False))
            result.raw_json = envelope

            # Track totals
            self.total_cost += result.cost_usd
            self.total_input_tokens += result.input_tokens + result.cache_read_tokens
            self.total_output_tokens += result.output_tokens

            # Extract the result text
            agent_text = envelope.get("result", "")
            result.output = agent_text

            if result.is_error:
                result.status = "error"
                return result

            # Try to parse agent_text as JSON for structured responses
            try:
                parsed = json.loads(agent_text)
                result.status = parsed.get("status", "done")
                result.files_changed = parsed.get("files_changed", [])
                result.summary = parsed.get("summary", agent_text[:200])
            except (json.JSONDecodeError, TypeError):
                # Agent returned plain text — that's fine
                result.status = "done"
                result.summary = agent_text[:300] if agent_text else "(no output)"

        except json.JSONDecodeError as e:
            result.output = f"JSON parse error: {e}\nRaw: {stdout[:500] if 'stdout' in dir() else '(no output)'}"
            result.is_error = True
        except FileNotFoundError:
            result.output = "Error: 'claude' CLI not found in PATH"
            result.is_error = True
        except Exception as e:
            result.output = f"Agent error: {type(e).__name__}: {e}"
            result.is_error = True

        return result

    # ---- master decomposition --------------------------------------------

    async def decompose_task(self, task: str, dashboard: Any) -> dict:
        """Use the master agent to decompose a task into department assignments."""
        dept_names = ", ".join(
            f"{d.key} ({d.name})" for d in self.departments.values()
        )
        prompt = f"""Decompose this task into department assignments.

Available departments: {dept_names}

Task: {task}

Respond ONLY with valid JSON in this exact format:
{{
  "assignments": {{
    "dept_key": "specific task description for that department"
  }},
  "parallel_groups": [["dept1", "dept2"], ["dept3"]],
  "reasoning": "brief explanation of decomposition"
}}

Rules:
- Only assign to departments that are needed. Not every task needs all departments.
- parallel_groups defines execution order — departments in the same group run concurrently.
- Be specific in task descriptions — include file paths and exact scope.
- If the task is simple enough for one department, assign to just one.
- The strategy department is handled automatically — do NOT include it in assignments."""

        dashboard.log("Master agent decomposing task...")
        result = await self.run_agent("master", prompt, is_master=True)
        dashboard.log(f"Master agent done (${result.cost_usd:.4f})")

        if result.is_error:
            dashboard.log(f"ERROR: Master failed — {result.output[:200]}")
            return {}

        # Parse the decomposition
        text = result.output.strip()
        # Try to extract JSON from the response (agent might wrap it in markdown)
        try:
            decomposition = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON block in the text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    decomposition = json.loads(text[start:end])
                except json.JSONDecodeError:
                    dashboard.log("ERROR: Could not parse master's decomposition")
                    return {}
            else:
                dashboard.log("ERROR: No JSON found in master's response")
                return {}

        return decomposition

    # ---- S&QA gate --------------------------------------------------------

    async def run_strategy_review(
        self, task: str, assignments: dict, dashboard: Any
    ) -> dict:
        """Send all assignments to Strategy & QA for review."""
        strategy_dept = self.departments.get("strategy")
        if not strategy_dept:
            dashboard.log("WARNING: No strategy department, skipping review")
            return {"verdict": "approve", "approved_tasks": assignments}

        strategy_dept.status = "reviewing"
        strategy_dept.current_task = "Reviewing all assignments"
        dashboard.draw()

        playbook = self._read_file(PLAYBOOK_PATH)
        prompt = f"""Review these proposed department assignments for Your Project.

## Original Task
{task}

## Proposed Assignments
{json.dumps(assignments, indent=2)}

## Playbook (past lessons)
{playbook}

Respond ONLY with valid JSON:
{{
  "verdict": "approve|challenge|veto",
  "reasoning": "your analysis",
  "approved_tasks": {{"dept_key": "approved/modified task or null if vetoed"}},
  "conditions": ["any conditions"],
  "risk_flags": ["concerns"],
  "alternative": "suggested alternative if challenging or vetoing"
}}"""

        dashboard.log("S&QA reviewing assignments...")
        result = await self.run_agent("strategy", prompt)
        strategy_dept.result = result

        if result.is_error:
            dashboard.log(f"S&QA error: {result.output[:200]}")
            strategy_dept.status = "error"
            dashboard.draw()
            return {"verdict": "error", "reasoning": result.output[:200]}

        # Parse S&QA response
        text = result.output.strip()
        try:
            review = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    review = json.loads(text[start:end])
                except json.JSONDecodeError:
                    dashboard.log("WARNING: Could not parse S&QA response, auto-approving")
                    strategy_dept.status = "done"
                    dashboard.draw()
                    return {"verdict": "approve", "approved_tasks": assignments}
            else:
                dashboard.log("WARNING: No JSON in S&QA response, auto-approving")
                strategy_dept.status = "done"
                dashboard.draw()
                return {"verdict": "approve", "approved_tasks": assignments}

        verdict = review.get("verdict", "approve")
        dashboard.log(f"S&QA verdict: {verdict} (${result.cost_usd:.4f})")

        if review.get("risk_flags"):
            for flag in review["risk_flags"]:
                dashboard.log(f"  Risk: {flag}")
        if review.get("conditions"):
            for cond in review["conditions"]:
                dashboard.log(f"  Condition: {cond}")

        strategy_dept.status = "done" if verdict != "error" else "error"
        dashboard.draw()
        return review

    # ---- briefing / memory ------------------------------------------------

    def write_briefing(self, dept_key: str, text: str) -> None:
        """Write a briefing.md to the department's directory."""
        dept = self.departments.get(dept_key)
        if dept:
            dept.briefing = text
        briefing_path = DEPTS_DIR / dept_key / "briefing.md"
        briefing_path.parent.mkdir(parents=True, exist_ok=True)
        briefing_path.write_text(f"# Briefing — {datetime.now():%Y-%m-%d %H:%M}\n\n{text}\n")

    def update_memory(self, dept_key: str, content: str) -> None:
        """Append a timestamped entry to the department's memory file."""
        mem_path = MEMORY_DIR / f"{dept_key}.md"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## {timestamp}\n{content}\n"
        with open(mem_path, "a") as f:
            f.write(entry)

    def update_playbook(self, entry: str) -> None:
        """Append to the master playbook."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(PLAYBOOK_PATH, "a") as f:
            f.write(f"\n## {timestamp}\n{entry}\n")

    def create_skill(self, dept_key: str, name: str, content: str) -> None:
        """Write a skill .md file to the department's skills/ directory."""
        skills_dir = DEPTS_DIR / dept_key / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skills_dir / f"{name}.md"
        skill_path.write_text(content)

    # ---- history ----------------------------------------------------------

    def save_history(self, task: str, decomposition: dict, review: dict,
                     results: dict[str, AgentResult]) -> None:
        """Save the full run to history/ as JSON."""
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        history = {
            "run_id": self.run_id,
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "decomposition": decomposition,
            "strategy_review": review,
            "total_cost_usd": round(self.total_cost, 6),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "budget_cap_usd": self.budget_cap,
            "results": {},
        }
        for dept_key, r in results.items():
            history["results"][dept_key] = {
                "status": r.status,
                "summary": r.summary,
                "files_changed": r.files_changed,
                "cost_usd": round(r.cost_usd, 6),
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read_tokens": r.cache_read_tokens,
                "duration_ms": r.duration_ms,
                "is_error": r.is_error,
            }

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = HISTORY_DIR / f"{ts}_{self.run_id[:8]}.json"
        path.write_text(json.dumps(history, indent=2))

    # ---- budget check -----------------------------------------------------

    def budget_exceeded(self) -> bool:
        return self.total_cost >= self.budget_cap

    # ---- dispatch a single department -------------------------------------

    async def _dispatch_department(
        self, dept_key: str, task: str, dashboard: Any
    ) -> AgentResult:
        dept = self.departments.get(dept_key)
        if not dept:
            return AgentResult(department=dept_key, status="error",
                               output=f"Unknown department: {dept_key}", is_error=True)

        dept.status = "working"
        dept.current_task = task[:80]
        dashboard.draw()
        dashboard.log(f"{dept.emoji} {dept.name} starting...")

        result = await self.run_agent(dept_key, task)
        dept.result = result

        if result.is_error:
            dept.status = "error"
            dashboard.log(f"{dept.emoji} {dept.name} ERROR: {result.output[:120]}")
        elif result.status == "blocked":
            dept.status = "blocked"
            dashboard.log(f"{dept.emoji} {dept.name} BLOCKED: {result.summary[:120]}")
        else:
            dept.status = "done"
            dashboard.log(f"{dept.emoji} {dept.name} done (${result.cost_usd:.4f})")

        dashboard.draw()
        return result

    # ---- main orchestration loop ------------------------------------------

    async def run(self, task: str, dashboard: Any) -> dict[str, AgentResult]:
        """Full orchestration: decompose -> S&QA -> dispatch -> collect -> memory -> history."""
        self.run_id = uuid.uuid4().hex[:12]
        results: dict[str, AgentResult] = {}

        dashboard.log(f"Run {self.run_id} | Budget: ${self.budget_cap:.2f}")
        dashboard.log(f"Task: {task}")
        dashboard.draw()

        # --- Step 1: Master decomposes the task ---
        decomposition = await self.decompose_task(task, dashboard)
        if not decomposition:
            dashboard.log("ABORT: Master could not decompose task")
            return results

        assignments = decomposition.get("assignments", {})
        parallel_groups = decomposition.get("parallel_groups", [list(assignments.keys())])
        reasoning = decomposition.get("reasoning", "")

        dashboard.log(f"Decomposition: {len(assignments)} departments")
        if reasoning:
            dashboard.log(f"Reasoning: {reasoning[:150]}")
        for dk, t in assignments.items():
            dashboard.log(f"  -> {dk}: {t[:80]}")
        dashboard.draw()

        if self.budget_exceeded():
            dashboard.log("ABORT: Budget exceeded after decomposition")
            return results

        # --- Step 2: Strategy & QA review ---
        review = await self.run_strategy_review(task, assignments, dashboard)
        verdict = review.get("verdict", "error")

        if verdict == "veto":
            dashboard.log("VETOED by Strategy & QA")
            if review.get("alternative"):
                dashboard.log(f"Alternative: {review['alternative']}")
            # Record veto in playbook
            self.update_playbook(
                f"Task VETOED: {task}\nReason: {review.get('reasoning', 'No reason given')}"
            )
            # Mark all departments as vetoed
            for dk in assignments:
                dept = self.departments.get(dk)
                if dept:
                    dept.status = "vetoed"
            dashboard.draw()
            self.save_history(task, decomposition, review, results)
            return results

        # Use S&QA's approved/modified tasks
        if verdict == "challenge":
            dashboard.log("CHALLENGED — using S&QA's modified assignments")
            approved_tasks = review.get("approved_tasks", assignments)
            # Filter out nulls (vetoed individual tasks)
            assignments = {k: v for k, v in approved_tasks.items() if v}
            # Rebuild parallel groups to only include approved departments
            approved_keys = set(assignments.keys())
            parallel_groups = [
                [dk for dk in group if dk in approved_keys]
                for group in parallel_groups
            ]
            parallel_groups = [g for g in parallel_groups if g]
        elif verdict == "approve":
            approved_tasks = review.get("approved_tasks", assignments)
            if approved_tasks:
                assignments = {k: v for k, v in approved_tasks.items() if v}

        if not assignments:
            dashboard.log("No assignments remaining after S&QA review")
            self.save_history(task, decomposition, review, results)
            return results

        if self.budget_exceeded():
            dashboard.log("ABORT: Budget exceeded after S&QA review")
            self.save_history(task, decomposition, review, results)
            return results

        # --- Step 3: Write briefings ---
        for dk, dept_task in assignments.items():
            conditions = review.get("conditions", [])
            cond_text = "\n".join(f"- {c}" for c in conditions) if conditions else "None"
            briefing = (
                f"## Task\n{dept_task}\n\n"
                f"## S&QA Conditions\n{cond_text}\n\n"
                f"## Risk Flags\n"
                + ("\n".join(f"- {f}" for f in review.get("risk_flags", [])) or "None")
            )
            self.write_briefing(dk, briefing)
        dashboard.log("Briefings written")
        dashboard.draw()

        # --- Step 4: Dispatch parallel groups ---
        # If parallel_groups is missing or doesn't cover all assignments, fall back
        assigned_in_groups = set()
        for g in parallel_groups:
            assigned_in_groups.update(g)
        missing = set(assignments.keys()) - assigned_in_groups
        if missing:
            parallel_groups.append(list(missing))

        for group_idx, group in enumerate(parallel_groups):
            if self.budget_exceeded():
                dashboard.log(f"BUDGET CAP — skipping group {group_idx + 1}")
                for dk in group:
                    dept = self.departments.get(dk)
                    if dept:
                        dept.status = "blocked"
                        dept.current_task = "Budget exceeded"
                dashboard.draw()
                break

            dashboard.log(f"--- Group {group_idx + 1}/{len(parallel_groups)}: {', '.join(group)} ---")
            dashboard.draw()

            # Dispatch concurrently within group
            coros = []
            for dk in group:
                if dk in assignments:
                    coros.append(self._dispatch_department(dk, assignments[dk], dashboard))
            group_results = await asyncio.gather(*coros, return_exceptions=True)

            for i, dk in enumerate(group):
                if dk not in assignments:
                    continue
                gr = group_results[i] if i < len(group_results) else None
                if isinstance(gr, Exception):
                    results[dk] = AgentResult(
                        department=dk, status="error",
                        output=str(gr), is_error=True
                    )
                    dept = self.departments.get(dk)
                    if dept:
                        dept.status = "error"
                elif isinstance(gr, AgentResult):
                    results[dk] = gr

            dashboard.draw()

        # --- Step 5: Update memory ---
        for dk, r in results.items():
            if r.status == "done":
                self.update_memory(dk, f"Task: {assignments.get(dk, '?')}\nResult: {r.summary[:200]}")
            elif r.is_error:
                self.update_memory(dk, f"ERROR on task: {assignments.get(dk, '?')}\n{r.output[:200]}")

        # Playbook entry
        summary_lines = []
        for dk, r in results.items():
            emoji = self.departments[dk].emoji if dk in self.departments else ""
            summary_lines.append(f"- {emoji} {dk}: {r.status} (${r.cost_usd:.4f})")
        playbook_entry = (
            f"Task: {task}\n"
            f"Verdict: {verdict}\n"
            f"Total cost: ${self.total_cost:.4f}\n"
            f"Results:\n" + "\n".join(summary_lines)
        )
        self.update_playbook(playbook_entry)

        # --- Step 6: Save history ---
        self.save_history(task, decomposition, review, results)

        dashboard.log(f"=== Run complete | ${self.total_cost:.4f} spent ===")
        dashboard.draw()
        return results


# ---------------------------------------------------------------------------
# Curses Dashboard
# ---------------------------------------------------------------------------

class Dashboard:
    def __init__(self, screen: Any, orchestrator: Orchestrator, task: str) -> None:
        self.screen = screen
        self.orch = orchestrator
        self.task = task
        self.messages: list[str] = []
        self.max_messages = 200
        self._setup_screen()

    def _setup_screen(self) -> None:
        curses.curs_set(0)
        self.screen.nodelay(True)
        self.screen.timeout(200)
        curses.start_color()
        curses.use_default_colors()
        # Color pairs
        curses.init_pair(1, curses.COLOR_GREEN, -1)    # done
        curses.init_pair(2, curses.COLOR_YELLOW, -1)    # working
        curses.init_pair(3, curses.COLOR_RED, -1)       # error
        curses.init_pair(4, curses.COLOR_CYAN, -1)      # header
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)   # reviewing
        curses.init_pair(6, curses.COLOR_WHITE, -1)     # idle

    def log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.messages.append(f"[{ts}] {msg}")
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
        self.orch.messages = self.messages

    def draw(self) -> None:
        try:
            self.screen.erase()
            max_y, max_x = self.screen.getmaxyx()
            if max_y < 10 or max_x < 40:
                self.screen.addstr(0, 0, "Terminal too small")
                self.screen.refresh()
                return

            row = 0

            # --- Header ---
            header = f" Your Project Orchestrator "
            self.screen.addstr(row, 0, header.center(max_x, "=")[:max_x - 1],
                               curses.color_pair(4) | curses.A_BOLD)
            row += 1

            # Task line
            task_line = f"Task: {self.task[:max_x - 8]}"
            self.screen.addstr(row, 0, task_line[:max_x - 1])
            row += 1

            # --- Budget bar ---
            spent = self.orch.total_cost
            cap = self.orch.budget_cap
            pct = min(spent / cap, 1.0) if cap > 0 else 0
            bar_width = max(max_x - 45, 10)
            filled = int(pct * bar_width)
            bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
            budget_line = f"Budget: ${spent:.4f}/${cap:.2f} [{bar}] In:{self.orch.total_input_tokens} Out:{self.orch.total_output_tokens}"
            color = curses.color_pair(3) if pct > 0.8 else (curses.color_pair(2) if pct > 0.5 else curses.color_pair(1))
            self.screen.addstr(row, 0, budget_line[:max_x - 1], color)
            row += 1

            # Separator
            self.screen.addstr(row, 0, "\u2500" * min(max_x - 1, 120))
            row += 1

            # --- Department rows ---
            status_colors = {
                "idle": 6, "reviewing": 5, "working": 2,
                "done": 1, "blocked": 3, "error": 3, "vetoed": 3,
            }
            for dept in self.orch.departments.values():
                if row >= max_y - 6:
                    break
                icon = STATUS_ICONS.get(dept.status, "?")
                cost_str = f"${dept.result.cost_usd:.4f}" if dept.result else "$0.0000"
                task_snippet = dept.current_task[:max(max_x - 50, 10)] if dept.current_task else ""
                line = f" {dept.emoji} {dept.name:<14} {icon} {dept.status:<10} {cost_str:>9}  {task_snippet}"
                pair = status_colors.get(dept.status, 6)
                self.screen.addstr(row, 0, line[:max_x - 1], curses.color_pair(pair))
                row += 1

            # Separator
            if row < max_y - 2:
                self.screen.addstr(row, 0, "\u2500" * min(max_x - 1, 120))
                row += 1

            # --- Message log ---
            log_space = max_y - row - 1
            if log_space > 0:
                visible = self.messages[-log_space:]
                for msg in visible:
                    if row >= max_y - 1:
                        break
                    self.screen.addstr(row, 0, msg[:max_x - 1])
                    row += 1

            # Footer
            if row < max_y:
                footer = " Press 'q' to exit "
                self.screen.addstr(max_y - 1, 0, footer.center(max_x, "\u2500")[:max_x - 1],
                                   curses.color_pair(4))

            self.screen.refresh()
        except curses.error:
            # Terminal resize or drawing out of bounds — skip this frame
            pass

    async def wait_for_exit(self) -> None:
        """After orchestration is complete, wait for user to press 'q'."""
        self.log("Press 'q' to exit")
        self.draw()
        while True:
            try:
                key = self.screen.getch()
                if key == ord("q") or key == ord("Q"):
                    break
            except curses.error:
                pass
            await asyncio.sleep(0.2)
            self.draw()


# ---------------------------------------------------------------------------
# Simple (no-curses) dashboard
# ---------------------------------------------------------------------------

class SimpleDashboard:
    def __init__(self, orchestrator: Orchestrator, task: str) -> None:
        self.orch = orchestrator
        self.task = task

    def log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        self.orch.messages.append(line)

    def draw(self) -> None:
        # In simple mode, draw is a no-op — messages print immediately via log()
        pass


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

async def run_with_curses(screen: Any, task: str) -> None:
    orch = Orchestrator()
    dashboard = Dashboard(screen, orch, task)
    dashboard.draw()
    await orch.run(task, dashboard)
    await dashboard.wait_for_exit()


async def run_simple(task: str) -> None:
    orch = Orchestrator()
    dashboard = SimpleDashboard(orch, task)
    print(f"{'=' * 60}")
    print(f"  Your Project Orchestrator (simple mode)")
    print(f"  Task: {task}")
    print(f"{'=' * 60}", flush=True)
    results = await orch.run(task, dashboard)
    print(f"\n{'=' * 60}")
    print(f"  RESULTS")
    print(f"{'=' * 60}")
    for dk, r in results.items():
        dept = orch.departments.get(dk)
        emoji = dept.emoji if dept else ""
        print(f"  {emoji} {dk}: {r.status} | ${r.cost_usd:.4f} | {r.summary[:100]}")
    print(f"\n  Total: ${orch.total_cost:.4f} | In: {orch.total_input_tokens} | Out: {orch.total_output_tokens}")
    print(f"{'=' * 60}", flush=True)


def main() -> None:
    args = sys.argv[1:]
    simple_mode = False
    task = ""

    if "--simple" in args:
        simple_mode = True
        args.remove("--simple")

    if not args:
        print("Usage: python3 .orchestra/orchestrator.py [--simple] \"your task here\"")
        sys.exit(1)

    task = " ".join(args)

    if simple_mode:
        asyncio.run(run_simple(task))
    else:
        # curses.wrapper handles init/cleanup, but we need asyncio inside it
        def curses_main(screen: Any) -> None:
            asyncio.run(run_with_curses(screen, task))
        try:
            curses.wrapper(curses_main)
        except KeyboardInterrupt:
            print("\nInterrupted.")


if __name__ == "__main__":
    main()
