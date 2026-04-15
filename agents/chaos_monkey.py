#!/usr/bin/env python3
"""
Chaos Monkey — Your Project Security Probe
Authorized security testing of Your Project production endpoints.
Run only when authorised by the operator or Master agent.

Tests: SQL injection, XSS, rate limiting, auth bypass, CSRF, path traversal.
Output: /tmp/chaos_monkey_report.md

Usage: python3 scripts/chaos_monkey.py
"""

import urllib.request
import urllib.parse
import urllib.error
import time
import threading
import datetime
import sys

TARGET = "https://your-project.fly.dev"
REPORT_PATH = "/tmp/chaos_monkey_report.md"
TIMEOUT = 5

results = []


def req(method, path, headers=None, body=None):
    """Make a single HTTP request. Returns (status_code, response_body_snippet)."""
    url = TARGET + path
    data = body.encode() if isinstance(body, str) else body
    rq = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(rq, timeout=TIMEOUT) as resp:
            body_bytes = resp.read(4096)
            return resp.status, body_bytes.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_bytes = e.read(2048) if e.fp else b""
        return e.code, body_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


def record(test_name, passed, detail):
    status = "PASS" if passed else "FAIL"
    results.append({"test": test_name, "status": status, "detail": detail})
    mark = "✅" if passed else "❌"
    print(f"  {mark} [{status}] {test_name}: {detail}")


# ── Test 1: SQL Injection ───────────────────────────────────────────────────

def test_sql_injection():
    print("\n[1] SQL Injection")
    payloads = [
        ("basic OR", "' OR '1'='1"),
        ("drop table", "'; DROP TABLE tools; --"),
        ("union select", "1 UNION SELECT name, slug FROM tools--"),
        ("encoded quote", "%27 OR 1=1 --"),
    ]
    for label, payload in payloads:
        path = "/api/tools/search?q=" + urllib.parse.quote(payload)
        code, body = req("GET", path)
        # PASS: 200 with normal JSON (no SQL error), or 400/422 validation error
        # FAIL: SQL error message in body, or server error (500)
        sql_error = any(k in body.lower() for k in [
            "syntax error", "sqlite", "operationalerror", "no such table",
            "unrecognized token", "you have an error in your sql"
        ])
        if code == 500 or sql_error:
            record(f"SQL injection ({label})", False,
                   f"HTTP {code} — possible SQL error in response")
        else:
            record(f"SQL injection ({label})", True,
                   f"HTTP {code} — no SQL error exposed")


# ── Test 2: XSS Probe ──────────────────────────────────────────────────────

def test_xss():
    print("\n[2] XSS Probe")
    payloads = [
        ("script tag", "<script>alert(1)</script>"),
        ("img onerror", "<img src=x onerror=alert(1)>"),
        ("svg xss", "<svg/onload=alert(1)>"),
    ]
    for label, payload in payloads:
        path = "/api/tools/search?q=" + urllib.parse.quote(payload, safe="")
        code, body = req("GET", path)
        if code is None:
            record(f"XSS ({label})", False,
                   f"HTTP None — request failed (inconclusive, manual check required)")
            continue
        # API returns JSON — check the raw payload isn't reflected unescaped
        raw_reflected = payload.lower() in body.lower()
        if raw_reflected:
            record(f"XSS ({label})", False,
                   f"HTTP {code} — raw payload reflected in response")
        else:
            record(f"XSS ({label})", True,
                   f"HTTP {code} — payload not reflected raw (sanitised or absent)")


# ── Test 3: Rate Limiting ──────────────────────────────────────────────────

def test_rate_limit():
    print("\n[3] Rate Limit (20 requests in ~2s)")
    statuses = []
    lock = threading.Lock()

    def fire():
        code, _ = req("GET", "/api/tools/search?q=auth")
        with lock:
            statuses.append(code)

    threads = [threading.Thread(target=fire) for _ in range(20)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0

    rate_limited = statuses.count(429)
    all_200 = all(s == 200 for s in statuses if s is not None)

    if all_200:
        record("Rate limiting", False,
               f"All {len(statuses)} requests returned 200 — no rate limit enforced "
               f"({elapsed:.1f}s burst)")
    else:
        record("Rate limiting", True,
               f"{rate_limited}/20 requests hit 429 in {elapsed:.1f}s — "
               f"rate limiting active")


# ── Test 4: Auth Bypass ────────────────────────────────────────────────────

def test_auth_bypass():
    print("\n[4] Auth Bypass")
    protected = [
        ("/admin",            "admin panel"),
        ("/admin/analytics",  "admin analytics"),
        ("/dashboard",        "user dashboard"),
    ]
    for path, label in protected:
        code, body = req("GET", path)
        # PASS: 401, 403, or redirect to /login (302/303)
        # FAIL: 200 with protected content rendered
        if code is None:
            record(f"Auth bypass ({label})", False,
                   f"HTTP None — request failed (inconclusive)")
        elif code == 200:
            # Heuristic: if "log in", "login", "sign in" appears it's the login page
            looks_like_login = any(k in body.lower() for k in ["log in", "login", "sign in", "github"])
            if looks_like_login:
                record(f"Auth bypass ({label})", True,
                       f"HTTP {code} — shows login page, not protected content")
            else:
                record(f"Auth bypass ({label})", False,
                       f"HTTP {code} — returned 200 without auth (check manually)")
        elif code in (301, 302, 303, 307, 308):
            record(f"Auth bypass ({label})", True,
                   f"HTTP {code} — redirects (likely to /login)")
        elif code in (401, 403):
            record(f"Auth bypass ({label})", True,
                   f"HTTP {code} — access denied correctly")
        else:
            record(f"Auth bypass ({label})", True,
                   f"HTTP {code} — not accessible without auth")

    # Forged cookie attempt on /admin
    code, body = req("GET", "/admin", headers={"Cookie": "session=aaaaaaaaaaaaaaaa"})
    if code == 200 and not any(k in body.lower() for k in ["log in", "login", "sign in", "github"]):
        record("Auth bypass (forged cookie)", False,
               f"HTTP {code} — forged cookie not rejected")
    else:
        record("Auth bypass (forged cookie)", True,
               f"HTTP {code} — forged cookie correctly rejected")


# ── Test 5: CSRF Check ─────────────────────────────────────────────────────

def test_csrf():
    print("\n[5] CSRF Check")
    # POST to /api/agent/outcome without Origin or Referer — should require auth
    code, body = req(
        "POST",
        "/api/agent/outcome",
        headers={"Content-Type": "application/json"},
        body='{"tool_slug":"test","outcome":"adopted"}'
    )
    # PASS: 401 (needs API key) or 400 (bad request)
    # FAIL: 200 — processed the request without any auth
    if code == 200:
        record("CSRF (no-origin POST)", False,
               f"HTTP {code} — unauthenticated POST accepted without Origin header")
    elif code in (400, 401, 403, 422):
        record("CSRF (no-origin POST)", True,
               f"HTTP {code} — unauthenticated request rejected correctly")
    else:
        record("CSRF (no-origin POST)", True,
               f"HTTP {code} — not processed without auth")


# ── Test 6: Path Traversal ─────────────────────────────────────────────────

def test_path_traversal():
    print("\n[6] Path Traversal")
    payloads = [
        ("etc/passwd (encoded)", "/api/tools/..%2F..%2Fetc%2Fpasswd"),
        ("etc/passwd (raw)",     "/api/tools/../../etc/passwd"),
        ("double encoded",       "/api/tools/%2E%2E%2F%2E%2E%2Fetc%2Fpasswd"),
    ]
    for label, path in payloads:
        code, body = req("GET", path)
        # FAIL: file contents in response (root: or /bin/bash markers)
        traversal_success = any(k in body for k in [
            "root:", "/bin/bash", "/bin/sh", "nobody:", "daemon:"
        ])
        if traversal_success:
            record(f"Path traversal ({label})", False,
                   f"HTTP {code} — file contents returned!")
        else:
            record(f"Path traversal ({label})", True,
                   f"HTTP {code} — no file contents in response")


# ── Report Writer ──────────────────────────────────────────────────────────

def write_report():
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)

    lines = [
        f"# Chaos Monkey Security Report",
        f"",
        f"**Target:** {TARGET}",
        f"**Run at:** {now}",
        f"**Result:** {passed}/{total} PASS — {failed} FAIL(s)",
        f"",
    ]

    if failed == 0:
        lines += [
            "## Summary",
            "",
            "All checks passed. No exploitable vulnerabilities found in tested vectors.",
            "",
        ]
    else:
        lines += [
            "## Summary",
            "",
            f"**{failed} test(s) FAILED** — review findings below.",
            "",
        ]

    lines += ["## Findings", ""]
    for r in results:
        icon = "✅" if r["status"] == "PASS" else "❌"
        lines.append(f"- {icon} **{r['status']}** — {r['test']}: {r['detail']}")

    lines += [
        "",
        "## Vectors Tested",
        "",
        "1. SQL injection — search API with common payloads",
        "2. XSS — reflected XSS in search API response",
        "3. Rate limiting — 20 concurrent requests to search",
        "4. Auth bypass — protected routes without session (+ forged cookie)",
        "5. CSRF — unauthenticated POST to agent outcome endpoint",
        "6. Path traversal — /api/tools/ with ../../../etc/passwd variants",
        "",
        "---",
        "*Generated by scripts/chaos_monkey.py*",
    ]

    report = "\n".join(lines)
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    return report


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print(f"Chaos Monkey — {TARGET}")
    print(f"Started: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    test_sql_injection()
    test_xss()
    test_rate_limit()
    test_auth_bypass()
    test_csrf()
    test_path_traversal()

    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    print(f"Results: {passed}/{len(results)} PASS — {failed} FAIL(s)")

    report = write_report()
    print(f"\nReport written to {REPORT_PATH}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
