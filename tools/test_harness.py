#!/usr/bin/env python3
"""Test Harness — iterative test-driven quality improvement for OATS agents.

Real-world lesson: we improved search quality from 2/10 to 10/10
by running the same 10-query test suite after every change. This tool
codifies that pattern — define assertions, run them, iterate until 100%.

The loop: define tests once, run after every change, fix what fails,
re-run until green. Each run is tracked so you can see quality over time.

Assertion types:
    contains:<string>           — stdout contains the string
    not_contains:<string>       — stdout does NOT contain the string
    exit:0                      — command exits with code 0
    regex:<pattern>             — stdout matches regex
    json_path:<path>=<value>    — JSON output at path equals value

Test suites persist at .oats/test_harnesses/{name}.json.

Usage:
    python3 tools/test_harness.py define search-quality --desc "Search tests"
    python3 tools/test_harness.py add search-quality \\
        --test stripe-appears --cmd "curl -s localhost:8000/api/search?q=payments" \\
        --expect "contains:Stripe" --weight 8
    python3 tools/test_harness.py run search-quality
    python3 tools/test_harness.py score search-quality
    python3 tools/test_harness.py history search-quality
    python3 tools/test_harness.py iterate search-quality --fix "python3 scripts/rebuild_index.py"
    python3 tools/test_harness.py list
    python3 tools/test_harness.py show search-quality
"""

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

HARNESS_DIR = Path(".oats/test_harnesses")


# --- Data classes ---

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


# --- Assertion engine ---

def _check_assertion(assertion: str, stdout: str, exit_code: int) -> tuple:
    """Evaluate an assertion. Returns (passed, error_message)."""
    if not assertion:
        return True, ""

    if assertion.startswith("contains:"):
        expected = assertion[9:]
        return (True, "") if expected in stdout else (False, f"stdout missing '{expected}'")

    if assertion.startswith("not_contains:"):
        bad = assertion[13:]
        return (True, "") if bad not in stdout else (False, f"stdout contains '{bad}'")

    if assertion.startswith("exit:"):
        want = int(assertion[5:])
        return (True, "") if exit_code == want else (False, f"exit {exit_code}, want {want}")

    if assertion.startswith("regex:"):
        pat = assertion[6:]
        return (True, "") if re.search(pat, stdout) else (False, f"no match for /{pat}/")

    if assertion.startswith("json_path:"):
        spec = assertion[10:]
        if "=" not in spec:
            return False, f"json_path needs path=value, got '{spec}'"
        path_str, expected = spec.split("=", 1)
        return _check_json_path(stdout, path_str, expected)

    return False, f"unknown assertion: '{assertion}'"


def _check_json_path(stdout: str, path_str: str, expected: str) -> tuple:
    """Navigate dot.notation[0] path in JSON and compare value."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError) as e:
        return False, f"not valid JSON: {e}"

    segments = []
    for part in path_str.split("."):
        if not part:
            continue
        m = re.match(r"^(\w+)\[(\d+)\]$", part)
        if m:
            segments.extend([m.group(1), int(m.group(2))])
        else:
            segments.append(part)

    cur = data
    for seg in segments:
        try:
            cur = cur[seg]
        except (KeyError, IndexError, TypeError) as e:
            return False, f"path '{path_str}' not found: {e}"

    actual = str(cur)
    return (True, "") if actual == expected else (False, f"'{path_str}': '{actual}' != '{expected}'")


# --- TestSuite ---

class TestSuite:
    """Named collection of test cases, persisted to disk."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.tests: list[TestCase] = []

    def add_test(self, test: TestCase):
        self.tests = [t for t in self.tests if t.name != test.name]
        self.tests.append(test)

    def remove_test(self, name: str) -> bool:
        n = len(self.tests)
        self.tests = [t for t in self.tests if t.name != name]
        return len(self.tests) < n

    def save(self):
        HARNESS_DIR.mkdir(parents=True, exist_ok=True)
        path = HARNESS_DIR / f"{self.name}.json"
        path.write_text(json.dumps({
            "name": self.name, "description": self.description,
            "tests": [asdict(t) for t in self.tests],
        }, indent=2))

    @classmethod
    def load(cls, name: str) -> "TestSuite":
        path = HARNESS_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Suite '{name}' not found at {path}")
        data = json.loads(path.read_text())
        suite = cls(data["name"], data.get("description", ""))
        for t in data.get("tests", []):
            suite.tests.append(TestCase(**t))
        return suite

    @classmethod
    def list_all(cls) -> list[str]:
        if not HARNESS_DIR.exists():
            return []
        return sorted(f.stem for f in HARNESS_DIR.glob("*.json")
                       if not f.stem.endswith("_history"))


# --- TestRunner ---

class TestRunner:
    """Execute test suites and track results over time."""

    def __init__(self):
        self._tracer = None

    def _get_tracer(self):
        if self._tracer is None:
            try:
                from tools.tracer import Tracer
                self._tracer = Tracer(f"test-{int(time.time())}")
            except Exception:
                self._tracer = False
        return self._tracer if self._tracer else None

    def run(self, suite_name: str) -> list[TestResult]:
        """Run all tests in a suite, print results, record history."""
        suite = TestSuite.load(suite_name)
        print(f"Test Suite: {suite.name}")
        if suite.description:
            print(f"  {suite.description}")
        print(f"  Tests: {len(suite.tests)}\n")

        results = [self._run_one(t, i + 1, len(suite.tests))
                    for i, t in enumerate(suite.tests)]

        # Tracer integration
        tracer = self._get_tracer()
        if tracer:
            p = sum(1 for r in results if r.passed)
            tracer.record("test_harness", "test_run",
                          {"suite": suite_name, "tests": len(results)},
                          {"passed": p, "failed": len(results) - p})

        self._save_history(suite_name, results)
        passed = sum(1 for r in results if r.passed)
        print(f"\n  Result: {passed}/{len(results)} passed")
        for r in results:
            if not r.passed:
                print(f"    FAIL: {r.name} — {r.error}")
        return results

    def _run_one(self, test: TestCase, idx: int, total: int) -> TestResult:
        print(f"  [{idx}/{total}] {test.name}...", end=" ", flush=True)
        start = time.time()
        try:
            proc = subprocess.run(test.command, shell=True,
                                   capture_output=True, text=True,
                                   timeout=test.timeout)
            ms = int((time.time() - start) * 1000)
            ok, err = _check_assertion(test.assertion, proc.stdout, proc.returncode)
            res = TestResult(name=test.name, passed=ok, assertion=test.assertion,
                             weight=test.weight, stdout=proc.stdout[:2000],
                             stderr=proc.stderr[:500], exit_code=proc.returncode,
                             duration_ms=ms, error=err)
        except subprocess.TimeoutExpired:
            ms = int((time.time() - start) * 1000)
            res = TestResult(name=test.name, passed=False, assertion=test.assertion,
                             weight=test.weight, duration_ms=ms,
                             error=f"timeout after {test.timeout}s")
        except Exception as e:
            ms = int((time.time() - start) * 1000)
            res = TestResult(name=test.name, passed=False, assertion=test.assertion,
                             weight=test.weight, duration_ms=ms, error=str(e))
        print(f"{'PASS' if res.passed else 'FAIL'} ({res.duration_ms}ms)")
        return res

    def score(self, suite_name: str) -> dict:
        """Pass rate from last recorded run."""
        hist = self._load_history(suite_name)
        if not hist:
            return {"suite": suite_name, "score": "no runs yet"}
        last = hist[-1]
        return {"suite": suite_name, "score": f"{last['passed']}/{last['total']}",
                "rate": f"{last['score']:.0%}",
                "weighted_rate": f"{last['weighted_score']:.0%}",
                "last_run": last["timestamp"]}

    def iterate(self, suite_name: str, fix_command: str,
                max_iterations: int = 10) -> dict:
        """Run tests -> fix -> retest until 100% or max iterations."""
        print(f"Iterate: {suite_name} (max {max_iterations})\n")
        log = []
        for i in range(1, max_iterations + 1):
            print(f"--- Iteration {i}/{max_iterations} ---\n")
            results = self.run(suite_name)
            p, t = sum(1 for r in results if r.passed), len(results)
            log.append({"iteration": i, "passed": p, "total": t})

            if p == t:
                print(f"\n  Converged after {i} iteration(s).")
                return {"status": "converged", "iterations": i,
                        "final_score": f"{p}/{t}", "log": log}

            print(f"\n  Applying fix: {fix_command}")
            try:
                r = subprocess.run(fix_command, shell=True,
                                    capture_output=True, text=True, timeout=120)
                print(f"  {'Fix applied.' if r.returncode == 0 else f'Fix failed (exit {r.returncode})'}\n")
            except subprocess.TimeoutExpired:
                print("  Fix timed out.\n")

        print(f"  Did not converge after {max_iterations} iterations.")
        return {"status": "max_iterations", "iterations": max_iterations,
                "final_score": f"{log[-1]['passed']}/{log[-1]['total']}", "log": log}

    def history(self, suite_name: str) -> list[dict]:
        return self._load_history(suite_name)

    def _save_history(self, suite_name: str, results: list[TestResult]):
        p = sum(1 for r in results if r.passed)
        t = len(results)
        wp = sum(r.weight for r in results if r.passed)
        wt = sum(r.weight for r in results)
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "passed": p, "failed": t - p, "total": t,
            "score": p / t if t else 0,
            "weighted_score": wp / wt if wt else 0,
            "duration_ms": sum(r.duration_ms for r in results),
            "results": [{"name": r.name, "passed": r.passed, "error": r.error}
                         for r in results],
        }
        hist = self._load_history(suite_name)
        hist.append(record)
        HARNESS_DIR.mkdir(parents=True, exist_ok=True)
        (HARNESS_DIR / f"{suite_name}_history.json").write_text(
            json.dumps(hist, indent=2))

    def _load_history(self, suite_name: str) -> list[dict]:
        f = HARNESS_DIR / f"{suite_name}_history.json"
        if not f.exists():
            return []
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, ValueError):
            return []


# --- CLI helpers ---

def _parse_flags(args: list, *flag_names) -> dict:
    """Parse --flag value pairs from args list."""
    result = {}
    i = 0
    while i < len(args):
        for name in flag_names:
            if args[i] == f"--{name}" and i + 1 < len(args):
                result[name] = args[i + 1]
                i += 2
                break
        else:
            i += 1
    return result


def main():
    if len(sys.argv) < 2:
        print("Test Harness — iterative test-driven quality improvement\n")
        print("Usage:")
        print("  test_harness.py define <name> [--desc <description>]")
        print("  test_harness.py add <name> --test <n> --cmd <c> --expect <a> [--weight N]")
        print("  test_harness.py remove <name> --test <test_name>")
        print("  test_harness.py run <name>         # execute all tests")
        print("  test_harness.py score <name>       # last pass rate")
        print("  test_harness.py history <name>     # runs over time")
        print("  test_harness.py iterate <name> --fix <cmd> [--max N]")
        print("  test_harness.py list | show <name>\n")
        print("Assertions: contains:, not_contains:, exit:, regex:, json_path:path=val")
        return

    cmd, args = sys.argv[1], sys.argv[2:]

    if cmd == "define":
        if not args:
            print("Usage: test_harness.py define <name>"); return
        flags = _parse_flags(args[1:], "desc", "from")
        suite = TestSuite(args[0], flags.get("desc", ""))
        if "from" in flags:
            p = Path(flags["from"])
            if p.exists():
                data = json.loads(p.read_text())
                for t in data.get("tests", data if isinstance(data, list) else []):
                    suite.add_test(TestCase(**t))
        suite.save()
        print(f"Suite '{args[0]}' created ({len(suite.tests)} tests).")

    elif cmd == "add":
        if not args:
            print("Usage: test_harness.py add <name> --test .. --cmd .. --expect .."); return
        try:
            suite = TestSuite.load(args[0])
        except FileNotFoundError:
            print(f"Suite '{args[0]}' not found. Run: test_harness.py define {args[0]}"); return
        f = _parse_flags(args[1:], "test", "cmd", "expect", "weight", "timeout", "desc")
        if not all(k in f for k in ("test", "cmd", "expect")):
            print("Required: --test, --cmd, --expect"); return
        suite.add_test(TestCase(name=f["test"], command=f["cmd"], assertion=f["expect"],
                                 weight=int(f.get("weight", 5)),
                                 timeout=int(f.get("timeout", 30)),
                                 description=f.get("desc", "")))
        suite.save()
        print(f"Test '{f['test']}' added ({len(suite.tests)} total).")

    elif cmd == "remove":
        if not args:
            print("Usage: test_harness.py remove <name> --test <n>"); return
        try:
            suite = TestSuite.load(args[0])
        except FileNotFoundError:
            print(f"Suite '{args[0]}' not found."); return
        f = _parse_flags(args[1:], "test")
        if "test" not in f:
            print("Required: --test <name>"); return
        if suite.remove_test(f["test"]):
            suite.save()
            print(f"Removed '{f['test']}'. {len(suite.tests)} remaining.")
        else:
            print(f"Test '{f['test']}' not found.")

    elif cmd == "run":
        if not args:
            print("Usage: test_harness.py run <name>"); return
        TestRunner().run(args[0])

    elif cmd == "score":
        if not args:
            print("Usage: test_harness.py score <name>"); return
        info = TestRunner().score(args[0])
        print(f"Suite: {info['suite']}")
        if "rate" in info:
            print(f"  Score: {info['score']} ({info['rate']}), weighted: {info['weighted_rate']}")
            print(f"  Last run: {info['last_run']}")
        else:
            print(f"  {info['score']}")

    elif cmd == "history":
        if not args:
            print("Usage: test_harness.py history <name>"); return
        records = TestRunner().history(args[0])
        if not records:
            print(f"No history for '{args[0]}'."); return
        print(f"History: {args[0]} ({len(records)} runs)\n")
        print(f"  {'#':>3}  {'Timestamp':19}  {'Score':>7}  {'Rate':>6}  {'Time':>7}")
        for i, r in enumerate(records):
            print(f"  {i+1:3d}  {r['timestamp'][:19]:19}  "
                  f"{r['passed']}/{r['total']:>5}  {r['score']:>5.0%}  "
                  f"{r['duration_ms']:>5}ms")
        if len(records) >= 2:
            d = records[-1]["score"] - records[0]["score"]
            trend = "improved" if d > 0 else "declined" if d < 0 else "unchanged"
            print(f"\n  Trend: {records[0]['score']:.0%} -> {records[-1]['score']:.0%} ({trend})")

    elif cmd == "iterate":
        if not args:
            print("Usage: test_harness.py iterate <name> --fix <cmd>"); return
        f = _parse_flags(args[1:], "fix", "max")
        if "fix" not in f:
            print("Required: --fix <command>"); return
        result = TestRunner().iterate(args[0], f["fix"], int(f.get("max", 10)))
        print(f"\n  Status: {result['status']} | Iterations: {result['iterations']}"
              f" | Final: {result['final_score']}")

    elif cmd == "list":
        suites = TestSuite.list_all()
        if not suites:
            print("No suites. Create one: test_harness.py define <name>"); return
        print(f"Test suites ({len(suites)}):")
        for n in suites:
            try:
                s = TestSuite.load(n)
                print(f"  {n:20s}  {len(s.tests):2d} tests  {s.description}")
            except Exception:
                print(f"  {n:20s}  (error)")

    elif cmd == "show":
        if not args:
            print("Usage: test_harness.py show <name>"); return
        try:
            s = TestSuite.load(args[0])
        except FileNotFoundError:
            print(f"Suite '{args[0]}' not found."); return
        print(f"Suite: {s.name}" + (f" — {s.description}" if s.description else ""))
        print(f"  Tests: {len(s.tests)}\n")
        for i, t in enumerate(s.tests):
            print(f"  {i+1}. {t.name} (weight={t.weight})")
            print(f"     cmd:    {t.command}")
            print(f"     expect: {t.assertion}")

    else:
        print(f"Unknown command: {cmd}. Run with no args for usage.")


if __name__ == "__main__":
    main()
