#!/usr/bin/env python3
"""Think — autonomous ideation engine for OATS agents.

The difference between a tool and a mind: a tool waits for instructions.
A mind finishes one thought and the completion itself sparks the next.

After each task, the agent asks: "What's now possible that wasn't before?"
Each answer becomes a Thought — not a task, not a review, but a creative
leap that connects what was just built to what could be built next.

Thoughts form a chain. Each thought references the one before it.
The chain runs until ideas genuinely dry up — not from a stop condition,
but from the agent honestly saying "I don't see where this leads."

A Thought contains:
    what_i_built     — the work that just completed
    what_i_realized  — the insight that emerged from doing the work
    where_this_leads — the most exciting next direction
    confidence       — how strongly the agent believes this is worth pursuing (0-1)
    signal_source    — what triggered this thought (completion, research, failure, user)

The thought engine integrates with:
    - Tracer: reads what was just done
    - Memory: reads project state
    - Trust: knows which agents are performing well
    - Research: connects internal ideas to external signal

Usage:
    engine = ThoughtEngine()

    # After completing a task, generate the next thought
    thought = engine.think_forward(
        what_i_built="context optimizer that tracks which memory items agents actually use",
        what_i_realized="we track context usage but not skill usage — same pattern could optimize everything",
        where_this_leads="unified usefulness tracker across context, skills, tools, and agent selection",
        confidence=0.8,
    )

    # Chain: keep thinking until ideas dry up
    engine.chain(max_steps=5, min_confidence=0.3)

    # Read the thought chain
    engine.show_chain()
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


THOUGHTS_DIR = Path(".oats/thoughts")


class Thought:
    """A single step in the thought chain."""

    def __init__(self, what_i_built: str, what_i_realized: str,
                 where_this_leads: str, confidence: float = 0.5,
                 signal_source: str = "completion",
                 parent_id: str = None):
        self.id = f"thought-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.what_i_built = what_i_built
        self.what_i_realized = what_i_realized
        self.where_this_leads = where_this_leads
        self.confidence = max(0.0, min(1.0, confidence))
        self.signal_source = signal_source
        self.parent_id = parent_id
        self.created_at = datetime.now().isoformat()
        self.acted_on = False
        self.outcome = None
        self.child_id = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "what_i_built": self.what_i_built,
            "what_i_realized": self.what_i_realized,
            "where_this_leads": self.where_this_leads,
            "confidence": self.confidence,
            "signal_source": self.signal_source,
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "created_at": self.created_at,
            "acted_on": self.acted_on,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Thought":
        t = cls(
            what_i_built=data["what_i_built"],
            what_i_realized=data["what_i_realized"],
            where_this_leads=data["where_this_leads"],
            confidence=data.get("confidence", 0.5),
            signal_source=data.get("signal_source", "completion"),
            parent_id=data.get("parent_id"),
        )
        t.id = data["id"]
        t.created_at = data.get("created_at", datetime.now().isoformat())
        t.acted_on = data.get("acted_on", False)
        t.outcome = data.get("outcome")
        t.child_id = data.get("child_id")
        return t

    def as_prompt(self) -> str:
        """Render this thought as a prompt for the next session."""
        lines = [
            f"# Next Step: {self.where_this_leads}",
            "",
            f"## How I got here",
            f"I built: {self.what_i_built}",
            f"That made me realize: {self.what_i_realized}",
            f"Confidence: {self.confidence:.0%}",
            f"Signal: {self.signal_source}",
            "",
            f"## What to do",
            f"{self.where_this_leads}",
            "",
            f"## After building",
            f"Ask yourself: what does THIS enable? What's now possible that wasn't before?",
            f"Write your next thought. If nothing genuine comes to mind, stop — don't force it.",
        ]
        return "\n".join(lines)


class ThoughtEngine:
    """The autonomous ideation engine."""

    def __init__(self):
        THOUGHTS_DIR.mkdir(parents=True, exist_ok=True)

    def think_forward(self, what_i_built: str, what_i_realized: str,
                      where_this_leads: str, confidence: float = 0.5,
                      signal_source: str = "completion",
                      parent_id: str = None) -> Thought:
        """Generate a forward-looking thought after completing work."""
        thought = Thought(
            what_i_built=what_i_built,
            what_i_realized=what_i_realized,
            where_this_leads=where_this_leads,
            confidence=confidence,
            signal_source=signal_source,
            parent_id=parent_id,
        )

        # Link to parent
        if parent_id:
            parent = self.get(parent_id)
            if parent:
                parent.child_id = thought.id
                self._save(parent)

        self._save(thought)
        return thought

    def act_on(self, thought_id: str, outcome: str, next_thought_id: str = None):
        """Record that a thought was acted on and what happened."""
        thought = self.get(thought_id)
        if thought:
            thought.acted_on = True
            thought.outcome = outcome
            if next_thought_id:
                thought.child_id = next_thought_id
            self._save(thought)

    def get(self, thought_id: str) -> Optional[Thought]:
        """Get a specific thought."""
        path = THOUGHTS_DIR / f"{thought_id}.json"
        if path.exists():
            return Thought.from_dict(json.loads(path.read_text()))
        return None

    def get_latest(self) -> Optional[Thought]:
        """Get the most recent thought."""
        files = sorted(THOUGHTS_DIR.glob("thought-*.json"), reverse=True)
        if files:
            return Thought.from_dict(json.loads(files[0].read_text()))
        return None

    def get_chain(self, start_id: str = None) -> list:
        """Walk the thought chain from a starting point (or find the root)."""
        all_thoughts = self._load_all()
        if not all_thoughts:
            return []

        # Find chain start
        if start_id:
            current = next((t for t in all_thoughts if t.id == start_id), None)
        else:
            # Find the root (no parent)
            roots = [t for t in all_thoughts if not t.parent_id]
            if not roots:
                return all_thoughts  # circular or orphaned, return all
            current = roots[0]

        chain = []
        seen = set()
        while current and current.id not in seen:
            chain.append(current)
            seen.add(current.id)
            if current.child_id:
                current = next((t for t in all_thoughts if t.id == current.child_id), None)
            else:
                break

        return chain

    def get_unacted(self) -> list:
        """Get thoughts that haven't been acted on yet."""
        return [t for t in self._load_all() if not t.acted_on]

    def get_highest_confidence_unacted(self) -> Optional[Thought]:
        """Get the highest-confidence unacted thought."""
        unacted = self.get_unacted()
        if unacted:
            return max(unacted, key=lambda t: t.confidence)
        return None

    def show_chain(self):
        """Print the thought chain visually."""
        all_thoughts = self._load_all()
        if not all_thoughts:
            print("No thoughts yet.")
            return

        # Find chains (may be multiple)
        roots = [t for t in all_thoughts if not t.parent_id]
        if not roots:
            roots = [all_thoughts[0]]

        for root in roots:
            chain = self.get_chain(root.id)
            print(f"{'='*60}")
            for i, t in enumerate(chain):
                connector = "  " if i == 0 else "  -> "
                acted = " [DONE]" if t.acted_on else " [PENDING]" if not t.acted_on else ""
                conf = f" ({t.confidence:.0%})" if t.confidence else ""

                print(f"{connector}Step {i+1}: {t.where_this_leads[:60]}{conf}{acted}")
                if i == 0:
                    print(f"     Built: {t.what_i_built[:60]}")
                print(f"     Realized: {t.what_i_realized[:60]}")
                if t.outcome:
                    print(f"     Outcome: {t.outcome[:60]}")
            print(f"{'='*60}")

    def stats(self) -> dict:
        """Get thought engine statistics."""
        all_t = self._load_all()
        acted = [t for t in all_t if t.acted_on]
        return {
            "total_thoughts": len(all_t),
            "acted_on": len(acted),
            "pending": len(all_t) - len(acted),
            "avg_confidence": round(
                sum(t.confidence for t in all_t) / max(1, len(all_t)), 2
            ),
            "chains": len([t for t in all_t if not t.parent_id]),
            "by_signal": {
                source: len([t for t in all_t if t.signal_source == source])
                for source in set(t.signal_source for t in all_t)
            } if all_t else {},
        }

    def _save(self, thought: Thought):
        path = THOUGHTS_DIR / f"{thought.id}.json"
        path.write_text(json.dumps(thought.to_dict(), indent=2))

    def _load_all(self) -> list:
        thoughts = []
        for path in sorted(THOUGHTS_DIR.glob("thought-*.json")):
            try:
                thoughts.append(Thought.from_dict(json.loads(path.read_text())))
            except Exception:
                pass
        return thoughts


def main():
    if len(sys.argv) < 2:
        print("Think — autonomous ideation engine")
        print()
        print("Each completed task sparks the next idea. Thoughts chain together.")
        print("The chain runs until ideas genuinely dry up.")
        print()
        print("Usage:")
        print("  think.py forward <built> <realized> <leads-to> [--confidence 0.8] [--parent id]")
        print("  think.py chain                         # show the thought chain")
        print("  think.py next                          # show highest-confidence pending thought")
        print("  think.py prompt [thought-id]            # render as a session prompt")
        print("  think.py acted <thought-id> <outcome>   # record that you acted on a thought")
        print("  think.py stats                          # thought engine stats")
        return

    cmd = sys.argv[1]
    engine = ThoughtEngine()

    if cmd == "forward":
        if len(sys.argv) < 5:
            print("Usage: think.py forward <built> <realized> <leads-to> [--confidence N] [--parent id]")
            return
        built = sys.argv[2]
        realized = sys.argv[3]
        leads = sys.argv[4]
        confidence = 0.5
        parent = None
        signal = "completion"

        i = 5
        while i < len(sys.argv):
            if sys.argv[i] == "--confidence" and i + 1 < len(sys.argv):
                confidence = float(sys.argv[i + 1]); i += 2
            elif sys.argv[i] == "--parent" and i + 1 < len(sys.argv):
                parent = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--signal" and i + 1 < len(sys.argv):
                signal = sys.argv[i + 1]; i += 2
            else:
                i += 1

        t = engine.think_forward(built, realized, leads, confidence, signal, parent)
        print(f"Thought: {t.id}")
        print(f"  Built: {built[:60]}")
        print(f"  Realized: {realized[:60]}")
        print(f"  Leads to: {leads[:60]}")
        print(f"  Confidence: {confidence:.0%}")

    elif cmd == "chain":
        engine.show_chain()

    elif cmd == "next":
        t = engine.get_highest_confidence_unacted()
        if t:
            print(f"Next thought ({t.confidence:.0%} confidence):")
            print(f"  {t.where_this_leads}")
            print(f"  (from: {t.what_i_realized[:60]})")
            print(f"  ID: {t.id}")
        else:
            print("No pending thoughts. The chain has ended — or hasn't started.")

    elif cmd == "prompt":
        thought_id = sys.argv[2] if len(sys.argv) > 2 else None
        if thought_id:
            t = engine.get(thought_id)
        else:
            t = engine.get_highest_confidence_unacted()
        if t:
            print(t.as_prompt())
        else:
            print("No thought to render.")

    elif cmd == "acted":
        if len(sys.argv) < 4:
            print("Usage: think.py acted <thought-id> <outcome>")
            return
        engine.act_on(sys.argv[2], " ".join(sys.argv[3:]))
        print(f"Recorded: {sys.argv[2]} acted on.")

    elif cmd == "stats":
        s = engine.stats()
        print(f"Thoughts: {s['total_thoughts']} ({s['acted_on']} acted, {s['pending']} pending)")
        print(f"Avg confidence: {s['avg_confidence']}")
        print(f"Chains: {s['chains']}")
        if s.get("by_signal"):
            print(f"By signal: {s['by_signal']}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
