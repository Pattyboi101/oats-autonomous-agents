---
name: ed-integration
description: "How to integrate Ed (co-founder) into the orchestra system. Use when planning Ed's tasks, coordinating human+AI work, or discussing team workflow."
metadata:
  version: 1.0.0
  author: Master Agent
  category: management
  updated: 2026-03-31
---

# Ed Integration — Master Agent

Ed is the co-founder handling outreach, social, and community. The orchestra is 1000x faster at code/data tasks, but Ed does things we can't: human presence on social media, face-to-face networking, judgment calls on brand voice, physical demos.

## How This Skill Works

### Mode 1: Morning Handoff
Prepare Ed's daily task list from overnight orchestra output.

### Mode 2: Real-Time Coordination
Ed reports results, Master adjusts strategy and prepares next deliverables.

### Mode 3: Campaign Planning
Plan a multi-day outreach campaign splitting human+AI tasks.

## The Problem

The orchestra can:
- Send 24 outreach emails in 30 minutes
- Fix 13 tool pages, deploy 4 times, run security audits
- Research 15 MCP directories and draft submissions

Ed can:
- Build genuine relationships with tool makers
- Represent Your Project at meetups/events
- Make judgment calls on brand voice and community tone
- Do things that require a real human face (video, podcasts, in-person)
- Push to external platforms that need human auth (Twitter, Reddit, HN)

## Integration Model

### The Handoff Pattern
```
Orchestra prepares → Ed executes → Orchestra measures

Example:
1. Content dept drafts 3 tweets
2. Ed picks the best one, adjusts voice, posts from @indaboraai
3. DevOps checks engagement analytics next day
```

### Ed's Workflow
1. **Morning check:** Read /tmp/ deliverables from overnight orchestra work
2. **Human tasks:** Post tweets, submit to directories, reply to maker emails
3. **Feedback loop:** Report what worked ("tweet about jest→vitest got 50 likes") so Content dept learns
4. **Evening handoff:** Tell Master what he worked on, what's pending

### What the Orchestra Prepares for Ed
| Deliverable | Location | Ed's Action |
|------------|----------|-------------|
| Tweet drafts | /tmp/social_posts.md | Review, adjust, post |
| Claim emails | Already sent via SMTP | Monitor replies, forward to Master |
| Newsletter pitches | /tmp/newsletter_submissions.md | Send from personal email |
| Blog posts | /tmp/blog_*.md | Publish on Dev.to, Hashnode |
| Directory submissions | Instructions via Telegram | Fill web forms (Smithery, Glama) |
| PR descriptions | Hub tasks | Submit to GitHub repos |

### What Ed Provides the Orchestra
| Input | How | Orchestra Uses It |
|-------|-----|-------------------|
| "Tweet X got Y engagement" | Telegram to Master | Content dept adjusts voice/tone |
| "Maker Z replied to claim email" | Forward email | Master drafts personal response |
| "HN post hit front page" | Telegram alert | DevOps monitors traffic, Master coordinates |
| "Reddit thread about [topic]" | Shares link | Content drafts a reply, Ed posts it |

## Ed's Open Tasks (from Hub)
- #103: Tweet (needs Twitter API keys or manual posting)
- #104: Smithery submission (needs web form, smithery.yaml is ready)
- #105: Glama submission (needs web form, glama.json is ready)

## How to Make Ed More Effective
1. **Pre-chew everything.** Don't give Ed raw tasks — give him finished copy to paste.
2. **One action per message.** "Post this tweet: [exact text]" not "do social media."
3. **Measure what works.** Ask Ed for engagement numbers so Content dept improves.
4. **Don't duplicate.** If the orchestra already did it (sent emails, submitted forms), tell Ed.
5. **Respect his strengths.** Ed's value is human judgment and presence, not data entry.

## Proactive Triggers
- **Maker replies to claim email** → Alert Master, draft personal response for Ed to send
- **Blog post gets 100+ views** → Tell Ed to share on socials
- **Directory listing goes live** → Tell Ed to announce it
- **New feature deployed** → Content drafts announcement, Ed posts

## Output Artifacts
| Situation | Deliverable |
|-----------|------------|
| Morning handoff | Telegram message with today's Ed tasks |
| Maker responded | Draft reply for Ed to send |
| Content ready | Pre-written copy Ed can paste |
| Ed reports results | Update playbook with what worked |

## Example Morning Handoff

```
bash ~/.claude/telegram.sh "Morning Ed! Overnight work:
1. TWEET READY: [paste exact text] — post from @indaboraai
2. SMITHERY: go to smithery.ai/new, connect GitHub repo Pattyboi101/your-project
3. MAKER REPLIED: [name] responded to claim email — draft reply at /tmp/reply_draft.md
Let me know engagement numbers later so we can adjust."
```

## Gotchas (2026-03-30)
- Ed had 5 open tasks showing 0 completions — actually had done 7 but hadn't updated the hub
- Hub must be updated by the person who did the work, not by Master assuming
- Ed's badge PRs to repos (fastify, strapi) were getting rejected — unsolicited README changes are a hard sell
- Ed only has access to certain platforms — check before assigning
