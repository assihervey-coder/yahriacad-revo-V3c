"""RLAgent — agent REINFORCE avec baseline, mémoire d'épisode, checkpoints."""
from __future__ import annotations

import os
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from shared.utilities import get_logger
from services.ai_engine.rl_agent.action_space import ActionSpace
from services.ai_engine.rl_agent.policy_network import PolicyNetwork
from services.ai_engine.rl_agent.value_network import ValueNetwork
from services.ai_engine.rl_agent.world_model import WorldModel

log = get_logger("ai_engine.rl.agent")


class RLAgent:
    """Agent décisionnel : observe → sélectionne → apprend (REINFORCE+baseline)."""

    GAMMA = 0.95

    def __init__(self, policy: PolicyNetwork, value: ValueNetwork,
                 world_model: WorldModel, action_space: ActionSpace) -> None:
        self.policy = policy
        self.value = value
        self.world_model = world_model
        self.action_space = action_space
        self._memory: Deque[Dict] = deque(maxlen=10_000)
        self._current_features: Optional[np.ndarray] = None
        self.episode_buffer: List[Tuple[np.ndarray, int]] = []

    # ------------------------------------------------------------- observe
    def observe(self, state_dict: Dict) -> np.ndarray:
        """Encode un état et le mémorise comme feature courante."""
        feats = self.world_model.encoder(state_dict)
        self._current_features = feats
        return feats

    # ------------------------------------------------------ select_action
    def select_action(self, greedy: bool = False, eps: float = 0.1) -> int:
        """Sélectionne une action (index) selon la politique courante."""
        if self._current_features is None:
            self._current_features = np.zeros(self.policy.feature_dim)
        return self.policy.select_action(self._current_features, greedy=greedy, eps=eps)

    def act(self, greedy: bool = False, eps: float = 0.1):
        """Action décodée (PlacementAction) depuis la politique."""
        idx = self.select_action(greedy=greedy, eps=eps)
        action = self.action_space.decode(idx)
        self._remember_step(idx)
        return action

    # -------------------------------------------------------------- memory
    def _remember_step(self, action_idx: int) -> None:
        if self._current_features is not None:
            self.episode_buffer.append((self._current_features.copy(), int(action_idx)))

    def remember(self, features: np.ndarray, action_idx: int) -> None:
        """Ajout explicite d'une transition (features, action)."""
        self._memory.append({"features": np.asarray(features, dtype=np.float64),
                             "action": int(action_idx)})

    def episode_end(self) -> List[Tuple[np.ndarray, int]]:
        """Clôt l'épisode et retourne la trajectoire (features, action)."""
        traj = list(self.episode_buffer)
        self.episode_buffer.clear()
        return traj

    # ---------------------------------------------------------------- learn
    def learn(self, rewards: List[float], states: List[np.ndarray],
              actions: List[int], lr_policy: float = 1e-3,
              lr_value: float = 1e-3, use_baseline: bool = True) -> Dict:
        """REINFORCE complet : retours escomptés + avantages + baseline.

        reward[t] = -wire_length_delta - violations (convention plate-forme).
        Retourne des métriques d'entraînement.
        """
        rewards = np.asarray(rewards, dtype=np.float64)
        states = [np.asarray(s, dtype=np.float64).ravel() for s in states]
        actions = [int(a) for a in actions]
        n = min(len(rewards), len(states), len(actions))
        if n == 0:
            return {"n": 0}

        # retours escomptés (backward pass)
        returns = np.zeros(n)
        running = 0.0
        for t in range(n - 1, -1, -1):
            running = rewards[t] + self.GAMMA * running
            returns[t] = running

        values = np.array([self.value.estimate(s) for s in states[:n]])
        advantages = returns - values if use_baseline else returns
        # normalisation des avantages (variance reduction)
        if n > 1 and float(np.std(advantages)) > 1e-8:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        loss_p = self.policy.train_batch(np.array(states[:n]),
                                         np.array(actions[:n]), advantages,
                                         lr=lr_policy)
        loss_v = self.value.train_batch(np.array(states[:n]), returns, lr=lr_value)

        # apprend aussi le world model sur les transitions observées
        for t in range(n - 1):
            self.world_model.fit_transition(states[t], states[t + 1], lr=0.01)

        self._memory.append({"returns": returns.tolist(),
                             "advantages": advantages.tolist()})
        return {"n": n, "policy_loss": loss_p, "value_loss": loss_v,
                "mean_return": float(np.mean(returns)),
                "mean_advantage": float(np.mean(advantages))}

    # ---------------------------------------------------------- persistence
    def save_all(self, directory: str) -> None:
        """Sauvegarde policy + value + world model dans un répertoire."""
        os.makedirs(directory, exist_ok=True)
        self.policy.save(os.path.join(directory, "policy.npz"))
        self.value.save(os.path.join(directory, "value.npz"))
        self.world_model.save(os.path.join(directory, "world_model.npz"))
        log.info("RLAgent sauvegardé dans %s", directory)

    def load_all(self, directory: str) -> bool:
        """Charge les trois réseaux — True si au moins la policy est chargée."""
        ok_p = self.policy.load(os.path.join(directory, "policy.npz"))
        self.value.load(os.path.join(directory, "value.npz"))
        self.world_model.load(os.path.join(directory, "world_model.npz"))
        return ok_p
