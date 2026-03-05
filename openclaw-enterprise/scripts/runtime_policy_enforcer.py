#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ToolCall:
    agent_id: str
    tool_name: str
    scope: str


class PolicyEnforcer:
    """RBAC enforcement scoped to runtime tool invocations."""

    def __init__(self, policy_file: str | None = None) -> None:
        if policy_file is None:
            root = Path(__file__).resolve().parents[1]
            policy_file = str(root / "policies" / "agent_capabilities.yaml")
        self.policy_file = policy_file
        self._policies = self._load()

    def _load(self) -> dict:
        with open(self.policy_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("agents", {})

    def is_allowed(self, agent_id: str, tool_name: str) -> bool:
        agent = self._policies.get(agent_id, {})
        allowed = set(agent.get("allowed_tools", []))
        denied = set(agent.get("denied_tools", []))
        if tool_name in denied:
            return False
        if allowed and tool_name not in allowed:
            return False
        return True

    def check_tool_allowed(self, call: ToolCall) -> None:
        if not self.is_allowed(call.agent_id, call.tool_name):
            raise PermissionError(
                f"policy_denied agent={call.agent_id} tool={call.tool_name} scope={call.scope}"
            )
