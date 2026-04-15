# Directive: Investigate Performance Anomaly

**Priority:** High
**Department:** Backend
**Trigger:** Response times or error rates exceeded threshold

## Context

- **Metric:** {{metric_name}}
- **Current value:** {{current_value}}
- **Threshold:** {{threshold}}
- **Detected at:** {{timestamp}}

## Tasks

1. Check application metrics and logs for the time window
2. Identify the affected endpoints or services
3. For each affected area, diagnose:
   - Is it a database query regression? Check slow query logs
   - Is it a memory/CPU spike? Check resource utilization
   - Is it an external dependency timeout? Check third-party status
   - Is it a traffic spike? Check request volume
4. If root cause found, document it and propose a fix
5. If mitigation needed immediately, coordinate with DevOps

## Constraints

- Gather evidence before proposing fixes
- Don't optimize prematurely — verify the bottleneck first
- If it's a traffic spike, consider whether scaling is the right response vs rate limiting
