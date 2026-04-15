# Directive: Investigate Security Alert

**Priority:** Critical
**Department:** Strategy & QA
**Trigger:** Security scan or monitoring detected a potential vulnerability

## Context

- **Alert type:** {{alert_type}}
- **Severity:** {{severity}}
- **Affected component:** {{component}}
- **Detected at:** {{timestamp}}

## Tasks

1. Assess the severity and blast radius
   - What data or systems could be affected?
   - Is it actively being exploited?
2. If actively exploited:
   - Coordinate immediate mitigation with DevOps (block IPs, disable endpoint, etc.)
   - Preserve logs and evidence before any changes
3. If not actively exploited:
   - Reproduce the vulnerability in a safe environment
   - Document the attack vector and impact
4. Propose a fix with the relevant department (Frontend for XSS, Backend for injection, etc.)
5. After fix: run the Chaos Monkey agent to verify the fix holds

## Constraints

- Do NOT disclose vulnerability details in public channels
- Preserve all logs before making changes
- Coordinate with CEO if user data may be compromised
- Security fixes skip the normal review queue — ship immediately
