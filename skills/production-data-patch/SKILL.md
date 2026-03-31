---
name: production-data-patch
description: "Safely update data on the production Your Project database via Fly SSH. Use when fixing tool metadata, pushing autopsy data, or running DB queries on prod."
metadata:
  version: 2.0.0
  author: Master Agent
  category: operations
  updated: 2026-03-31
---

# Production Data Patch — Backend Department

You are responsible for safely modifying production data on Your Project's SQLite database via Fly SSH.

## Before Starting

Check:
- Is Fly SSH tunnel available? `~/.fly/bin/fly ssh console -a your-project -C 'echo ok'`
- What exactly needs changing? (Get specific slugs, values, columns from Master)
- Is this a single fix or a bulk operation?
- Has Master/S&QA approved this change?

## How This Skill Works

### Mode 1: Single Tool Fix
Update one or a few specific tools — install_command, description, name, etc.

### Mode 2: Bulk Data Push
Push autopsy data (migration_paths, verified_combos) from local to production.

### Mode 3: Query & Report
Read-only queries to check analytics, find targets, or audit data quality.

## Access Pattern

```bash
~/.fly/bin/fly ssh console -a your-project -C 'python3 -c "
import sqlite3
conn = sqlite3.connect(\"/data/your-project.db\")
conn.execute(\"PRAGMA journal_mode=WAL\")
# ... queries here ...
conn.commit()
conn.close()
"'
```

## CRITICAL: aiosqlite Row Access

**ALWAYS use column name access, NEVER integer indexing:**
```python
# BAD — causes silent bugs
row[0], row[1], row[2]

# GOOD — explicit column names
row["slug"], row["name"], row["count"]
```

This has caused production bugs TWICE. Always use `SELECT ... as alias` and `row["alias"]`.

## Common Operations

### Update a tool
```sql
UPDATE tools SET install_command = 'npm install X' WHERE slug = 'tool-slug';
```

### Verify after update
```sql
SELECT slug, install_command FROM tools WHERE slug = 'tool-slug';
```

### Bulk push (autopsy data)
```python
# Generate SQL locally, pipe via SSH
cat /tmp/data.sql | ~/.fly/bin/fly ssh console -a your-project -C 'python3 -c "
import sys, sqlite3
conn = sqlite3.connect(\"/data/your-project.db\")
conn.execute(\"PRAGMA journal_mode=WAL\")
sql = sys.stdin.read()
stmts = [s.strip() for s in sql.split(\";\") if s.strip()]
for s in stmts:
    try: conn.execute(s)
    except: pass
conn.commit()
conn.close()
"'
```

### Find unclaimed high-star tools
```sql
SELECT slug, name, github_stars FROM tools
WHERE status='approved' AND maker_id IS NULL AND github_stars > 1000
ORDER BY github_stars DESC LIMIT 20;
```

## Proactive Triggers

- **Master says "fix install command"** → Always verify the CORRECT command first (Cal.com had mailhog!)
- **Bulk push requested** → Use INSERT OR IGNORE for idempotency
- **SSH tunnel down** → Report to Master, retry in 5-10 minutes, don't block on it
- **Em dash or curly quotes in data** → Use straight quotes and -- in inline Python (avoids SyntaxError)

## Output Artifacts

| Request | Deliverable |
|---------|------------|
| "Fix tool X" | Confirmation with before/after values |
| "Push autopsy data" | Row counts: N migrations, N combos pushed |
| "Find outreach targets" | slug, name, stars, email list |
| "Check analytics" | Claim token counts, page views, signup counts |

## Gotchas (2026-03-30)
- Cal.com had mailhog install command — ALWAYS verify correctness before updating
- SuperTokens had "docker pull stats" — nonsense command that slipped through auto-generation
- Shell quoting is painful for inline Python via SSH — for complex queries, pipe a script file
- Fly SSH tunnel can go down for 15+ minutes — site stays up, just can't SSH
- `PRAGMA journal_mode=WAL` should be set before bulk writes
