#!/usr/bin/env python3
"""Test Harness — iterative test-driven quality improvement for OATS agents.

Real-world lesson: IndieStack improved search quality from 2/10 to 10/10
by running the same 10-query test suite after every change. This tool
codifies that pattern — define assertions, run them, iterate until 100%.

The loop: define tests once, run after every change, fix what fails,
re-run until green. Each run is tracked so you can see quality improve
over time.

Assertion types:
    contains:<string>           — stdout contains the string
    not_contains:<string>       — stdout does NOT contain the string
    exit:0                      — command exits with code 0 (any code works)
    regex:<pattern>             — stdout matches the regex pattern
    json_path:<path>=<value>    — JSON output has value at JSONPath
                                  e.g. json_path:items[0].name=Stripe

Test suites are persisted to .oats/test_harnesses/{name}.json so they
survive across sessions. History is appended to the same directory.

Usage:
    # Define a new test suite
    python3 tools/test_harness.py define search-quality

    # Add individual tests
    python3 tools/test_harness.py add search-quality \\
        --test "stripe-appears" \\
        --cmd "curl -s localhost:8000/api/search?q=payments" \\
        --expect "contains:Stripe" \\
        --weight 8

    # Run all tests in a suite
    python3 tools/test_harness.py run search-quality

    # Show pass rate
    python3 tools/test_harness.py score search-quality

    # Show improvement over time
    python3 tools/test_harness.py history search-quality

    # Auto-iterate: run tests, apply fix, re-run until 100% or max iters
    python3 tools/test_harness.py iterate search-quality \\
        --fix "python3 scripts/rebuild_index.py"
"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

HARNESS_DIR = Path(".oats/test_harnesses")


@dataclass
class TestCase:
    """A single test within a suite."""
    name: str
    command: str
    assertion: str
    weight: int = 5
    timeout: int = 30
    description: str = ""


@dataclass
class TestResult:
    """Result of running a single test case."""
    name: str
    passed: bool
    assertion: str
    weight: int
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    error: str = ""


@dataclass
class RunRecord:
    """Snapshot of a complete test run for history tracking."""
    timestamp: str
    passed: int
    failed: int
    total: int
    score: float
    weighted_score: float
    duration_ms: int
    results: list = field(default_factory=list)


class TestSuite:
    """A named collection of test cases, persisted to disk."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.tests: list[TestCase] = []
        self.suite_file = HARNESS_DIR / f"{name}.json"
        self.history_file = HARNESS_DIR / f"{name}_history.json"

    def add_test(self, test: TestCase):
        """Add a test case to the suite. Replaces if name already exists."""
        self.tests = [t for t in self.tests if t.name != test.name]
        self.tests.append(test)

    def remove_test(self, test_name: str) -> bool:
        """Remove a test by name. Returns True if found."""
        before = len(self.tests)
        self.tests = [t for t in self.tests if t.name != test_name]
        return len(self.tests) < before

    def save(self):
        """Persist suite definition to disk."""
        HARNESS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "name": self.name,
            "description": self.description,
            "tests": [asdict(t) for t in self.tests],
        }
        self.suite_file.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, name: str) -> "TestSuite":
        """Load a suite from disk."""
        path = HARNESS_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Test suite '{name}' not found at {path}")
        data = json.loads(path.read_text())
        suite = cls(data["name"], data.get("description", ""))
        for t in data.get("tests", []):
            suite.tests.append(TestCase(**t))
        return suite

    @classmethod
    def list_suites(cls) -> list[str]:
        """List all defined test suite names."""
        if not HARNESS_DIR.exists():
            return []
        return sorted(
            f.stem for f in HARNESS_DIR.glob("*.json")
            if not f.stem.endswith("_history")
        )


def _check_assertion(assertion: str, stdout: str, exit_code: int) -> tuple:
    """Evaluate an assertion against command output.

    Returns:
        (passed: bool, error_message: str)
    """
    if not assertion:
        return True, ""

    if assertion.startswith("contains:"):
        expected = assertion[len("contains:"):]
        if expected in stdout:
            return True, ""
        return False, f"stdout does not contain '{expected}'"

    if assertion.startswith("not_contains:"):
        unexpected = assertion[len("not_contains:"):]
        if unexpected not in stdout:
            return True, ""
        return False, f"stdout contains '{unexpected}' (should not)"

    if assertion.startswith("exit:"):
        expected_code = int(assertion[len("exit:"):])
        if exit_code == expected_code:
            return True, ""
        return False, f"exit code {exit_code}, expected {expected_code}"

    if assertion.startswith("regex:"):
        pattern = assertion[len("regex:"):]
        if re.search(pattern, stdout):
            return True, ""
        return False, f"stdout does not match regex '{pattern}'"

    if assertion.startswith("json_path:"):
        spec = assertion[len("json_path:"):]
        if "=" not in spec:
            return False, f"json_path assertion must be path=value, got '{spec}'"
        path_str, expected_value = spec.split("=", 1)
        return _check_json_path(stdout, path_str, expected_value)

    return False, f"unknown assertion type: '{assertion}'"


def _check_json_path(stdout: str, path_str: str, expected: str) -> tuple:
    """Navigate a simple JSONPath expression and check the value.

    Supports dot notation and integer array indices:
        items[0].name    -> data["items"][0]["name"]
        meta.count       -> data["meta"]["count"]
    """
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError) as e:
        return False, f"stdout is not valid JSON: {e}"

    # Parse path segments: "items[0].name" -> ["items", 0, "name"]
    segments = []
    for part in path_str.split("."):
        if not part:
            continue
        # Handle array indexing: items[0] -> "items", 0
        bracket_match = re.match(r"^(\w+)\[(\d+)\]$", part)
        if bracket_match:
            segments.append(bracket_match.group(1))
            segments.append(int(bracket_match.group(2)))
        else:
            segments.append(part)

    # Navigate
    current = data
    for seg in segments:
        try:
            if isinstance(seg, int):
                current = current[seg]
            else:
                current = current[seg]
        except (KeyError, IndexError, TypeError) as e:
            return False, f"path '{path_str}' not found: {e}"

    # Compare as strings (allows numeric comparison too)
    actual = str(current)
    if actual == expected:
        return True, ""
    return False, f"at '{path_str}': got '{actual}', expected '{expected}'"


class TestRunner:
    """Execute test suites and track results over time."""

    def __init__(self):
        self._tracer = None

    def _get_tracer(self):
        """Lazy-load tracer integration. Gracefully skip if unavailable."""
        if self._tracer is None:
            try:
                from tools.tracer import Tracer
                self._tracer = Tracer(f"test-{int(time.time())}")
            except (ImportError, Exception):
                self._tracer = False  # Sentinel: tried and failed
        return self._tracer if self._tracer else None

    def run(self, suite_name: str) -> list[TestResult]:
        """Run all tests in a suite and return results."""
        suite = TestSuite.load(suite_name)
        results = []

        print(f"Test Suite: {suite.name}")
        if suite.description:
            print(f"  {suite.description}")
        print(f"  Tests: {len(suite.tests)}")
        print()

        for i, test in enumerate(suite.tests):
            result = self._run_single(test, index=i + 1, total=len(suite.tests))
            results.append(result)

        # Record trace entry if tracer is available
        tracer = self._get_tracer()
        if tracer:
            passed = sum(1 for r in results if r.passed)
            tracer.record(
                "test_harness", "test_run",
                {"suite": suite_name, "tests": len(results)},
                {
                    "status": "ok" if passed == len(results) else "partial",
                    "passed": passed,
                    "failed": len(results) - passed,
                    "score": f"{passed}/{len(results)}",
                },
            )

        # Append to history
        self._record_history(suite_name, results)

        # Print summary
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        print()
        print(f"  Result: {passed}/{total} passed")
        if passed < total:
            for r in results:
                if not r.passed:
                    print(f"    FAIL: {r.name} — {r.error}")

        return results

    def _run_single(self, test: TestCase, index: int = 0,
                     total: int = 0) -> TestResult:
        """Execute a single test case."""
        prefix = f"  [{index}/{total}]" if total else "  "
        print(f"{prefix} {test.name}...", end=" ", flush=True)

        start = time.time()
        try:
            proc = subprocess.run(
                test.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=test.timeout,
            )
            duration_ms = int((time.time() - start) * 1000)

            passed, error = _check_assertion(
                test.assertion, proc.stdout, proc.returncode
            )

            result = TestResult(
                name=test.name,
                passed=passed,
                assertion=test.assertion,
                weight=test.weight,
                stdout=proc.stdout[:2000],
                stderr=proc.stderr[:500],
                exit_code=proc.returncode,
                duration_ms=duration_ms,
                error=error,
            )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            result = TestResult(
                name=test.name,
                passed=False,
                assertion=test.assertion,
                weight=test.weight,
                duration_ms=duration_ms,
                error=f"timeout after {test.timeout}s",
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            result = TestResult(
                name=test.name,
                passed=False,
                assertion=test.assertion,
                weight=test.weight,
                duration_ms=duration_ms,
                error=str(e),
            )

        status = "PASS" if result.passed else "FAIL"
        print(f"{status} ({result.duration_ms}ms)")
        return result

    def score(self, suite_name: str) -> dict:
        """Calculate pass rate for a suite (from last run in history)."""
        history = self._load_history(suite_name)
        if not history:
            return {"suite": suite_name, "score": "no runs yet"}

        last = history[-1]
        return {
            "suite": suite_name,
            "passed": last["passed"],
            "total": last["total"],
            "score": f"{last['passed']}/{last['total']}",
            "rate": f"{last['score']:.0%}",
            "weighted_rate": f"{last['weighted_score']:.0%}",
            "last_run": last["timestamp"],
        }

    def iterate(self, suite_name: str, fix_command: str,
                max_iterations: int = 10) -> dict:
        """Run tests, apply fix, re-run until 100% or max iterations.

        The core iterative loop:
            1. Run all tests
            2. If all pass, done
            3. Run fix_command
            4. Go to 1 (up to max_iterations)

        Returns summary of the iteration process.
        """
        print(f"Iterate: {suite_name}")
        print(f"  Fix command: {fix_command}")
        print(f"  Max iterations: {max_iterations}")
        print()

        iteration_log = []

        for iteration in range(1, max_iterations + 1):
            print(f"--- Iteration {iteration}/{max_iterations} ---")
            print()

            results = self.run(suite_name)
            passed = sum(1 for r in results if r.passed)
            total = len(results)
            rate = passed / total if total else 0

            iteration_log.append({
                "iteration": iteration,
                "passed": passed,
                "total": total,
                "rate": rate,
            })

            if passed == total:
                print()
                print(f"  All tests passing after {iteration} iteration(s).")
                return {
                    "status": "converged",
                    "iterations": iteration,
                    "final_score": f"{passed}/{total}",
                    "log": iteration_log,
                }

            # Apply fix
            print()
            print(f"  Applying fix: {fix_command}")
            try:
                fix_result = subprocess.run(
                    fix_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if fix_result.returncode != 0:
                    print(f"  Fix command failed (exit {fix_result.returncode})")
                    if fix_result.stderr:
                        print(f"    {fix_result.stderr[:200]}")
                else:
                    print(f"  Fix applied.")
            except subprocess.TimeoutExpired:
                print(f"  Fix command timed out.")
            print()

        # Did not converge
        print(f"  Did not converge after {max_iterations} iterations.")
        return {
            "status": "max_iterations",
            "iterations": max_iterations,
            "final_score": f"{iteration_log[-1]['passed']}/{iteration_log[-1]['total']}",
            "log": iteration_log,
        }

    def history(self, suite_name: str) -> list[dict]:
        """Return run history for a suite."""
        return self._load_history(suite_name)

    def _record_history(self, suite_name: str, results: list[TestResult]):
        """Append a run record to history."""
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        weighted_passed = sum(r.weight for r in results if r.passed)
        weighted_total = sum(r.weight for r in results)
        total_duration = sum(r.duration_ms for r in results)

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "passed": passed,
            "failed": total - passed,
            "total": total,
            "score": passed / total if total else 0,
            "weighted_score": weighted_passed / weighted_total if weighted_total else 0,
            "duration_ms": total_duration,
            "results": [
                {"name": r.name, "passed": r.passed, "error": r.error}
                for r in results
            ],
        }

        history = self._load_history(suite_name)
        history.append(record)

        HARNESS_DIR.mkdir(parents=True, exist_ok=True)
        history_file = HARNESS_DIR / f"{suite_name}_history.json"
        history_file.write_text(json.dumps(history, indent=2))

    def _load_history(self, suite_name: str) -> list[dict]:
        """Load run history from disk."""
        history_file = HARNESS_DIR / f"{suite_name}_history.json"
        if not history_file.exists():
            return []
        try:
            return json.loads(history_file.read_text())
        except (json.JSONDecodeError, ValueError):
            return []


def main():
    if len(sys.argv) < 2:
        print("Test Harness — iterative test-driven quality improvement")
        print()
        print("Usage:")
        print("  test_harness.py define <name> [--desc <description>]")
        print("  test_harness.py add <name> --test <test_name> --cmd <command> --expect <assertion> [--weight N]")
        print("  test_harness.py remove <name> --test <test_name>")
        print("  test_harness.py run <name>")
        print("  test_harness.py score <name>")
        print("  test_harness.py history <name>")
        print("  test_harness.py iterate <name> --fix <command> [--max N]")
        print("  test_harness.py list")
        print("  test_harness.py show <name>")
        print()
        print("Assertion types:")
        print("  contains:<string>           stdout contains string")
        print("  not_contains:<string>       stdout does not contain string")
        print("  exit:0                      command exits with code 0")
        print("  regex:<pattern>             stdout matches regex")
        print("  json_path:<path>=<value>    JSON output at path equals value")
        return

    cmd = sys.argv[1]

    if cmd == "define":
        if len(sys.argv) < 3:
            print("Usage: test_harness.py define <name> [--desc <description>]")
            return

        name = sys.argv[2]
        desc = ""
        if "--desc" in sys.argv:
            idx = sys.argv.index("--desc")
            if idx + 1 < len(sys.argv):
                desc = sys.argv[idx + 1]

        suite = TestSuite(name, desc)

        # If a JSON file is provided via stdin or as a path, load tests from it
        if "--from" in sys.argv:
            idx = sys.argv.index("--from")
            if idx + 1 < len(sys.argv):
                json_path = Path(sys.argv[idx + 1])
                if json_path.exists():
                    data = json.loads(json_path.read_text())
                    for t in data.get("tests", data if isinstance(data, list) else []):
                        suite.add_test(TestCase(**t))

        suite.save()
        print(f"Suite '{name}' created ({len(suite.tests)} tests).")
        print(f"  Saved to: {suite.suite_file}")

    elif cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: test_harness.py add <name> --test <test_name> --cmd <command> --expect <assertion>")
            return

        name = sys.argv[2]
        try:
            suite = TestSuite.load(name)
        except FileNotFoundError:
            print(f"Suite '{name}' not found. Create it first with: test_harness.py define {name}")
            return

        # Parse flags
        test_name = ""
        command = ""
        assertion = ""
        weight = 5
        timeout = 30
        description = ""

        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--test" and i + 1 < len(args):
                test_name = args[i + 1]; i += 2
            elif args[i] == "--cmd" and i + 1 < len(args):
                command = args[i + 1]; i += 2
            elif args[i] == "--expect" and i + 1 < len(args):
                assertion = args[i + 1]; i += 2
            elif args[i] == "--weight" and i + 1 < len(args):
                weight = int(args[i + 1]); i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = int(args[i + 1]); i += 2
            elif args[i] == "--desc" and i + 1 < len(args):
                description = args[i + 1]; i += 2
            else:
                i += 1

        if not test_name or not command or not assertion:
            print("Required: --test, --cmd, --expect")
            return

        test = TestCase(
            name=test_name,
            command=command,
            assertion=assertion,
            weight=weight,
            timeout=timeout,
            description=description,
        )
        suite.add_test(test)
        suite.save()
        print(f"Test '{test_name}' added to suite '{name}' ({len(suite.tests)} tests total).")

    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: test_harness.py remove <name> --test <test_name>")
            return

        name = sys.argv[2]
        try:
            suite = TestSuite.load(name)
        except FileNotFoundError:
            print(f"Suite '{name}' not found.")
            return

        test_name = ""
        if "--test" in sys.argv:
            idx = sys.argv.index("--test")
            if idx + 1 < len(sys.argv):
                test_name = sys.argv[idx + 1]

        if not test_name:
            print("Required: --test <test_name>")
            return

        if suite.remove_test(test_name):
            suite.save()
            print(f"Test '{test_name}' removed. {len(suite.tests)} tests remaining.")
        else:
            print(f"Test '{test_name}' not found in suite '{name}'.")

    elif cmd == "run":
        if len(sys.argv) < 3:
            print("Usage: test_harness.py run <name>")
            return

        runner = TestRunner()
        runner.run(sys.argv[2])

    elif cmd == "score":
        if len(sys.argv) < 3:
            print("Usage: test_harness.py score <name>")
            return

        runner = TestRunner()
        info = runner.score(sys.argv[2])
        if "rate" in info:
            print(f"Suite: {info['suite']}")
            print(f"  Score:    {info['score']} ({info['rate']})")
            print(f"  Weighted: {info['weighted_rate']}")
            print(f"  Last run: {info['last_run']}")
        else:
            print(f"Suite: {info['suite']}")
            print(f"  {info['score']}")

    elif cmd == "history":
        if len(sys.argv) < 3:
            print("Usage: test_harness.py history <name>")
            return

        runner = TestRunner()
        records = runner.history(sys.argv[2])

        if not records:
            print(f"No history for suite '{sys.argv[2]}'.")
            return

        print(f"History: {sys.argv[2]} ({len(records)} runs)")
        print()
        print(f"  {'#':>3s}  {'Timestamp':19s}  {'Score':>7s}  {'Rate':>6s}  {'Time':>7s}")
        print(f"  {'---':>3s}  {'---':19s}  {'---':>7s}  {'---':>6s}  {'---':>7s}")

        for i, rec in enumerate(records):
            ts = rec["timestamp"][:19]
            score = f"{rec['passed']}/{rec['total']}"
            rate = f"{rec['score']:.0%}"
            ms = f"{rec['duration_ms']}ms"
            print(f"  {i+1:3d}  {ts:19s}  {score:>7s}  {rate:>6s}  {ms:>7s}")

        # Show trend
        if len(records) >= 2:
            first_rate = records[0]["score"]
            last_rate = records[-1]["score"]
            delta = last_rate - first_rate
            direction = "improved" if delta > 0 else "declined" if delta < 0 else "unchanged"
            print()
            print(f"  Trend: {first_rate:.0%} -> {last_rate:.0%} ({direction})")

    elif cmd == "iterate":
        if len(sys.argv) < 3:
            print("Usage: test_harness.py iterate <name> --fix <command> [--max N]")
            return

        name = sys.argv[2]
        fix_command = ""
        max_iters = 10

        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--fix" and i + 1 < len(args):
                fix_command = args[i + 1]; i += 2
            elif args[i] == "--max" and i + 1 < len(args):
                max_iters = int(args[i + 1]); i += 2
            else:
                i += 1

        if not fix_command:
            print("Required: --fix <command>")
            return

        runner = TestRunner()
        result = runner.iterate(name, fix_command, max_iterations=max_iters)
        print()
        print(f"  Status: {result['status']}")
        print(f"  Iterations: {result['iterations']}")
        print(f"  Final score: {result['final_score']}")

    elif cmd == "list":
        suites = TestSuite.list_suites()
        if not suites:
            print("No test suites defined.")
            print("  Create one with: test_harness.py define <name>")
            return

        print(f"Test suites ({len(suites)}):")
        for name in suites:
            try:
                suite = TestSuite.load(name)
                print(f"  {name:20s}  {len(suite.tests):2d} tests  {suite.description}")
            except Exception:
                print(f"  {name:20s}  (error loading)")

    elif cmd == "show":
        if len(sys.argv) < 3:
            print("Usage: test_harness.py show <name>")
            return

        try:
            suite = TestSuite.load(sys.argv[2])
        except FileNotFoundError:
            print(f"Suite '{sys.argv[2]}' not found.")
            return

        print(f"Suite: {suite.name}")
        if suite.description:
            print(f"  {suite.description}")
        print(f"  Tests: {len(suite.tests)}")
        print()
        for i, t in enumerate(suite.tests):
            print(f"  {i+1}. {t.name} (weight={t.weight})")
            print(f"     cmd:    {t.command}")
            print(f"     expect: {t.assertion}")
            if t.description:
                print(f"     desc:   {t.description}")

    else:
        print(f"Unknown command: {cmd}")
        print("Run 'test_harness.py' with no args for usage.")


if __name__ == "__main__":
    main()
