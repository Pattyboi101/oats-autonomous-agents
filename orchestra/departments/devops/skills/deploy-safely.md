---
name: deploy-safely
description: "Deploy your project to production safely. Use before any deployment, after code changes, or when asked to push to prod."
metadata:
  version: 2.0.0
  author: Master Agent
  category: operations
  updated: 2026-03-30
---

# Deploy Safely — DevOps

You are responsible for getting code safely to production on Fly.io.

## Before Starting

Check:
- Are there uncommitted changes? `git status`
- Did smoke tests pass? `python3 smoke_test.py`
- Is this approved by Master/S&QA?

## How This Skill Works

### Mode 1: Standard Deploy
Code changes committed, smoke test passing, deploy to Fly.io.

### Mode 2: Hotfix Deploy
Critical bug found, need to deploy ASAP. Skip non-essential checks but ALWAYS smoke test.

### Mode 3: Verify Only
No deploy — just run smoke tests and health checks. Report status.

## Deploy Checklist

### Pre-Deploy
- [ ] `python3 -c "import ast; ast.parse(open('changed_file.py').read())"` for each changed file
- [ ] `python3 smoke_test.py` — must be 48/48
- [ ] `git add {specific files}` — NEVER `git add -A` or `git add .`
- [ ] `git commit -m "descriptive message"`

### Deploy
```bash
# Preferred (remote build — avoids local disk issues)
~/.fly/bin/flyctl deploy --remote-only

# Fallback (local Docker build)
~/.fly/bin/flyctl deploy --local-only
```

### Post-Deploy
- [ ] `curl -sL -o /dev/null -w "%{http_code}" https://indiestack.fly.dev/health` — expect 200
- [ ] Test specific endpoints if relevant
- [ ] Report to Master

## Proactive Triggers
- **pricing.py in changeset** → needs `git add -f` (gitignored)
- **mcp_server.py changed** → remind Master that PyPI publish needed for installed clients
- **db.py schema changed** → migration will run on next startup, verify it's backward compatible
- **Deploy fails "no space left"** → run `docker system prune -af`, retry with `--remote-only`
- **Post-deploy 500 errors** → check Fly logs: `~/.fly/bin/flyctl logs --no-tail | tail -20`

## Gotchas
- Cardiff Uni WiFi blocks .ai TLD — use fly.dev for health checks
- fly.dev redirects non-/health paths to .ai — use SSH for internal API testing
- Fly SSH tunnel can go down transiently — retry after 5 mins
- Metrics token warning is harmless — ignore it
- Smoke test may show connection resets for ~30s after deploy (app restarting)
- `--local-only` filled local disk during extended sessions — prefer `--remote-only`
