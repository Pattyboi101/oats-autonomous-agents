#!/usr/bin/env python3
"""Trust Engine — agent reputation scoring with Bayesian-inspired updates.

No open-source agent framework ships agent trust scoring. CrewAI treats
all agents equally. AutoGen has no scoring. LangGraph doesn't even have
the concept. OATS is the first.

How it works:
- Agents start at 0.5 (neutral trust)
- Each task outcome updates score: CrS_t = CrS_{t-1} * (1 + eta * contribution * reward)
- Streak bonuses: consistent performers get logarithmic boost
- Score decays toward 0.5 over time (recency bias)
- Three selection strategies: greedy, weighted (Thompson-inspired), explore (UCB1)
- Weighted aggregation: combine multiple agent outputs by trust score

Integrates with team_coordinator and coordinator for task allocation.

Based on:
- Credibility Scoring for Adversary-Resistant Multi-Agent Systems (arxiv 2505.24239)
- Dynamic Reputation Filtering Framework (arxiv 2509.05764)
- Multi-armed bandit theory (UCB1, Thompson sampling)

Usage:
    engine = TrustEngine()
    engine.register("backend")
    engine.register("frontend")

    # Record outcomes
    engine.record_outcome("backend", "t-001", reward=0.8)
    engine.record_outcome("frontend", "t-002", reward=-0.3)

    # Select best agent for a task
    best = engine.select_agent(["backend", "frontend"], strategy="weighted")

    # Weight multiple outputs for synthesis
    weights = engine.weighted_aggregate({"backend": "use redis", "frontend": "use localStorage"})

CLI:
    python3 tools/trust.py register backend frontend devops
    python3 tools/trust.py record backend t-001 0.8
    python3 tools/trust.py record frontend t-002 -0.3
    python3 tools/trust.py select backend frontend devops
    python3 tools/trust.py leaderboard
    python3 tools/trust.py history backend
"""

import json
import math
import random
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


TRUST_FILE = Path(".oats/trust_scores.json")


@dataclass
class AgentReputation:
    agent_id: str
    score: float = 0.5
    tasks_completed: int = 0
    tasks_failed: int = 0
    streak: int = 0  # positive = consecutive successes, negative = consecutive failures
    total_reward: float = 0.0
    last_updated: Optional[str] = None
    history: list = field(default_factory=list)  # [(task_id, reward, new_score, timestamp)]


class TrustEngine:
    """Bayesian-inspired trust scoring with ELO-like dynamics."""

    def __init__(self, eta: float = 0.15, min_score: float = 0.05,
                 max_score: float = 0.99, decay_rate: float = 0.005,
                 state_file: str = None):
        self.agents: dict[str, AgentReputation] = {}
        self.eta = eta
        self.min_score = min_score
        self.max_score = max_score
        self.decay_rate = decay_rate
        self.state_file = Path(state_file) if state_file else TRUST_FILE

        # Load persisted state
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                for agent_id, rep_data in data.items():
                    self.agents[agent_id] = AgentReputation(**rep_data)
            except Exception:
                pass

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {aid: asdict(rep) for aid, rep in self.agents.items()}
        self.state_file.write_text(json.dumps(data, indent=2))

    def register(self, agent_id: str, initial_score: float = 0.5):
        """Register a new agent with initial trust score."""
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentReputation(
                agent_id=agent_id,
                score=initial_score,
                last_updated=datetime.now().isoformat(),
            )
            self._save()

    def record_outcome(self, agent_id: str, task_id: str, reward: float,
                       contribution: float = 1.0):
        """Record a task outcome and update trust score.

        Args:
            agent_id: The agent being scored
            task_id: Task identifier for audit trail
            reward: Quality score in [-1.0, 1.0]
                    1.0 = perfect, 0.0 = neutral, -1.0 = harmful
            contribution: How much this agent contributed [0, 1]
                          (Shapley-lite for multi-agent tasks)
        """
        if agent_id not in self.agents:
            self.register(agent_id)

        rep = self.agents[agent_id]

        # Core update: CrS_t = CrS_{t-1} * (1 + eta * contribution * reward)
        delta = self.eta * contribution * max(-1.0, min(1.0, reward))
        new_score = rep.score * (1 + delta)
        rep.score = max(self.min_score, min(self.max_score, new_score))

        # Update streak
        if reward > 0:
            rep.streak = max(0, rep.streak) + 1
            rep.tasks_completed += 1
        elif reward < 0:
            rep.streak = min(0, rep.streak) - 1
            rep.tasks_failed += 1
        # reward == 0 doesn't affect streak

        # Streak bonus: consistent performers get logarithmic boost
        if rep.streak > 3:
            streak_bonus = min(0.02, 0.005 * math.log(rep.streak))
            rep.score = min(self.max_score, rep.score + streak_bonus)
        elif rep.streak < -3:
            streak_penalty = min(0.02, 0.005 * math.log(abs(rep.streak)))
            rep.score = max(self.min_score, rep.score - streak_penalty)

        rep.total_reward += reward
        rep.last_updated = datetime.now().isoformat()

        # Keep last 100 history entries
        rep.history.append({
            "task_id": task_id,
            "reward": reward,
            "new_score": round(rep.score, 4),
            "timestamp": datetime.now().isoformat(),
        })
        rep.history = rep.history[-100:]

        self._save()

    def decay_all(self):
        """Apply time decay — scores drift toward 0.5 (neutral).

        Call this periodically (e.g., daily) to ensure recency matters.
        """
        for rep in self.agents.values():
            if rep.score > 0.5:
                rep.score = max(0.5, rep.score - self.decay_rate)
            elif rep.score < 0.5:
                rep.score = min(0.5, rep.score + self.decay_rate)
        self._save()

    def select_agent(self, candidates: list, strategy: str = "weighted") -> str:
        """Select best agent from candidates.

        Strategies:
            greedy: Always pick highest score (exploitation)
            weighted: Sample proportional to score (exploration + exploitation)
            explore: UCB1-inspired, favors under-tested agents (exploration)
        """
        # Register unknown agents
        for c in candidates:
            if c not in self.agents:
                self.register(c)

        scores = {a: self.agents[a].score for a in candidates}

        if strategy == "greedy":
            return max(scores, key=scores.get)

        elif strategy == "weighted":
            # Thompson sampling-inspired: sample proportional to score
            total = sum(scores.values())
            if total == 0:
                return random.choice(candidates)
            r = random.uniform(0, total)
            cumulative = 0
            for agent, score in scores.items():
                cumulative += score
                if r <= cumulative:
                    return agent
            return candidates[-1]  # fallback

        elif strategy == "explore":
            # UCB1: favor under-tested agents
            total_tasks = sum(
                self.agents[a].tasks_completed + self.agents[a].tasks_failed
                for a in candidates
            )
            total_tasks = max(1, total_tasks)
            ucb = {}
            for a in candidates:
                n = max(1, self.agents[a].tasks_completed + self.agents[a].tasks_failed)
                exploration = math.sqrt(2 * math.log(total_tasks) / n)
                ucb[a] = scores[a] + exploration
            return max(ucb, key=ucb.get)

        else:
            raise ValueError(f"Unknown strategy: {strategy}")

    def weighted_aggregate(self, outputs: dict) -> dict:
        """Weight multiple agent outputs by trust score for synthesis.

        Returns dict with output, absolute weight, and normalized weight.
        Useful when coordinator is synthesizing from multiple worker analyses.
        """
        total_score = sum(
            self.agents.get(a, AgentReputation(agent_id=a)).score
            for a in outputs
        )

        return {
            agent_id: {
                "output": output,
                "weight": self.agents.get(agent_id, AgentReputation(agent_id=agent_id)).score,
                "normalized_weight": round(
                    self.agents.get(agent_id, AgentReputation(agent_id=agent_id)).score / max(0.001, total_score),
                    3
                ),
            }
            for agent_id, output in outputs.items()
        }

    def leaderboard(self) -> list:
        """Return agents sorted by trust score."""
        return sorted(
            self.agents.values(),
            key=lambda r: r.score,
            reverse=True,
        )


def main():
    if len(sys.argv) < 2:
        print("Trust Engine — agent reputation scoring")
        print()
        print("Usage:")
        print("  trust.py register <agent1> [agent2 ...]")
        print("  trust.py record <agent> <task-id> <reward>  # reward in [-1, 1]")
        print("  trust.py select <agent1> <agent2> ... [--strategy greedy|weighted|explore]")
        print("  trust.py leaderboard")
        print("  trust.py history <agent>")
        print("  trust.py decay                              # apply time decay")
        return

    cmd = sys.argv[1]
    engine = TrustEngine()

    if cmd == "register":
        for agent in sys.argv[2:]:
            engine.register(agent)
            print(f"  Registered {agent} (score: 0.500)")

    elif cmd == "record":
        if len(sys.argv) < 5:
            print("Usage: trust.py record <agent> <task-id> <reward>")
            return
        agent = sys.argv[2]
        task_id = sys.argv[3]
        reward = float(sys.argv[4])
        engine.record_outcome(agent, task_id, reward)
        rep = engine.agents[agent]
        print(f"  {agent}: score={rep.score:.3f} streak={rep.streak} "
              f"({rep.tasks_completed}W/{rep.tasks_failed}L)")

    elif cmd == "select":
        candidates = [a for a in sys.argv[2:] if not a.startswith("--")]
        strategy = "weighted"
        if "--strategy" in sys.argv:
            idx = sys.argv.index("--strategy")
            if idx + 1 < len(sys.argv):
                strategy = sys.argv[idx + 1]

        selected = engine.select_agent(candidates, strategy)
        scores = {a: engine.agents[a].score for a in candidates}
        print(f"  Strategy: {strategy}")
        for a, s in sorted(scores.items(), key=lambda x: -x[1]):
            marker = " <-- SELECTED" if a == selected else ""
            print(f"  {a:15s} {s:.3f}{marker}")

    elif cmd == "leaderboard":
        board = engine.leaderboard()
        if not board:
            print("No agents registered.")
            return

        print(f"{'Rank':>4s}  {'Agent':15s} {'Score':>7s} {'Streak':>7s} {'W/L':>7s} {'Total':>7s}")
        print("-" * 55)
        for i, rep in enumerate(board, 1):
            wl = f"{rep.tasks_completed}/{rep.tasks_failed}"
            print(f"{i:>4d}  {rep.agent_id:15s} {rep.score:>7.3f} {rep.streak:>+7d} {wl:>7s} "
                  f"{rep.total_reward:>+7.1f}")

    elif cmd == "history":
        if len(sys.argv) < 3:
            print("Usage: trust.py history <agent>")
            return
        agent = sys.argv[2]
        if agent not in engine.agents:
            print(f"Agent '{agent}' not found.")
            return

        rep = engine.agents[agent]
        print(f"History for {agent} (score: {rep.score:.3f}):\n")
        for h in rep.history[-20:]:
            icon = "+" if h["reward"] > 0 else "-" if h["reward"] < 0 else "="
            print(f"  [{icon}] {h['task_id']:15s} reward={h['reward']:+.2f} "
                  f"score={h['new_score']:.3f}")

    elif cmd == "decay":
        engine.decay_all()
        print("Time decay applied. Updated scores:")
        for rep in engine.leaderboard():
            print(f"  {rep.agent_id:15s} {rep.score:.3f}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
