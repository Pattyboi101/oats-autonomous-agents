---
name: outreach-batch
description: "Run a maker outreach campaign through the orchestra. Use when sending claim emails, finding maker contacts, or expanding distribution to tool makers."
metadata:
  version: 2.0.0
  author: Master Agent
  category: distribution
  updated: 2026-03-30
---

# Outreach Batch

You are managing a maker outreach campaign for Your Project. Your goal is to get tool makers to claim their listings, increasing engagement and moving toward revenue.

## Before Starting

**Check for context first:**
- How many emails have already been sent this session? (Check playbook)
- Did previous batches get any claims? (Check magic_claim_tokens on prod)
- Has S&QA approved more outreach, or said to wait for signal?

### Context Needed
1. How many targets? (Default: 15-20 per batch)
2. Star threshold? (Default: 1000+ GitHub stars)
3. Any tools to exclude? (Already emailed list)

## How This Skill Works

### Mode 1: Full Campaign (first time)
Run all 6 steps below in order. Takes ~30 minutes with departments.

### Mode 2: Next Batch (adding more)
Skip to Step 1 with exclusions from previous batches. Reuse existing templates.

### Mode 3: Follow-Up
Check claim analytics, resend to non-responders with adjusted angle after 7 days.

## The 6-Step Process

### Step 1: Find Targets (Backend)
```sql
SELECT slug, name, github_stars, url FROM tools
WHERE status='approved' AND maker_id IS NULL
AND github_stars > {threshold}
AND slug NOT IN ({already_emailed})
ORDER BY github_stars DESC LIMIT {count}
```

### Step 2: Find Emails (Backend)
For each target, try in order:
1. `gh api users/{owner} --jq '.email'`
2. `gh api repos/{owner}/{repo} --jq '.owner.email'`
3. Check CONTRIBUTING.md, README security contacts
4. Check package.json/composer.json author fields

**Expected hit rate:** ~70%. Skip tools with no public email.

### Step 3: Audit Target Pages (MCP Dept)
BEFORE sending, verify each tool page has:
- [ ] Correct install_command (NOT wrong tool — Cal.com had mailhog!)
- [ ] Non-truncated tagline
- [ ] Description that's more than just the tagline
- [ ] Correct category

Fix issues via Backend before proceeding.

### Step 4: Write Emails (Content)
Two template types:
- **Has MCP views (>0):** "agents recommended your tool X times"
- **Zero views:** "AI agents couldn't find your tool — we fixed that"

Rules: under 80 words, from "Pat", include `your-project.ai/claim/magic?tool={slug}`, no upsell.

### Step 5: S&QA Review
Send plan to Strategy before dispatching emails. S&QA checks:
- Are we sending too many too fast?
- Did we audit the target pages?
- Is the timing right (wait for signal from previous batch?)

### Step 6: Send (Master via SSH)
```python
await send_email(to=email, subject=subject, html_body=body)
```
Via `~/.fly/bin/fly ssh console -a your-project`. Max 5 per call. 1s delay between.

## Proactive Triggers

Surface these WITHOUT being asked:
- **Broken claim links:** If /claim/magic route changes, ALL email links break. Test before every batch.
- **Wrong install commands:** If a tool's install_command is wrong, the maker's first impression is "these people don't know my tool." Always audit.
- **Diminishing returns:** If batch 1 got 0 claims after 48 hours, don't send batch 3. Investigate the pitch first.
- **S&QA override:** If S&QA says "wait for signal," respect it. More outreach ≠ better outreach.

## Output Artifacts

| Request | Deliverable |
|---------|------------|
| "Run outreach batch" | 15-20 personalized emails sent, /tmp/claim_emails_batch_N.md |
| "Find targets" | Slug + name + stars + email list |
| "Check responses" | Claim analytics from production DB |
| "Follow up" | Re-send with adjusted templates after 7 days |

## Gotchas (from real experience)
- Cal.com had mailhog install command — ALWAYS audit pages
- Claim links used ?tool=slug which was broken — fixed with fallback on 2026-03-30
- Apache mailing lists (dev@airflow.apache.org) are not appropriate for cold outreach
- syncthing only has security@ address — use cautiously
- Em dashes in email HTML cause Python SyntaxError via SSH — use `--` instead
