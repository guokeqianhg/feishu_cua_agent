from __future__ import annotations

from agent.state import AgentState, StepLog


class RunLogger:
    def log(self, state: AgentState, node: str, message: str, **data) -> None:
        step_index = state.current_step_idx if hasattr(state, "current_step_idx") else 0
        state.logs.append(
            StepLog(
                step_index=step_index,
                node=node,
                message=message,
                data=data,
            )
        )
