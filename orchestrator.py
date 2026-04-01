#!/usr/bin/env python3
"""OATS Orchestrator — the glue that ties agents, tools, hooks, and memory together.

This is the main entry point for running OATS as an autonomous system.
It coordinates:
- Team management (team_coordinator)
- Lifecycle hooks (hooks engine)
- Memory context (memory scoper)
- Skill loading (skill loader)
- Agent dispatch and monitoring

Two modes:
1. Simple: dispatch a single task to an agent
2. Persistent: run a team of agents continuously (tmux/screen)

Usage:
    # Simple dispatch
    python3 orchestrator.py run "Fix the broken auth endpoint"

    # Run with a specific agent
    python3 orchestrator.py run --agent backend "Add rate limiting to /api/search"

    # Start persistent team
    python3 orchestrator.py team start "feature-x" "Build the new dashboard"

    # Team status
    python3 orchestrator.py team status "feature-x"

    # Self-improvement loop (Karpathy autoresearch pattern)
    python3 orchestrator.py improve --target skills

    # Health check (memory + hooks + skills)
    python3 orchestrator.py health
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent))

from tools.hooks import HookEngine, VALID_EVENTS
from tools.memory_scoper import MemoryScoper
from tools.team_coordinator import Team, TEAMS_DIR
from tools.skill_loader import SkillLoader
from tools.trust import TrustEngine
from tools.budget import BudgetTracker
from tools.blackboard import Blackboard, BOARD_DIR
from tools.think import ThoughtEngine


class Orchestrator:
    """Main OATS orchestrator — coordinates agents, memory, hooks, and skills.

    Two modes:
    - Directed: you give it a task, it executes
    - Autonomous: it generates its own next steps from completed work
    """

    def __init__(self, project_dir: str = "."):
        self.project_dir = Path(project_dir)
        self.trust = TrustEngine()
        self.budget = BudgetTracker()
        self.thoughts = ThoughtEngine()
        self.hooks = HookEngine.from_config(
            str(self.project_dir / ".oats" / "hooks.json"),
            project_dir
        )
        self.memory = MemoryScoper(project_dir)
        self.skills = SkillLoader(project_dir)

    def dispatch(self, task: str, agent: str = None, files: list = None):
        """Dispatch a task to an agent with full context."""
        print(f"Dispatching: {task}")
        print(f"Agent: {agent or 'auto'}")
        print()

        # Fire SessionStart hooks
        self.hooks.fire("SessionStart", {"agent": agent or "orchestrator"})

        # Load context for this agent
        ctx = self.memory.load_context(agent=agent, files_touched=files or [])
        print(f"Context: {ctx['items_loaded']} memory items ({ctx['total_size']:,} bytes)")

        # Find relevant skills
        relevant_skills = self.skills.search(task.split()[0]) if task else []
        if relevant_skills:
            print(f"Relevant skills: {', '.join(s['name'] for s in relevant_skills[:3])}")

        # Build the dispatch prompt
        prompt_parts = [
            f"# Task\n{task}\n",
        ]

        # Add memory context
        if ctx["loaded"]:
            prompt_parts.append("# Context (from memory)")
            for item in ctx["loaded"]:
                prompt_parts.append(f"## {item['name']} ({item['source']})")
                # Truncate large files
                content = item["content"]
                if len(content) > 2000:
                    content = content[:2000] + "\n... (truncated)"
                prompt_parts.append(content)

        prompt = "\n\n".join(prompt_parts)

        # Save dispatch log
        log_dir = self.project_dir / ".oats" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "agent": agent,
            "context_items": ctx["items_loaded"],
            "context_size": ctx["total_size"],
            "skills_found": len(relevant_skills),
        }

        log_file = log_dir / "dispatch_log.json"
        logs = []
        if log_file.exists():
            try:
                logs = json.loads(log_file.read_text())
            except Exception:
                logs = []
        logs.append(log_entry)
        logs = logs[-100:]
        log_file.write_text(json.dumps(logs, indent=2))

        print(f"\nPrompt ready ({len(prompt):,} chars). Dispatch log saved.")
        return prompt

    def team_start(self, name: str, description: str, members: list = None):
        """Start a new team."""
        team = Team(name)
        team.create(description)

        # Default members if none specified
        if not members:
            members = [
                ("backend", "backend"),
                ("frontend", "frontend"),
                ("devops", "devops"),
            ]

        for member_name, member_type in members:
            team.add_member(member_name, member_type)

        # Fire hooks
        self.hooks.fire("SessionStart", {"agent": "team-lead", "team": name})

        print(f"\nTeam '{name}' ready with {len(members)} members.")
        team.status()

    def improve(self, target: str = "skills"):
        """Run the self-improvement loop (Karpathy autoresearch pattern).

        1. Evaluate current state
        2. Identify lowest-scoring item
        3. Generate improvement
        4. Re-evaluate — did it improve?
        5. Keep or revert
        """
        print(f"Self-improvement loop: {target}")
        print()

        if target == "skills":
            skills = self.skills.load_all()
            if not skills:
                print("No skills found.")
                return

            # Score skills by quality indicators
            scored = []
            for s in skills:
                score = 0
                if s["has_frontmatter"]:
                    score += 30
                if s["has_modes"]:
                    score += 30
                if s["has_triggers"]:
                    score += 20
                if s["size"] > 500:
                    score += 10
                if s["size"] > 2000:
                    score += 10
                scored.append((s, score))

            scored.sort(key=lambda x: x[1])

            print(f"Skill scores ({len(scored)} skills):")
            for s, score in scored:
                grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
                print(f"  [{grade}] {score:3d}% {s['name']:25s} ({s['source_type']})")

            # Identify improvement targets
            targets = [(s, score) for s, score in scored if score < 80]
            if targets:
                print(f"\n{len(targets)} skill(s) below grade A — improvement candidates:")
                for s, score in targets[:3]:
                    missing = []
                    if not s["has_frontmatter"]:
                        missing.append("frontmatter")
                    if not s["has_modes"]:
                        missing.append("modes")
                    if not s["has_triggers"]:
                        missing.append("triggers")
                    print(f"  {s['name']}: missing {', '.join(missing)}")
            else:
                print(f"\nAll skills are grade A!")

            avg = sum(score for _, score in scored) / len(scored) if scored else 0
            print(f"\nAverage score: {avg:.0f}%")

        elif target == "memory":
            issues = self.memory.health_check()
            if issues:
                print(f"{len(issues)} memory issue(s) found:")
                for issue in issues:
                    print(f"  [{issue['severity']}] {issue['message']}")
            else:
                print("Memory health: all clear")

        elif target == "hooks":
            errors = self.hooks.validate_config()
            if errors:
                print(f"{len(errors)} hook config error(s):")
                for e in errors:
                    print(f"  - {e}")
            else:
                print("Hooks config: valid")

        elif target == "trust":
            board = self.trust.leaderboard()
            if not board:
                print("No agents tracked yet.")
                return
            print(f"Trust leaderboard ({len(board)} agents):")
            for i, rep in enumerate(board, 1):
                print(f"  {i}. {rep.agent_id:15s} {rep.score:.3f} "
                      f"streak={rep.streak:+d} ({rep.tasks_completed}W/{rep.tasks_failed}L)")
            low = [r for r in board if r.score < 0.3]
            if low:
                print(f"\n{len(low)} agent(s) with low trust — consider retraining or replacing")

        elif target == "budget":
            s = self.budget.status()
            if not s["agents"]:
                print("No budgets configured.")
                return
            session = s["session"]
            print(f"Session: {session['tokens_used']:,}/{session['token_limit']:,} "
                  f"({session['pct']:.1f}%) ${session['cost_usd']:.3f}")
            for aid, b in s["agents"].items():
                pct = b["tokens_used"] / max(1, b["token_limit"]) * 100
                status = "BROKEN" if b["circuit_broken"] else "ok"
                print(f"  {aid:12s} {b['tokens_used']:>8,}/{b['token_limit']:>8,} ({pct:.0f}%) [{status}]")

    def health(self):
        """Full system health check."""
        print("OATS Health Check")
        print("=" * 50)

        # Memory
        inv = self.memory.inventory()
        issues = self.memory.health_check()
        status = "OK" if not issues else f"{len(issues)} issue(s)"
        print(f"\n  Memory:  {inv['total_files']} files, {inv['total_size']:,} bytes [{status}]")

        # Hooks
        hook_errors = self.hooks.validate_config()
        total_hooks = sum(
            len(g.get("hooks", []))
            for groups in self.hooks.config.values()
            for g in groups
        )
        status = "OK" if not hook_errors else f"{len(hook_errors)} error(s)"
        print(f"  Hooks:   {len(self.hooks.config)} events, {total_hooks} hooks [{status}]")

        # Skills
        skills = self.skills.load_all()
        grade_a = sum(1 for s in skills if s["has_frontmatter"] and s["has_modes"] and s["has_triggers"])
        print(f"  Skills:  {len(skills)} total, {grade_a} grade A")

        # Teams
        if TEAMS_DIR.exists():
            teams = [d.name for d in TEAMS_DIR.iterdir() if d.is_dir()]
            active = 0
            for t in teams:
                try:
                    cfg = json.loads((TEAMS_DIR / t / "config.json").read_text())
                    if cfg.get("status") == "active":
                        active += 1
                except Exception:
                    pass
            print(f"  Teams:   {len(teams)} total, {active} active")
        else:
            print("  Teams:   none")

        # Agents
        agents_dir = self.project_dir / "agents"
        if agents_dir.exists():
            agents = list(agents_dir.glob("*.py"))
            print(f"  Agents:  {len(agents)}")
        else:
            print("  Agents:  none")

        # Trust scores
        if self.trust.agents:
            top = self.trust.leaderboard()
            broken = [r for r in top if r.score < 0.2]
            status = "OK" if not broken else f"{len(broken)} low-trust"
            print(f"  Trust:   {len(top)} agents tracked [{status}]")
            for r in top[:3]:
                print(f"           {r.agent_id}: {r.score:.3f} ({r.tasks_completed}W/{r.tasks_failed}L)")
        else:
            print("  Trust:   no agents tracked")

        # Budget
        budget_status = self.budget.status()
        session = budget_status["session"]
        broken = budget_status["circuit_broken"]
        status = f"BROKEN: {', '.join(broken)}" if broken else "OK"
        if budget_status["agents"]:
            print(f"  Budget:  {session['tokens_used']:,} tokens, ${session['cost_usd']:.3f} [{status}]")
        else:
            print("  Budget:  no budgets set")

        # Blackboards
        if BOARD_DIR.exists():
            boards = [d for d in BOARD_DIR.iterdir() if d.is_dir()]
            active = sum(1 for b in boards
                         if json.loads((b / "config.json").read_text()).get("status") == "active")
            print(f"  Boards:  {len(boards)} total, {active} active")
        else:
            print("  Boards:  none")

        print("=" * 50)

        # Thoughts
        t_stats = self.thoughts.stats()
        if t_stats["total_thoughts"]:
            pending = t_stats["pending"]
            print(f"  Thoughts: {t_stats['total_thoughts']} total, {pending} pending")
            next_t = self.thoughts.get_highest_confidence_unacted()
            if next_t:
                print(f"  Next:    {next_t.where_this_leads[:50]}... ({next_t.confidence:.0%})")
        else:
            print("  Thoughts: none — run 'orchestrator.py think' after completing work")

        print("=" * 50)

    def think(self, what_i_built: str, what_i_realized: str,
              where_this_leads: str, confidence: float = 0.5,
              signal_source: str = "completion"):
        """Generate a forward-looking thought after completing work.

        This is the core of autonomous ideation. Each thought links to
        the previous one, forming a chain of creative leaps.
        """
        # Link to the most recent thought
        latest = self.thoughts.get_latest()
        parent_id = latest.id if latest and not latest.child_id else None

        thought = self.thoughts.think_forward(
            what_i_built=what_i_built,
            what_i_realized=what_i_realized,
            where_this_leads=where_this_leads,
            confidence=confidence,
            signal_source=signal_source,
            parent_id=parent_id,
        )

        print(f"Thought recorded: {thought.id}")
        print(f"  Built: {what_i_built[:70]}")
        print(f"  Realized: {what_i_realized[:70]}")
        print(f"  Next: {where_this_leads[:70]}")
        print(f"  Confidence: {confidence:.0%}")

        if parent_id:
            print(f"  Chained from: {parent_id}")

        return thought

    def autonomous(self, max_steps: int = 5, min_confidence: float = 0.3):
        """Run the autonomous thought-action loop.

        1. Check for pending thoughts
        2. Pick the highest-confidence one
        3. Render it as a prompt (for the next session to act on)
        4. After acting, generate the next thought
        5. Repeat until confidence drops below threshold

        This is the 'learning to run' mode — the agent generates its own
        next steps from completed work.
        """
        print(f"Autonomous mode: max {max_steps} steps, min {min_confidence:.0%} confidence")
        print()

        for step in range(max_steps):
            next_thought = self.thoughts.get_highest_confidence_unacted()

            if not next_thought:
                print(f"Step {step + 1}: No pending thoughts. Chain complete.")
                break

            if next_thought.confidence < min_confidence:
                print(f"Step {step + 1}: Best thought is {next_thought.confidence:.0%} confidence "
                      f"(below {min_confidence:.0%} threshold). Stopping — ideas have dried up.")
                break

            print(f"Step {step + 1}: {next_thought.where_this_leads[:60]}")
            print(f"  Confidence: {next_thought.confidence:.0%}")
            print(f"  Prompt:")
            print(f"  {next_thought.as_prompt()[:200]}...")
            print()

        # Show chain
        print()
        self.thoughts.show_chain()


def main():
    parser = argparse.ArgumentParser(
        description="OATS Orchestrator — autonomous agent coordination",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s run "Fix the auth bug"
  %(prog)s run --agent backend "Add rate limiting"
  %(prog)s team start feature-x "Build dashboard"
  %(prog)s team status feature-x
  %(prog)s improve --target skills
  %(prog)s health
        """
    )

    sub = parser.add_subparsers(dest="command")

    # Run
    run_p = sub.add_parser("run", help="Dispatch a task")
    run_p.add_argument("task", help="Task description")
    run_p.add_argument("--agent", help="Target agent")
    run_p.add_argument("--files", nargs="*", help="Files being touched")

    # Team
    team_p = sub.add_parser("team", help="Team management")
    team_sub = team_p.add_subparsers(dest="team_cmd")
    start_p = team_sub.add_parser("start", help="Start a team")
    start_p.add_argument("name", help="Team name")
    start_p.add_argument("description", help="Team description")
    status_p = team_sub.add_parser("status", help="Team status")
    status_p.add_argument("name", help="Team name")
    shutdown_p = team_sub.add_parser("shutdown", help="Shutdown team")
    shutdown_p.add_argument("name", help="Team name")

    # Improve
    improve_p = sub.add_parser("improve", help="Self-improvement loop")
    improve_p.add_argument("--target", default="skills",
                           choices=["skills", "memory", "hooks", "trust", "budget"])

    # Health
    sub.add_parser("health", help="System health check")

    # Think
    think_p = sub.add_parser("think", help="Generate next thought after completing work")
    think_p.add_argument("built", help="What you just built")
    think_p.add_argument("realized", help="What it made you realize")
    think_p.add_argument("leads_to", help="Where this leads next")
    think_p.add_argument("--confidence", type=float, default=0.5)
    think_p.add_argument("--signal", default="completion",
                         choices=["completion", "research", "failure", "user", "competition"])

    # Autonomous
    auto_p = sub.add_parser("autonomous", help="Run thought-action loop")
    auto_p.add_argument("--max-steps", type=int, default=5)
    auto_p.add_argument("--min-confidence", type=float, default=0.3)

    # Chain
    sub.add_parser("chain", help="Show the thought chain")

    # Next
    sub.add_parser("next", help="Show the next pending thought")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    orch = Orchestrator()

    if args.command == "run":
        orch.dispatch(args.task, agent=args.agent, files=args.files)

    elif args.command == "team":
        if args.team_cmd == "start":
            orch.team_start(args.name, args.description)
        elif args.team_cmd == "status":
            Team(args.name).status()
        elif args.team_cmd == "shutdown":
            Team(args.name).shutdown()

    elif args.command == "improve":
        orch.improve(args.target)

    elif args.command == "health":
        orch.health()

    elif args.command == "think":
        orch.think(args.built, args.realized, args.leads_to,
                   confidence=args.confidence, signal_source=args.signal)

    elif args.command == "autonomous":
        orch.autonomous(max_steps=args.max_steps, min_confidence=args.min_confidence)

    elif args.command == "chain":
        orch.thoughts.show_chain()

    elif args.command == "next":
        t = orch.thoughts.get_highest_confidence_unacted()
        if t:
            print(t.as_prompt())
        else:
            print("No pending thoughts.")


if __name__ == "__main__":
    main()
