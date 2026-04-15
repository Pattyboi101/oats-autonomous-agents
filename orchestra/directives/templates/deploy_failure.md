# Directive: Investigate Deploy Failure

**Priority:** Critical
**Department:** DevOps
**Trigger:** Health check failures detected after deployment

## Context

- **Error:** {{error}}
- **Consecutive failures:** {{consecutive_failures}}
- **Detected at:** {{timestamp}}

## Tasks

1. Verify the outage: hit the health check endpoint
2. If confirmed down:
   - Check hosting platform status and machine logs
   - If machines are stopped, restart them
   - Check recent deploys for the breaking change
3. If API returns errors but health is OK:
   - Check application logs for stack traces
   - Check if a recent migration or config change caused it
4. Notify the team with findings

## Constraints

- Do NOT redeploy without understanding the root cause
- Do NOT modify code — this is an investigation directive
- If data corruption suspected, take a backup FIRST
