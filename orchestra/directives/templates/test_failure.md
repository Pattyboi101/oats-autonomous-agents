# Directive: Investigate Test Failure

**Priority:** High
**Department:** {{department}}
**Trigger:** CI or smoke test reported failures

## Context

- **Test suite:** {{test_suite}}
- **Failures:** {{failure_count}} / {{total_tests}}
- **Detected at:** {{timestamp}}

## Tasks

1. Read the test output and identify which tests failed
2. For each failure, classify:
   - **Flaky** — passes on retry, no code change needed (but track frequency)
   - **Regression** — previously passing, now broken by a recent change
   - **Environment** — infrastructure issue (network, disk, dependency)
3. For regressions:
   - Identify the commit that introduced the failure (git bisect if needed)
   - Write or update a regression test that catches the specific bug
   - Fix the root cause, not the symptom
4. Run the full test suite to confirm no knock-on failures

## Constraints

- Do NOT skip or disable failing tests without CEO approval
- Do NOT merge to main with known test failures
- If flaky tests exceed 5% of the suite, escalate to Strategy & QA
