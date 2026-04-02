#!/usr/bin/env python3
"""Provoke — general-purpose provocation engine for autonomous agents.

Autonomous agents fall into patterns. They optimize what they already know.
They refine, iterate, polish — but they rarely step sideways. A provocation
is a forced sideways step: a question the agent wouldn't have asked itself.

Five provocation types:
    trending       — What can you learn from what's hot right now?
    roleplay       — Become a user/entity and feel the product's friction
    constraint     — Creative pressure that forces novel thinking
    inversion      — Attack your own product to find the cracks
    cross-domain   — Steal ideas from completely unrelated fields

The point is the thinking, not the output. Most provocations won't produce
an actionable idea. That's fine. The one in ten that does is worth more
than ten safe optimizations.

Usage:
    # Random provocation
    python3 tools/provoke.py

    # Specific type
    python3 tools/provoke.py --type constraint

    # With project context (enables roleplay with live data)
    python3 tools/provoke.py --type roleplay --project-url https://api.example.com

    # List all constraint and inversion prompts
    python3 tools/provoke.py --list

Integration with think.py:
    After thinking about a provocation, record the result:
    python3 tools/think.py forward "provocation: X" "realized Y" "leads to Z"
"""

import argparse
import json
import random
import sys
import textwrap
from urllib.error import URLError
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Constraint prompts — universal creative pressure for any software project
# ---------------------------------------------------------------------------

CONSTRAINTS = [
    "What if you had to make your first dollar by Friday?",
    "A user installed your product and uninstalled it 30 seconds later. Why?",
    "What if you could only keep 3 features?",
    "What would a competitor need to beat you? What can't they copy?",
    "What's the one metric that matters most? Is it visible?",
    "Someone just rage-tweeted about your product. What did they say?",
    "What if your primary user was non-technical?",
    "What would this look like if it had to work offline?",
    "What feature are you maintaining that nobody uses?",
    "What's your product's 'aha moment'? Does it happen in the first 60 seconds?",
    "What if you had to explain your product in 5 words?",
    "What would make someone recommend this to a friend unprompted?",
    "What if your entire team quit and a new team had to take over tomorrow?",
    "What would this product look like if it was built for a 10-year-old?",
    "What if you had to charge 10x your current price? What would justify it?",
    "What if every API call cost you $1? What would you stop doing?",
    "What would the free version look like if you had to make it irresistible?",
    "What if your product had to work via SMS only?",
    "What if you could only ship one more update, ever?",
    "What's the thing you're embarrassed to show investors?",
    "What would a user with terrible internet think of your product?",
    "What if you had to rebuild the entire thing in a weekend?",
    "What feature would you build if you had zero technical debt?",
    "What if your product needed to work without JavaScript?",
    "What's the hardest thing to explain about your product? That's your real problem.",
    "What if you had to onboard a new user in under 10 seconds?",
    "What would this look like if it was a physical product?",
    "What if your competitor open-sourced a clone tomorrow?",
    "What would change if you had 1 million users overnight?",
    "What if you had to make money from the people who never sign up?",
]

# ---------------------------------------------------------------------------
# Inversion prompts — attack your own product to find the cracks
# ---------------------------------------------------------------------------

INVERSIONS = [
    "What's the single worst thing about your product right now?",
    "What promise does your landing page make that you can't deliver?",
    "What data are you collecting but never using?",
    "What would make a user actively angry?",
    "What are you building that nobody asked for?",
    "What would happen if you deleted your most popular feature?",
    "Where are you copying instead of innovating?",
    "What assumption are you making that might be wrong?",
    "What would a user who hates your product say in a review?",
    "What's the most complex part of your codebase? Does it need to be?",
    "Where are you optimizing for vanity metrics instead of real value?",
    "What technical debt are you pretending doesn't exist?",
    "What would a security auditor find embarrassing?",
    "If you had to sabotage your own product subtly, where would you start?",
    "What's the thing that works in demo but breaks in production?",
    "What part of the user journey makes people give up?",
    "What would a journalist write if they investigated your product?",
    "What would break if your database grew 100x overnight?",
    "Where are you spending engineering time that a user would never notice?",
    "What's the lie you tell yourself about your users?",
    "What would your most frustrated support ticket say?",
    "What feature do you keep because of sunk cost, not user value?",
    "If your product disappeared tomorrow, what would users actually miss?",
    "What edge case are you ignoring because it's inconvenient?",
    "What would an accessibility audit reveal?",
]

# ---------------------------------------------------------------------------
# Cross-domain categories — fields far from software
# ---------------------------------------------------------------------------

CROSS_DOMAINS = [
    "game",
    "music",
    "biology",
    "architecture",
    "cooking",
    "sports",
    "art",
    "film",
    "education",
    "medicine",
    "fashion",
    "agriculture",
    "robotics",
    "astronomy",
    "linguistics",
]


def _fetch_json(url: str, timeout: int = 10) -> dict:
    """Fetch JSON from a URL. Returns empty dict on failure."""
    try:
        req = Request(url, headers={"User-Agent": "OATS-Provoke/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _wrap(text: str, width: int = 72) -> str:
    """Wrap text for terminal output."""
    return "\n".join(textwrap.wrap(text, width=width))


# ---------------------------------------------------------------------------
# Provocation generators
# ---------------------------------------------------------------------------

def provoke_trending() -> str:
    """Fetch trending GitHub repos and generate a provocation."""
    # GitHub trending doesn't have an official API, use the search API
    # to find recently-created repos with high stars as a proxy
    url = (
        "https://api.github.com/search/repositories"
        "?q=created:>2025-01-01+stars:>50&sort=stars&order=desc&per_page=30"
    )
    data = _fetch_json(url)
    items = data.get("items", [])

    if not items:
        return (
            "Could not fetch trending repos from GitHub.\n\n"
            "Fallback provocation: go to github.com/trending right now.\n"
            "Pick the first repo you don't understand. Spend 5 minutes\n"
            "figuring out why it's trending. What does that tell you\n"
            "about where developer tooling is headed?"
        )

    repo = random.choice(items[:15])
    name = repo.get("full_name", "unknown")
    desc = repo.get("description", "no description") or "no description"
    stars = repo.get("stargazers_count", 0)
    lang = repo.get("language", "unknown")

    return (
        f"Trending repo: {name}\n"
        f"  Stars: {stars:,} | Language: {lang}\n"
        f"  \"{desc}\"\n"
        f"\n"
        f"This project got mass attention. Ask yourself:\n"
        f"  - What problem does it solve that people clearly care about?\n"
        f"  - Does your project have a similar unmet need hiding in plain sight?\n"
        f"  - What idea from this repo could you adapt (not copy) for your domain?\n"
        f"  - Why did THIS project get traction while similar ones didn't?"
    )


def provoke_roleplay(project_url: str = None) -> str:
    """Generate a roleplay provocation, optionally using live project data."""
    if project_url:
        # Try to fetch some data from the project API
        data = _fetch_json(project_url)

        if data and isinstance(data, dict):
            # Try to find something useful in the response
            # Look for lists of items, users, resources
            entity = None
            for key in ("items", "results", "data", "tools", "users", "posts"):
                if key in data and isinstance(data[key], list) and data[key]:
                    entity = random.choice(data[key])
                    break

            if entity and isinstance(entity, dict):
                name = (entity.get("name") or entity.get("title")
                        or entity.get("username") or entity.get("id")
                        or "this entity")
                return (
                    f"Roleplay: You are \"{name}\".\n"
                    f"  Data: {json.dumps(entity, indent=2)[:500]}\n"
                    f"\n"
                    f"As this entity:\n"
                    f"  - What's your experience of this product?\n"
                    f"  - What would make you come back every day?\n"
                    f"  - What's confusing or frustrating from your perspective?\n"
                    f"  - What feature would change everything for you?"
                )

        if data and isinstance(data, list) and data:
            entity = random.choice(data)
            name = str(entity) if not isinstance(entity, dict) else (
                entity.get("name") or entity.get("title") or "this entity"
            )
            return (
                f"Roleplay: You are \"{name}\".\n"
                f"\n"
                f"As this entity:\n"
                f"  - What's your experience of this product?\n"
                f"  - What would make you the product's biggest advocate?\n"
                f"  - What friction do you feel that nobody has asked about?\n"
                f"  - What would make you leave for a competitor?"
            )

    # Fallback: generic roleplay personas
    personas = [
        ("a developer who just discovered your product through an AI assistant",
         "integrate it into their workflow"),
        ("a CTO evaluating your product for a 50-person team",
         "approve it for company-wide adoption"),
        ("a solo founder who can't afford to waste time on bad tools",
         "trust this product with their entire stack"),
        ("a junior developer on their first real project",
         "feel confident using this without senior help"),
        ("a developer who loved your competitor but got burned",
         "give your product a real chance"),
        ("a power user who's been with you since day one",
         "stay instead of building their own version"),
        ("an open-source maintainer considering integrating your product",
         "recommend it to their community"),
        ("a developer in a country with slow internet and expensive data",
         "justify the bandwidth your product uses"),
        ("someone who found your product through a frustrated forum post",
         "become a paying customer within a week"),
        ("a developer who tried your product once, hit a bug, and left",
         "come back and give it another shot"),
    ]

    persona, action = random.choice(personas)
    return (
        f"Roleplay: You are {persona}.\n"
        f"\n"
        f"As this person:\n"
        f"  - What would make you {action}?\n"
        f"  - What's the first thing you notice?\n"
        f"  - What would you Google before signing up?\n"
        f"  - What would make you tell your colleagues about this?"
    )


def provoke_constraint() -> str:
    """Pick a random creative constraint."""
    prompt = random.choice(CONSTRAINTS)
    return (
        f"{prompt}\n"
        f"\n"
        f"Sit with this constraint for 5 minutes. Don't dismiss it.\n"
        f"The best ideas come from impossible-sounding restrictions.\n"
        f"What would you actually do if this were true?"
    )


def provoke_inversion() -> str:
    """Pick a random inversion prompt."""
    prompt = random.choice(INVERSIONS)
    return (
        f"{prompt}\n"
        f"\n"
        f"Be honest. The point of inversion is to find blind spots,\n"
        f"not to confirm what you already believe. If the answer makes\n"
        f"you uncomfortable, you're doing it right."
    )


def provoke_cross_domain() -> str:
    """Fetch a trending repo from a different domain and force an analogy."""
    domain = random.choice(CROSS_DOMAINS)
    url = (
        f"https://api.github.com/search/repositories"
        f"?q={domain}+stars:>20&sort=stars&order=desc&per_page=20"
    )
    data = _fetch_json(url)
    items = data.get("items", [])

    if not items:
        # Fallback: use the domain concept directly
        analogies = [
            (
                f"Think about {domain}. What principle from {domain} could\n"
                f"transform how your product works?\n"
                f"\n"
                f"For example:\n"
                f"  - Cooking has 'mise en place' (everything in its place before you start)\n"
                f"  - Music has 'call and response' (every input gets a reaction)\n"
                f"  - Biology has 'symbiosis' (two organisms helping each other survive)\n"
                f"\n"
                f"What's the {domain} equivalent for your product?"
            ),
        ]
        return analogies[0]

    repo = random.choice(items[:10])
    name = repo.get("full_name", "unknown")
    desc = repo.get("description", "no description") or "no description"

    return (
        f"Cross-domain: from the world of {domain}\n"
        f"  Project: {name}\n"
        f"  \"{desc}\"\n"
        f"\n"
        f"This {domain} project does something interesting.\n"
        f"Force an analogy:\n"
        f"  - What's the equivalent concept for your product?\n"
        f"  - What would your product look like if it worked like this?\n"
        f"  - What user experience principle is hiding in this analogy?\n"
        f"  - What would a {domain} expert think of your product's design?"
    )


# ---------------------------------------------------------------------------
# Provocation type registry
# ---------------------------------------------------------------------------

PROVOCATION_TYPES = {
    "trending": provoke_trending,
    "roleplay": provoke_roleplay,
    "constraint": provoke_constraint,
    "inversion": provoke_inversion,
    "cross-domain": provoke_cross_domain,
}


def generate_provocation(ptype: str = None, project_url: str = None) -> str:
    """Generate a provocation of the given type (or random if None).

    Args:
        ptype: One of trending, roleplay, constraint, inversion, cross-domain.
               If None, picks randomly.
        project_url: Optional URL for roleplay to fetch live project data.

    Returns:
        Formatted provocation string ready for output.
    """
    if ptype is None:
        ptype = random.choice(list(PROVOCATION_TYPES.keys()))

    if ptype not in PROVOCATION_TYPES:
        return f"Unknown provocation type: {ptype}\nValid types: {', '.join(PROVOCATION_TYPES.keys())}"

    func = PROVOCATION_TYPES[ptype]

    # Pass project_url only to roleplay (the others don't use it)
    if ptype == "roleplay":
        body = func(project_url)
    else:
        body = func()

    output = (
        f"=== PROVOCATION ({ptype}) ===\n"
        f"\n"
        f"{body}\n"
        f"\n"
        f"Instructions:\n"
        f"- Spend 5 minutes thinking genuinely about this\n"
        f"- If you get a useful idea, act on it\n"
        f"- If not, record the thought and move on\n"
        f"- The point is the thinking, not the output"
    )

    return output


def list_all_prompts():
    """Print all constraint and inversion prompts."""
    print(f"{'='*60}")
    print(f"CONSTRAINTS ({len(CONSTRAINTS)} prompts)")
    print(f"{'='*60}")
    for i, c in enumerate(CONSTRAINTS, 1):
        print(f"  {i:2d}. {c}")

    print()
    print(f"{'='*60}")
    print(f"INVERSIONS ({len(INVERSIONS)} prompts)")
    print(f"{'='*60}")
    for i, inv in enumerate(INVERSIONS, 1):
        print(f"  {i:2d}. {inv}")

    print()
    print(f"Total: {len(CONSTRAINTS)} constraints + {len(INVERSIONS)} inversions"
          f" = {len(CONSTRAINTS) + len(INVERSIONS)} prompts")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Provoke — provocation engine for autonomous agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python3 tools/provoke.py                          # random provocation
              python3 tools/provoke.py --type constraint        # specific type
              python3 tools/provoke.py --type roleplay --project-url https://api.example.com
              python3 tools/provoke.py --list                   # show all prompts

            provocation types:
              trending      — learn from what's hot on GitHub right now
              roleplay      — become a user and feel the product's friction
              constraint    — creative pressure that forces novel thinking
              inversion     — attack your own product to find the cracks
              cross-domain  — steal ideas from completely unrelated fields

            after thinking, record the result via think.py:
              python3 tools/think.py forward "provocation: X" "realized Y" "leads to Z"
        """),
    )
    parser.add_argument(
        "--type", "-t",
        choices=list(PROVOCATION_TYPES.keys()),
        default=None,
        help="Type of provocation (default: random)",
    )
    parser.add_argument(
        "--project-url", "-u",
        default=None,
        help="Project API URL for roleplay (fetches live data)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all constraint and inversion prompts",
    )

    args = parser.parse_args()

    if args.list:
        list_all_prompts()
        return

    print(generate_provocation(ptype=args.type, project_url=args.project_url))


if __name__ == "__main__":
    main()
