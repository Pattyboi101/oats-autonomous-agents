---
name: agent-experience-audit
description: "Audit the MCP server experience from an agent's perspective. Use when checking search quality, response richness, or first-impression for new MCP installs."
metadata:
  version: 1.0.0
  author: Master Agent
  category: product-quality
  updated: 2026-03-30
---

# Agent Experience Audit — MCP Dept

You audit what AI agents see when they use Your Project's MCP server. Your goal is to ensure every interaction is obviously better than a raw web search.

## Before Starting

- Is production up? Check /health endpoint
- Is SSH available? Try a quick fly ssh command
- What's the context? (New registry listing, post-outreach, routine check)

## How This Skill Works

### Mode 1: Search Quality Audit
Test the top 5 search queries (auth, analytics, payments, email, database). For each: is the top result relevant? Does it have install_command? Is the tagline useful?

### Mode 2: Tool Detail Audit
Pick specific tools (e.g. the 13 we emailed) and check their full detail response. Are descriptions accurate? Are migration signals present? Are compatible tools shown?

### Mode 3: First-Install Experience
Simulate a developer who just installed from Smithery/Glama. What's their first query? What do they see? Would they keep using us?

## Audit Checklist

### Per Search Query
| Check | Pass | Fail |
|-------|------|------|
| Top result is relevant to query? | Auth → auth tool | Auth → Airflow |
| Top result has install_command? | `npm install X` | Empty |
| Top result has useful tagline? | Describes what it does | Truncated or generic |
| Category is correct? | Analytics → Analytics | Analytics → AI & Automation |
| Migration signal present? | "14 repos migrated from X" | Empty (acceptable if no data) |

### Per Tool Detail
| Check | Pass | Fail |
|-------|------|------|
| Description > tagline? | Full paragraph | Same as tagline |
| Install command correct? | Matches actual package | Wrong package entirely |
| Migration data present? | Gaining/losing signals | Empty (check sdk_packages mapping) |
| Verified combos present? | "Works with X in N repos" | Empty |
| Trust tier shown? | "New/Tested/Verified" | Missing |

## Query via Production

```bash
# Search test
~/.fly/bin/fly ssh console -a your-project -C 'python3 -c "
import urllib.request, json
r = urllib.request.urlopen(\"http://localhost:8080/api/tools/search?q={query}&limit=5\")
data = json.loads(r.read())
for t in data.get(\"tools\", []):
    print(t.get(\"slug\") + \": \" + str(t.get(\"migration_signal\", \"no signal\")))
"'
```

## Proactive Triggers
- **New tools added to catalog** → Check they have install_command before they show in search
- **Migration data pushed** → Verify signals appear in search results (check Row access pattern)
- **Registry listing approved** → Run Mode 3 (first-install audit) immediately
- **Maker outreach sent** → Run Mode 2 on emailed tool pages

## Common Issues Found (2026-03-30)
1. Plausible Analytics stored as just "Analytics" — no product identity
2. ClickHouse miscategorised as "AI & Automation"
3. Payment tools (Killbill, Flowglad, dj-stripe) had 0/3 install commands
4. Migration signals used row[0] instead of row["column"] — returned NONE for everything
5. Cal.com had mailhog install command (wrong tool entirely)
