#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


class BudgetExceededError(RuntimeError):
    pass


class BudgetGuard:
    def __init__(self, control_plane_file: str | None = None) -> None:
        if control_plane_file is None:
            root = Path(__file__).resolve().parents[1]
            control_plane_file = str(root / "control-plane" / "openclaw.json")
        with open(control_plane_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.budgets = data.get("budgets", {})
        self.cost_by_execution: dict[str, float] = {}

    def add_cost(self, execution_id: str, budget_key: str, delta_cost_usd: float) -> float:
        total = self.cost_by_execution.get(execution_id, 0.0) + float(delta_cost_usd)
        self.cost_by_execution[execution_id] = total
        max_cost = float(self.budgets.get(budget_key, {}).get("max_cost_usd", 1e9))
        if total > max_cost:
            raise BudgetExceededError(
                f"budget_exceeded execution_id={execution_id} budget={budget_key} total={total:.4f} limit={max_cost:.4f}"
            )
        return total
