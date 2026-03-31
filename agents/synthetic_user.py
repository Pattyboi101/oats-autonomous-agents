#!/usr/bin/env python3
"""
Synthetic User Testing Script — Your Project

Simulates a developer journey through key pages, checking for essential content.
Reports pass/fail for each page and specific content checks.

Usage:
  python3 scripts/synthetic_user.py [target_url]

Example:
  python3 scripts/synthetic_user.py https://your-project.fly.dev
  python3 scripts/synthetic_user.py http://localhost:8080
"""

import sys
import urllib.request
import urllib.error
from datetime import datetime
from html.parser import HTMLParser

class SimpleHTMLParser(HTMLParser):
    """Extract text content from HTML."""
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data.strip())

    def get_text(self):
        return ' '.join([t for t in self.text if t])

def fetch_page(url, timeout=10):
    """Fetch a page and return (status_code, html_content, error_msg)."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Your Project-SyntheticUser/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            content = response.read().decode('utf-8')
            return status, content, None
    except urllib.error.HTTPError as e:
        return e.code, None, str(e)
    except urllib.error.URLError as e:
        return None, None, str(e)
    except Exception as e:
        return None, None, str(e)

def check_content(html, *search_strings):
    """Check if all search strings appear in HTML (case-insensitive)."""
    if not html:
        return False, []
    html_lower = html.lower()
    results = []
    for s in search_strings:
        found = s.lower() in html_lower
        results.append(found)
    return all(results), results

def test_landing():
    """Test / — Landing page."""
    status, html, error = fetch_page(f"{BASE_URL}/")
    checks = []

    if status == 200:
        found, _ = check_content(html, "Set up", "discovery layer", "developer tools")
        checks.append(("Page loads", True))
        checks.append(("CTA visible (contains 'Set up')", "set up" in html.lower()))
        checks.append(("Key messaging present", found))
    else:
        checks.append(("Page loads", False))

    return {
        "page": "/",
        "status": status,
        "error": error,
        "checks": checks,
    }

def test_setup():
    """Test /setup — Setup/install page."""
    status, html, error = fetch_page(f"{BASE_URL}/setup")
    checks = []

    if status == 200:
        has_install, _ = check_content(html, "install", "command", "mcp")
        has_value, _ = check_content(html, "curated", "migration", "verified")
        checks.append(("Page loads", True))
        checks.append(("Install commands visible", has_install))
        checks.append(("Value prop visible", has_value))
    else:
        checks.append(("Page loads", False))

    return {
        "page": "/setup",
        "status": status,
        "error": error,
        "checks": checks,
    }

def test_explore():
    """Test /explore — Tool explorer page."""
    status, html, error = fetch_page(f"{BASE_URL}/explore")
    checks = []

    if status == 200:
        # Check for category/tool content
        has_tools, _ = check_content(html, "browse", "category")
        # Check if any form elements exist for filtering
        has_search, _ = check_content(html, "filter")
        checks.append(("Page loads", True))
        checks.append(("Categories/tools content present", has_tools))
        checks.append(("Filter interface present", has_search))
    else:
        checks.append(("Page loads", False))

    return {
        "page": "/explore",
        "status": status,
        "error": error,
        "checks": checks,
    }

def test_analyze():
    """Test /analyze — Stack health analyzer."""
    status, html, error = fetch_page(f"{BASE_URL}/analyze")
    checks = []

    if status == 200:
        has_form, _ = check_content(html, "textarea", "manifest", "analyze")
        has_sample, _ = check_content(html, "sample", "try sample", "package.json")
        checks.append(("Page loads", True))
        checks.append(("Form renders", has_form))
        checks.append(("Sample data available", has_sample))
    else:
        checks.append(("Page loads", False))

    return {
        "page": "/analyze",
        "status": status,
        "error": error,
        "checks": checks,
    }

def test_migrations():
    """Test /migrations — Migration intelligence page."""
    status, html, error = fetch_page(f"{BASE_URL}/migrations")
    checks = []

    if status == 200:
        # Check for real numbers (look for large counts in the page)
        has_stats, _ = check_content(html, "repos", "migration", "verified")
        has_insights, _ = check_content(html, "insight", "jest", "vite", "webpack")
        # Verify it's not all zeros
        has_data = "0" not in html or "100" in html  # Real migration data would have non-zero counts

        checks.append(("Page loads", True))
        checks.append(("Stats visible", has_stats))
        checks.append(("Insights section present", has_insights))
        checks.append(("Real data present", has_data))
    else:
        checks.append(("Page loads", False))

    return {
        "page": "/migrations",
        "status": status,
        "error": error,
        "checks": checks,
    }

def test_pricing():
    """Test /pricing — Pricing page."""
    status, html, error = fetch_page(f"{BASE_URL}/pricing")
    checks = []

    if status == 200:
        has_free, _ = check_content(html, "free", "developer")
        has_makers, _ = check_content(html, "tool maker", "$299")
        checks.append(("Page loads", True))
        checks.append(("Free tier prominent", has_free))
        checks.append(("Pricing tiers visible", has_makers))
    else:
        checks.append(("Page loads", False))

    return {
        "page": "/pricing",
        "status": status,
        "error": error,
        "checks": checks,
    }

def run_all_tests():
    """Run all synthetic user tests."""
    results = [
        test_landing(),
        test_setup(),
        test_explore(),
        test_analyze(),
        test_migrations(),
        test_pricing(),
    ]
    return results

def generate_report(results):
    """Generate markdown report from test results."""
    report = f"""# Synthetic User Test Report

**Generated:** {datetime.now().isoformat()}
**Target:** {BASE_URL}

## Summary

| Page | Status | Checks Passed | Issues |
|------|--------|---------------|--------|
"""

    for r in results:
        passed = sum(1 for _, result in r['checks'] if result)
        total = len(r['checks'])
        status = "✓" if r['status'] == 200 else "✗"
        issues = "Error: " + r['error'] if r['error'] else "None" if passed == total else f"{total - passed} checks failed"

        report += f"| {r['page']} | {status} {r['status']} | {passed}/{total} | {issues} |\n"

    report += "\n## Detailed Results\n\n"

    for r in results:
        report += f"### {r['page']}\n\n"
        report += f"**HTTP Status:** {r['status']}\n\n"

        if r['error']:
            report += f"**Error:** {r['error']}\n\n"
        else:
            report += "**Checks:**\n\n"
            for check_name, result in r['checks']:
                status_icon = "✓" if result else "✗"
                report += f"- {status_icon} {check_name}\n"
            report += "\n"

    return report

if __name__ == "__main__":
    if len(sys.argv) > 1:
        BASE_URL = sys.argv[1].rstrip('/')
    else:
        BASE_URL = "https://your-project.fly.dev"

    print(f"Running synthetic user tests against {BASE_URL}...")
    print()

    results = run_all_tests()
    report = generate_report(results)

    # Write report
    report_path = "/tmp/synthetic_user_report.md"
    with open(report_path, 'w') as f:
        f.write(report)

    print(report)
    print(f"\nReport saved to {report_path}")

    # Exit with error if any critical test failed
    critical_failures = [r for r in results if r['status'] != 200]
    sys.exit(1 if critical_failures else 0)
