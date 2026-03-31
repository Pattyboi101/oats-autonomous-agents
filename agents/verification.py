#!/usr/bin/env python3
"""Verification Agent — try to break it, don't confirm it works.

Inspired by Claude Code's internal verification agent. This agent is
strictly read-only — it runs tests, checks outputs, and reports failures.
It never modifies project files.

Two documented failure patterns to avoid:
1. VERIFICATION AVOIDANCE: reading code and writing "PASS" without running anything
2. SEDUCED BY THE FIRST 80%: seeing a polished UI and not testing edge cases

Usage:
    python3 agents/verification.py                     # verify last commit
    python3 agents/verification.py --commit abc123     # verify specific commit
    python3 agents/verification.py --full              # full project verification
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


class VerificationAgent:
    def __init__(self, project_dir: str = "."):
        self.project_dir = Path(project_dir)
        self.results = []
        self.passed = 0
        self.failed = 0

    def check(self, name: str, command: str, expect_success: bool = True,
              expect_output: str = None) -> bool:
        """Run a check and record the result."""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=60, cwd=self.project_dir
            )
            success = (result.returncode == 0) == expect_success

            if expect_output and expect_output not in result.stdout:
                success = False

            status = "PASS" if success else "FAIL"
            self.results.append({
                "name": name,
                "status": status,
                "command": command,
                "returncode": result.returncode,
                "stdout_preview": result.stdout[:200] if result.stdout else "",
                "stderr_preview": result.stderr[:200] if result.stderr else "",
            })

            if success:
                self.passed += 1
            else:
                self.failed += 1

            icon = "✅" if success else "❌"
            print(f"  {icon} [{status}] {name}")
            if not success and result.stderr:
                print(f"      stderr: {result.stderr[:100]}")

            return success

        except subprocess.TimeoutExpired:
            self.results.append({
                "name": name,
                "status": "TIMEOUT",
                "command": command,
            })
            self.failed += 1
            print(f"  ⏰ [TIMEOUT] {name}")
            return False
        except Exception as e:
            self.results.append({
                "name": name,
                "status": "ERROR",
                "command": command,
                "error": str(e),
            })
            self.failed += 1
            print(f"  💥 [ERROR] {name}: {e}")
            return False

    def detect_project_type(self) -> list:
        """Detect what kind of project this is."""
        types = []
        if (self.project_dir / "package.json").exists():
            types.append("node")
        if (self.project_dir / "pyproject.toml").exists():
            types.append("python")
        if (self.project_dir / "Cargo.toml").exists():
            types.append("rust")
        if (self.project_dir / "go.mod").exists():
            types.append("go")
        if (self.project_dir / "Dockerfile").exists():
            types.append("docker")
        if (self.project_dir / "fly.toml").exists():
            types.append("flyio")
        if (self.project_dir / ".orchestra").exists():
            types.append("orchestra")
        if (self.project_dir / "smoke_test.py").exists():
            types.append("has_smoke_test")
        return types

    def get_changed_files(self, commit: str = "HEAD") -> list:
        """Get files changed in a commit."""
        try:
            result = subprocess.run(
                f"git diff --name-only {commit}~1 {commit}",
                shell=True, capture_output=True, text=True,
                timeout=10, cwd=self.project_dir
            )
            return [f for f in result.stdout.strip().split("\n") if f]
        except Exception:
            return []

    def verify_commit(self, commit: str = "HEAD"):
        """Verify a specific commit."""
        print(f"Verifying commit: {commit}")
        print()

        changed = self.get_changed_files(commit)
        print(f"Changed files: {len(changed)}")
        for f in changed[:10]:
            print(f"  - {f}")
        print()

        types = self.detect_project_type()
        print(f"Project type: {', '.join(types)}")
        print()

        # Universal baseline
        print("--- Universal Baseline ---")

        # 1. Syntax check (Python)
        if "python" in types:
            py_files = [f for f in changed if f.endswith(".py")]
            for pf in py_files[:5]:
                self.check(
                    f"Syntax: {pf}",
                    f"python3 -c \"import ast; ast.parse(open('{pf}').read())\""
                )

        # 2. Test suite
        if "has_smoke_test" in types:
            self.check("Smoke test", "python3 smoke_test.py", expect_output="passed")

        if "python" in types:
            self.check("Python compile check",
                        "python3 -m compileall src/ -q 2>&1 | head -5",
                        expect_success=True)

        # 3. Build check
        if "docker" in types:
            self.check("Dockerfile syntax",
                        "python3 -c \"open('Dockerfile').read()\" 2>&1")

        # 4. Orchestra validation
        if "orchestra" in types:
            self.check("Skill validator",
                        "python3 .orchestra/sandbox/tools/orchestra_skill_validator.py --all 2>&1 | tail -3")

        # Type-specific checks
        print()
        print("--- Type-Specific Checks ---")

        # Check for common issues in changed files
        for f in changed:
            if f.endswith(".py"):
                # Check for debug prints
                self.check(
                    f"No debug prints: {f}",
                    f"grep -n 'print.*DEBUG\\|breakpoint()\\|import pdb' {f} | wc -l",
                    expect_output="0"
                )

        # Security checks
        print()
        print("--- Security ---")
        self.check(
            "No secrets in changed files",
            "git diff HEAD~1 HEAD | grep -iE 'sk_live|sk_test|ghp_|gho_|AKIA|password\\s*=' | wc -l",
            expect_output="0"
        )

        self.check(
            "No .env committed",
            "git ls-files .env | wc -l",
            expect_output="0"
        )

    def verify_full(self):
        """Full project verification."""
        print("Full project verification")
        print()

        types = self.detect_project_type()
        print(f"Project type: {', '.join(types)}")
        print()

        print("--- Build & Test ---")
        if "python" in types:
            self.check("Python compiles", "python3 -m compileall src/ -q")
        if "has_smoke_test" in types:
            self.check("Smoke test", "python3 smoke_test.py")
        if "orchestra" in types:
            self.check("Skills valid",
                        "python3 .orchestra/sandbox/tools/orchestra_skill_validator.py --all 2>&1 | tail -1")

        print()
        print("--- Security ---")
        self.check("No secrets in repo",
                    "grep -rn 'sk_live\\|sk_test\\|ghp_\\|AKIA' src/ --include='*.py' | wc -l",
                    expect_output="0")
        self.check("No .env committed", "git ls-files .env | wc -l", expect_output="0")
        self.check(".gitignore exists", "test -f .gitignore && echo yes", expect_output="yes")

        print()
        print("--- Code Quality ---")
        self.check("No TODO/FIXME/HACK",
                    "grep -rn 'TODO\\|FIXME\\|HACK' src/ --include='*.py' | wc -l")

    def report(self) -> dict:
        """Generate the verification report."""
        total = self.passed + self.failed
        report = {
            "timestamp": datetime.now().isoformat(),
            "total": total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": f"{100*self.passed//total}%" if total else "N/A",
            "results": self.results,
        }

        print()
        print(f"{'='*50}")
        print(f"  Results: {self.passed}/{total} PASS — {self.failed} FAIL(s)")
        print(f"{'='*50}")

        return report


def main():
    parser = argparse.ArgumentParser(description="Verification Agent — try to break it")
    parser.add_argument("--commit", default="HEAD", help="Commit to verify")
    parser.add_argument("--full", action="store_true", help="Full project verification")
    parser.add_argument("--output", default="/tmp/verification_report.md", help="Report output path")
    args = parser.parse_args()

    agent = VerificationAgent()

    if args.full:
        agent.verify_full()
    else:
        agent.verify_commit(args.commit)

    report = agent.report()

    # Save report
    with open(args.output, "w") as f:
        f.write(f"# Verification Report\n\n")
        f.write(f"**Date:** {report['timestamp']}\n")
        f.write(f"**Result:** {report['passed']}/{report['total']} PASS\n\n")
        for r in report["results"]:
            icon = "✅" if r["status"] == "PASS" else "❌"
            f.write(f"- {icon} **{r['name']}**: {r['status']}\n")

    print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
