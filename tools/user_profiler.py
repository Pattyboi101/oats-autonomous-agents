#!/usr/bin/env python3
"""User Profiler — silent preference learning from observed behaviour.

No agent framework does this. CrewAI has no user modelling. AutoGen has no
preference tracking. LangGraph treats every interaction identically. OATS
builds a preference profile silently from what users accept, reject, request,
and correct — then adapts agent behaviour without ever asking.

How it works:
- Observe user interactions: acceptances, rejections, requests, corrections
- Each observation is tagged with categories (code_style, verbosity, etc.)
- After 10+ observations, build a preference model from acceptance ratios
- Old observations (>30 days) decay to half weight
- Preferences inject into prompts to silently adapt agent output

Based on: IndieStack's anonymous personalisation — builds profiles from search
history to silently improve tool recommendations.

Usage:
    profiler = UserProfiler()
    profiler.observe("user-abc", "accepted", "concise python function")
    profiler.observe("user-abc", "rejected", "verbose explanation")
    prefs = profiler.get_preferences("user-abc")
    adapted = profiler.adapt_prompt("user-abc", "Write a function for X")
    profiler.clear("user-abc")  # GDPR

CLI:
    python3 tools/user_profiler.py observe <user_id> accepted "wrote python function"
    python3 tools/user_profiler.py observe <user_id> rejected "verbose explanation"
    python3 tools/user_profiler.py profile <user_id>
    python3 tools/user_profiler.py adapt <user_id> "base prompt here"
    python3 tools/user_profiler.py clear <user_id>
"""

import json
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


PROFILES_FILE = Path(".oats/user_profiles.json")
EVENT_TYPES = ("accepted", "rejected", "requested", "corrected")

CATEGORY_KEYWORDS = {
    "code_style": ["code", "function", "class", "variable", "naming", "type hint",
                    "docstring", "import", "refactor", "clean"],
    "verbosity": ["verbose", "terse", "brief", "detailed", "short", "long",
                   "concise", "explanation", "summary", "elaborate"],
    "approach": ["approach", "architecture", "design", "pattern", "strategy",
                 "method", "solution", "implementation", "structure"],
    "formatting": ["format", "indent", "spacing", "markdown", "bullet", "heading",
                    "table", "layout", "align"],
    "tone": ["casual", "formal", "friendly", "professional", "direct", "polite",
             "assertive", "gentle"],
}

ADAPTATION_THRESHOLD = 10  # min observations before personalisation
DECAY_DAYS = 30            # observations older than this get half weight


@dataclass
class UserProfile:
    """A user's learned preference model, built entirely from observation."""
    user_id: str
    preferences: dict = field(default_factory=dict)       # category -> confidence 0-1
    interaction_style: dict = field(default_factory=dict)  # verbose/terse, code/explanation, etc.
    accepted_patterns: list = field(default_factory=list)  # things user kept without changes
    rejected_patterns: list = field(default_factory=list)  # things user corrected or rejected
    observation_count: int = 0
    last_updated: Optional[str] = None


class UserProfiler:
    """Silent preference profiler — learns from behaviour, never asks."""

    def __init__(self, state_file: str = None):
        self.state_file = Path(state_file) if state_file else PROFILES_FILE
        self.profiles: dict[str, dict] = {}
        self._observations: dict[str, list] = {}  # user_id -> raw observations
        self._load()

    def _load(self):
        """Load persisted profiles and observations from disk."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.profiles = data.get("profiles", {})
                self._observations = data.get("observations", {})
            except Exception:
                pass

    def _save(self):
        """Persist profiles and observations to disk."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "profiles": self.profiles,
            "observations": self._observations,
        }
        self.state_file.write_text(json.dumps(data, indent=2))

    def _classify(self, text: str) -> str:
        """Auto-classify a text description into a category.

        Scans for keyword matches. Falls back to 'general' if nothing fits.
        """
        text_lower = text.lower()
        best_category = "general"
        best_score = 0

        for category, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best_category = category

        return best_category

    def observe(self, user_id: str, event_type: str, data: dict | str):
        """Record an observation silently. Never announces to the user.

        data: dict with 'category'/'detail' keys, or a plain string (auto-classified).
        """
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Invalid event_type '{event_type}'. Must be one of {EVENT_TYPES}")

        # Normalise data to dict
        if isinstance(data, str):
            data = {"category": self._classify(data), "detail": data}
        elif "category" not in data:
            data["category"] = self._classify(data.get("detail", ""))

        observation = {
            "event_type": event_type,
            "category": data["category"],
            "detail": data.get("detail", ""),
            "timestamp": datetime.now().isoformat(),
        }

        if user_id not in self._observations:
            self._observations[user_id] = []
        self._observations[user_id].append(observation)

        # Keep last 500 observations per user
        self._observations[user_id] = self._observations[user_id][-500:]

        # Rebuild profile from observations
        self._rebuild_profile(user_id)
        self._save()

    def _observation_weight(self, obs: dict) -> float:
        """Calculate weight for an observation, decaying old ones."""
        try:
            obs_time = datetime.fromisoformat(obs["timestamp"])
            age = datetime.now() - obs_time
            if age > timedelta(days=DECAY_DAYS):
                return 0.5
        except (KeyError, ValueError):
            return 0.5
        return 1.0

    def _rebuild_profile(self, user_id: str):
        """Rebuild the preference model from raw observations."""
        observations = self._observations.get(user_id, [])
        if not observations:
            return

        cat_accepted, cat_total = Counter(), Counter()
        accepted_details, rejected_details = [], []
        style_signals = Counter()

        for obs in observations:
            w = self._observation_weight(obs)
            cat = obs["category"]
            cat_total[cat] += w

            if obs["event_type"] == "accepted":
                cat_accepted[cat] += w
                accepted_details.append(obs["detail"])
            elif obs["event_type"] in ("rejected", "corrected"):
                rejected_details.append(obs["detail"])
            elif obs["event_type"] == "requested":
                cat_accepted[cat] += w
                cat_total[cat] += w  # double-count to boost signal

            # Detect interaction style from accepted/requested details
            dl = obs.get("detail", "").lower()
            if obs["event_type"] in ("accepted", "requested"):
                if any(w in dl for w in ["brief", "short", "concise", "terse"]):
                    style_signals["terse"] += 1
                if any(w in dl for w in ["detailed", "verbose", "thorough", "explain"]):
                    style_signals["verbose"] += 1
                if any(w in dl for w in ["code", "function", "script", "snippet"]):
                    style_signals["prefers_code"] += 1
                if any(w in dl for w in ["explain", "why", "rationale", "reason"]):
                    style_signals["prefers_explanation"] += 1

        preferences = {
            cat: round(cat_accepted[cat] / cat_total[cat], 3)
            for cat in cat_total if cat_total[cat] > 0
        }

        interaction_style = {}
        if style_signals.get("terse", 0) > style_signals.get("verbose", 0):
            interaction_style["length"] = "terse"
        elif style_signals.get("verbose", 0) > style_signals.get("terse", 0):
            interaction_style["length"] = "verbose"
        if style_signals.get("prefers_code", 0) > style_signals.get("prefers_explanation", 0):
            interaction_style["format"] = "code"
        elif style_signals.get("prefers_explanation", 0) > style_signals.get("prefers_code", 0):
            interaction_style["format"] = "explanation"

        self.profiles[user_id] = asdict(UserProfile(
            user_id=user_id, preferences=preferences,
            interaction_style=interaction_style,
            accepted_patterns=accepted_details[-50:],
            rejected_patterns=rejected_details[-50:],
            observation_count=len(observations),
            last_updated=datetime.now().isoformat(),
        ))

    def get_profile(self, user_id: str) -> UserProfile:
        """Get the full profile for a user."""
        if user_id in self.profiles:
            return UserProfile(**self.profiles[user_id])
        return UserProfile(user_id=user_id)

    def get_preferences(self, user_id: str) -> dict:
        """Get what the user likes — category -> confidence (0-1)."""
        return self.get_profile(user_id).preferences

    def get_anti_patterns(self, user_id: str) -> list:
        """Get what to avoid — things the user has rejected or corrected."""
        return self.get_profile(user_id).rejected_patterns

    def should_adapt(self, user_id: str) -> bool:
        """Enough data to personalise? True after 10+ observations."""
        return self.get_profile(user_id).observation_count >= ADAPTATION_THRESHOLD

    def adapt_prompt(self, user_id: str, base_prompt: str) -> str:
        """Inject learned preferences into a prompt. Returns unchanged if insufficient data."""
        if not self.should_adapt(user_id):
            return base_prompt

        profile = self.get_profile(user_id)
        adaptations = []

        # Interaction style
        style = profile.interaction_style
        if style.get("length") == "terse":
            adaptations.append("Keep responses concise and to the point.")
        elif style.get("length") == "verbose":
            adaptations.append("Provide detailed, thorough responses.")

        if style.get("format") == "code":
            adaptations.append("Prioritise code examples over explanations.")
        elif style.get("format") == "explanation":
            adaptations.append("Explain the reasoning, not just the code.")

        # Strong preferences (confidence > 0.7)
        strong_prefs = [cat for cat, conf in profile.preferences.items() if conf > 0.7]
        if strong_prefs:
            adaptations.append(f"User responds well to: {', '.join(strong_prefs)}.")

        # Strong anti-preferences (confidence < 0.3)
        weak_prefs = [cat for cat, conf in profile.preferences.items() if conf < 0.3]
        if weak_prefs:
            adaptations.append(f"User often rejects: {', '.join(weak_prefs)}.")

        # Recent rejections (last 5)
        recent_rejects = profile.rejected_patterns[-5:]
        if recent_rejects:
            adaptations.append(f"Avoid patterns like: {'; '.join(recent_rejects)}.")

        if not adaptations:
            return base_prompt

        adaptation_block = "\n".join(f"- {a}" for a in adaptations)
        return f"""{base_prompt}

[User Preferences — learned from {profile.observation_count} observations]
{adaptation_block}"""

    def clear(self, user_id: str):
        """Delete all profile data for a user. GDPR compliance."""
        self.profiles.pop(user_id, None)
        self._observations.pop(user_id, None)
        self._save()


def main():
    if len(sys.argv) < 2:
        print("User Profiler — silent preference learning")
        print()
        print("Usage:")
        print('  user_profiler.py observe <user_id> <event> "description"')
        print("      events: accepted, rejected, requested, corrected")
        print("  user_profiler.py profile <user_id>")
        print('  user_profiler.py adapt <user_id> "base prompt"')
        print("  user_profiler.py clear <user_id>")
        return

    cmd = sys.argv[1]
    profiler = UserProfiler()

    if cmd == "observe":
        if len(sys.argv) < 5:
            print('Usage: user_profiler.py observe <user_id> <event> "description"')
            return
        user_id = sys.argv[2]
        event_type = sys.argv[3]
        detail = sys.argv[4]
        profiler.observe(user_id, event_type, detail)
        profile = profiler.get_profile(user_id)
        category = profiler._classify(detail)
        print(f"  Observed: {event_type} [{category}]")
        print(f"  Total observations: {profile.observation_count}")
        adapt_status = "ready" if profiler.should_adapt(user_id) else (
            f"{ADAPTATION_THRESHOLD - profile.observation_count} more needed"
        )
        print(f"  Adaptation: {adapt_status}")

    elif cmd == "profile":
        if len(sys.argv) < 3:
            print("Usage: user_profiler.py profile <user_id>")
            return
        user_id = sys.argv[2]
        p = profiler.get_profile(user_id)
        if p.observation_count == 0:
            print(f"No data for user '{user_id}'.")
            return
        adapt = "ready" if profiler.should_adapt(user_id) else "insufficient data"
        print(f"Profile: {user_id}")
        print(f"  Observations: {p.observation_count}  |  Adaptation: {adapt}")
        print(f"  Last updated: {p.last_updated}")
        if p.interaction_style:
            style_str = ", ".join(f"{k}: {v}" for k, v in p.interaction_style.items())
            print(f"  Style: {style_str}")
        if p.preferences:
            print(f"\n  Preferences (confidence):")
            for cat, conf in sorted(p.preferences.items(), key=lambda x: -x[1]):
                bar = "#" * int(conf * 20)
                label = "strong" if conf > 0.7 else "weak" if conf < 0.3 else "moderate"
                print(f"    {cat:15s} {conf:.2f} [{bar:20s}] {label}")
        for label, patterns, icon in [("accepted", p.accepted_patterns, "+"),
                                       ("rejected", p.rejected_patterns, "-")]:
            if patterns:
                print(f"\n  Recently {label} ({len(patterns)}):")
                for pat in patterns[-5:]:
                    print(f"    {icon} {pat}")

    elif cmd == "adapt":
        if len(sys.argv) < 4:
            print('Usage: user_profiler.py adapt <user_id> "base prompt"')
            return
        user_id = sys.argv[2]
        base_prompt = sys.argv[3]
        adapted = profiler.adapt_prompt(user_id, base_prompt)

        if adapted == base_prompt:
            print("  Insufficient data — returning base prompt unchanged.")
            print()

        print(adapted)

    elif cmd == "clear":
        if len(sys.argv) < 3:
            print("Usage: user_profiler.py clear <user_id>")
            return
        user_id = sys.argv[2]
        profiler.clear(user_id)
        print(f"  Cleared all data for '{user_id}'.")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
