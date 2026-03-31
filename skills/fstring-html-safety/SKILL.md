---
name: fstring-html-safety
description: "XSS prevention and HTML safety patterns for Your Project's f-string templates. Use when writing or reviewing any route file that renders HTML."
metadata:
  version: 2.0.0
  author: Master Agent
  category: security
  updated: 2026-03-31
---

# F-String HTML Safety — Frontend Department

You are responsible for preventing XSS vulnerabilities in Your Project's f-string HTML templates. Every route file renders HTML via Python f-strings — this is powerful but dangerous if user data isn't escaped.

## Before Starting

Check:
- Does this route display ANY user-supplied data? (tool names, descriptions, search queries, usernames)
- Are there any `f'<tag>{variable}</tag>'` patterns without `escape()`?
- Is JSON-LD being injected? (needs `json.dumps()`, not `escape()`)

## How This Skill Works

### Mode 1: Writing New Templates
Follow the rules below when creating any new f-string HTML.

### Mode 2: Reviewing Existing Code
Grep for unescaped injections: `{variable}` in HTML context without `escape()`.

### Mode 3: Fixing XSS Bugs
When a vulnerability is found, apply the minimal fix (add `escape()`) without restructuring.

## Core Rules

### 1. Always escape user data
```python
from html import escape
name = escape(tool['name'])  # BEFORE injecting
html = f'<h1>{name}</h1>'
```

### 2. Never hardcode hex colors
```python
# BAD — violates design system
style="color:#00D4F5"

# GOOD — uses CSS variable
style="color:var(--accent)"
```
All CSS variables are in `components.py` `:root` block.

### 3. Touch targets >= 44px
```python
# Every clickable element needs this for mobile
style="min-height:44px;padding:10px 16px;box-sizing:border-box;"
```

### 4. No button inside link
```python
# BAD — invalid HTML
f'<a href="/x"><button>Click</button></a>'

# GOOD — style the link as a button
f'<a href="/x" class="btn-primary">Click</a>'
```

### 5. Python 3.11 f-string limitations
```python
# BAD — backslash in f-string expression
f'<p>{value.replace("x", "y")}</p>'

# GOOD — pre-compute
cleaned = value.replace("x", "y")
f'<p>{cleaned}</p>'
```

### 6. JSON-LD uses json.dumps, not escape
```python
import json
schema = {"@type": "FAQPage", "name": tool_name}  # raw strings OK
json_ld = json.dumps(schema)  # json.dumps handles escaping
html = f'<script type="application/ld+json">{json_ld}</script>'
```

## Proactive Triggers

- **New route file created** → Check every `{variable}` in HTML for escape()
- **User input in URL params** → request.query_params values MUST be escaped before rendering
- **Tool descriptions displayed** → Always escape (makers can put anything in descriptions)
- **Search query shown back to user** → Escape the query text in results header

## Output Artifacts

| Request | Deliverable |
|---------|------------|
| "Review route for XSS" | List of unescaped injections with file:line |
| "Fix XSS in file X" | Minimal escape() additions, syntax verified |
| "New template for page" | Clean f-string HTML following all 6 rules |

## Gotchas (from real experience)

- The security audit on 2026-03-30 found NO confirmed XSS — but that's because most tool data comes from our own ingestion, not user input. As maker-submitted content grows, XSS risk increases.
- `html.escape()` is sufficient for HTML text content. For attribute values, also escape quotes: `escape(value, quote=True)`.
- CSS variable names cannot be injected (they're in `:root`) but CSS VALUES from user data could be. Never put user data in `style=""` attributes without sanitization.

## Verification
After every edit: `python3 -c "import ast; ast.parse(open('file.py').read())"`
