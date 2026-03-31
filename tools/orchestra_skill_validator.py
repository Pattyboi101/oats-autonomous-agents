#!/usr/bin/env python3
"""Orchestra Skill Validator — tests IndieStack department skills.

Validates skills against our authoring standard:
- Frontmatter (name, description, metadata)
- Modes (how this skill works)
- Proactive triggers
- Output artifacts
- Real experience (gotchas, lessons learned)

Usage:
    python3 .orchestra/sandbox/tools/orchestra_skill_validator.py .orchestra/master/skills/outreach-batch.md
    python3 .orchestra/sandbox/tools/orchestra_skill_validator.py --all
"""

import sys
import os
import re
import glob
import json


def validate_skill(filepath: str) -> dict:
    """Validate a single skill file and return a score + findings."""
    with open(filepath) as f:
        content = f.read()

    findings = {"pass": [], "fail": [], "warn": [], "score": 0}
    max_score = 0

    # 1. Frontmatter (20 points)
    max_score += 20
    if content.startswith("---"):
        fm_end = content.index("---", 3)
        frontmatter = content[3:fm_end].strip()
        findings["pass"].append("Has frontmatter")
        score = 5

        for field in ["name:", "description:", "metadata:"]:
            if field in frontmatter:
                findings["pass"].append(f"Frontmatter has {field}")
                score += 5
            else:
                findings["fail"].append(f"Frontmatter missing {field}")
        findings["score"] += score
    else:
        findings["fail"].append("No frontmatter (should start with ---)")

    # 2. Title and intro (10 points)
    max_score += 10
    if re.search(r'^# .+', content, re.MULTILINE):
        findings["pass"].append("Has title heading")
        findings["score"] += 5
    else:
        findings["fail"].append("No title heading (# Title)")

    if "You are" in content or "Your goal" in content or "Your job" in content:
        findings["pass"].append("Has agent identity/role statement")
        findings["score"] += 5
    else:
        findings["warn"].append("No clear agent identity statement ('You are...')")

    # 3. Before Starting section (10 points)
    max_score += 10
    if "## Before Starting" in content or "## Before" in content:
        findings["pass"].append("Has 'Before Starting' section")
        findings["score"] += 10
    else:
        findings["warn"].append("No 'Before Starting' section — agents should check context first")

    # 4. Modes (15 points)
    max_score += 15
    mode_matches = re.findall(r'### Mode \d', content)
    if len(mode_matches) >= 2:
        findings["pass"].append(f"Has {len(mode_matches)} modes")
        findings["score"] += 15
    elif len(mode_matches) == 1:
        findings["pass"].append("Has 1 mode")
        findings["score"] += 8
        findings["warn"].append("Only 1 mode — consider adding Mode 2 for optimization/follow-up")
    else:
        findings["warn"].append("No modes defined (### Mode N)")

    # 5. Proactive Triggers (15 points)
    max_score += 15
    if "Proactive Trigger" in content or "proactive" in content.lower():
        triggers = re.findall(r'\*\*(.+?)\*\*.*?→', content)
        if triggers:
            findings["pass"].append(f"Has {len(triggers)} proactive triggers")
            findings["score"] += 15
        else:
            findings["pass"].append("Has proactive triggers section")
            findings["score"] += 10
    else:
        findings["warn"].append("No proactive triggers — agents should flag issues without being asked")

    # 6. Output Artifacts (10 points)
    max_score += 10
    if "Output" in content and ("|" in content):  # Table format
        findings["pass"].append("Has output artifacts table")
        findings["score"] += 10
    elif "Output" in content:
        findings["pass"].append("Has output section")
        findings["score"] += 5
        findings["warn"].append("Output section should use a table format")
    else:
        findings["warn"].append("No output artifacts section")

    # 7. Real Experience / Gotchas (10 points)
    max_score += 10
    gotcha_keywords = ["gotcha", "lesson", "caught", "bug", "mistake", "real experience", "2026-"]
    has_experience = any(kw.lower() in content.lower() for kw in gotcha_keywords)
    if has_experience:
        findings["pass"].append("Contains real experience / lessons learned")
        findings["score"] += 10
    else:
        findings["warn"].append("No gotchas or lessons learned — skills should encode real experience")

    # 8. Code Examples (10 points)
    max_score += 10
    code_blocks = re.findall(r'```', content)
    if len(code_blocks) >= 4:  # At least 2 code blocks (open + close)
        findings["pass"].append(f"Has {len(code_blocks)//2} code examples")
        findings["score"] += 10
    elif len(code_blocks) >= 2:
        findings["pass"].append("Has code examples")
        findings["score"] += 5
    else:
        findings["warn"].append("No code examples — concrete examples help agents follow the skill")

    # Calculate percentage
    pct = int((findings["score"] / max_score) * 100) if max_score else 0
    findings["max_score"] = max_score
    findings["percentage"] = pct

    if pct >= 80:
        findings["grade"] = "A"
    elif pct >= 60:
        findings["grade"] = "B"
    elif pct >= 40:
        findings["grade"] = "C"
    else:
        findings["grade"] = "D"

    return findings


def print_report(filepath: str, findings: dict):
    """Pretty-print a validation report."""
    name = os.path.basename(filepath)
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"  Score: {findings['score']}/{findings['max_score']} ({findings['percentage']}%) — Grade {findings['grade']}")
    print(f"{'='*60}")

    if findings["pass"]:
        for p in findings["pass"]:
            print(f"  ✓ {p}")

    if findings["fail"]:
        for f in findings["fail"]:
            print(f"  ✗ {f}")

    if findings["warn"]:
        for w in findings["warn"]:
            print(f"  ⚠ {w}")

    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 orchestra_skill_validator.py <skill.md> [--all]")
        sys.exit(1)

    if sys.argv[1] == "--all":
        # Find all skill files
        skills = glob.glob(".orchestra/master/skills/*.md") + \
                 glob.glob(".orchestra/departments/*/skills/*.md")
        if not skills:
            print("No skills found")
            sys.exit(1)

        total_score = 0
        total_max = 0
        for skill in sorted(skills):
            findings = validate_skill(skill)
            print_report(skill, findings)
            total_score += findings["score"]
            total_max += findings["max_score"]

        avg = int((total_score / total_max) * 100) if total_max else 0
        print(f"\n{'='*60}")
        print(f"  OVERALL: {total_score}/{total_max} ({avg}%) across {len(skills)} skills")
        print(f"{'='*60}")
    else:
        filepath = sys.argv[1]
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            sys.exit(1)
        findings = validate_skill(filepath)
        print_report(filepath, findings)


if __name__ == "__main__":
    main()
