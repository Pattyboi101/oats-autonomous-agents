#!/usr/bin/env python3
"""Token Economist — analyze orchestrator cost patterns and suggest optimizations.

Reads orchestrator history logs and playbook to find:
- Which departments cost the most
- Which task types are cheapest/most expensive
- Where cheaper models could be used
- Opportunities for caching or batching

Usage:
    python3 scripts/token_economist.py
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path


def parse_history():
    """Parse orchestrator history files for cost data."""
    history_dir = Path(".orchestra/history")
    if not history_dir.exists():
        return []

    runs = []
    for f in sorted(history_dir.glob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
                runs.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return runs


def parse_playbook():
    """Extract cost data from playbook entries."""
    playbook = Path(".orchestra/memory/playbook.md")
    if not playbook.exists():
        return []

    entries = []
    content = playbook.read_text()

    # Find cost entries like "Total cost: $0.3206"
    for match in re.finditer(r'Task: (.+?)\n.*?Total cost: \$(\d+\.\d+)', content, re.DOTALL):
        task = match.group(1).strip()
        cost = float(match.group(2))
        entries.append({"task": task, "cost": cost})

    # Find department costs like "backend: done ($1.2407)"
    for match in re.finditer(r'(\w+): done \(\$(\d+\.\d+)\)', content):
        dept = match.group(1)
        cost = float(match.group(2))
        entries.append({"dept": dept, "cost": cost})

    return entries


def analyze_costs(entries):
    """Analyze cost patterns and generate recommendations."""
    if not entries:
        return "No cost data found in playbook or history."

    # Aggregate by department
    dept_costs = defaultdict(list)
    task_costs = []

    for e in entries:
        if "dept" in e:
            dept_costs[e["dept"]].append(e["cost"])
        if "task" in e:
            task_costs.append(e)

    report = []
    report.append("# Token Economist Report")
    report.append(f"\nAnalyzed {len(entries)} cost entries.\n")

    # Department breakdown
    report.append("## Department Costs")
    report.append("| Department | Calls | Total | Avg | Model |")
    report.append("|-----------|-------|-------|-----|-------|")

    model_map = {
        "frontend": "sonnet",
        "backend": "sonnet",
        "devops": "haiku",
        "content": "sonnet",
        "mcp": "sonnet",
        "strategy": "opus",
    }

    for dept, costs in sorted(dept_costs.items(), key=lambda x: -sum(x[1])):
        total = sum(costs)
        avg = total / len(costs)
        model = model_map.get(dept, "unknown")
        report.append(f"| {dept} | {len(costs)} | ${total:.2f} | ${avg:.2f} | {model} |")

    # Recommendations
    report.append("\n## Recommendations")

    # Find expensive departments
    for dept, costs in dept_costs.items():
        avg = sum(costs) / len(costs)
        if avg > 1.0 and dept not in ("strategy",):
            report.append(f"- **{dept}** averages ${avg:.2f}/call. Consider:")
            report.append(f"  - Narrower task scope (smaller briefs)")
            report.append(f"  - Pre-reading files before dispatching")
            if dept == "frontend":
                report.append(f"  - Frontend often reads large route files — send specific line ranges")

    # Find tasks that could use cheaper models
    for dept, costs in dept_costs.items():
        if dept == "devops" and sum(costs) / len(costs) < 0.10:
            report.append(f"- **{dept}** (haiku) averages ${sum(costs)/len(costs):.2f} — good. Keep routine tasks here.")

    # General suggestions
    report.append("\n## General Optimizations")
    report.append("- **Batch similar tasks** — 5 tool data fixes in 1 SSH call vs 5 separate calls")
    report.append("- **Pre-compute context** — read files before dispatching so agents don't re-read")
    report.append("- **Use DevOps (haiku) for simple checks** — health checks, status queries, file existence")
    report.append("- **S&QA (opus) is expensive but earns it** — caught broken claim links, worth every token")
    report.append("- **Cache API responses** — if testing the same endpoint repeatedly, cache the first result")

    return "\n".join(report)


def main():
    print("Parsing orchestrator history and playbook...")
    entries = parse_playbook()
    history = parse_history()

    # Merge history entries if available
    for run in history:
        if "total_cost" in run:
            entries.append({"task": run.get("task", "unknown"), "cost": run["total_cost"]})
        for dept_result in run.get("results", []):
            if "cost" in dept_result:
                entries.append({"dept": dept_result.get("dept", "unknown"), "cost": dept_result["cost"]})

    report = analyze_costs(entries)

    output_path = "/tmp/token_economist_report.md"
    with open(output_path, "w") as f:
        f.write(report)

    print(report)
    print(f"\nReport saved to {output_path}")


if __name__ == "__main__":
    main()
