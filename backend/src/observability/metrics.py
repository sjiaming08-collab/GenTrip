"""Small dependency-free Prometheus exposition for plan runtime metrics."""

from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Any


class RuntimeMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._runs: Counter[tuple[str, str]] = Counter()
            self._duration_sum_seconds: Counter[str] = Counter()
            self._token_usage: Counter[str] = Counter()
            self._bundle_search: Counter[str] = Counter()
            self._llm_calls: Counter[tuple[str, str, str]] = Counter()
            self._tool_calls: Counter[tuple[str, str]] = Counter()
            self._phases: Counter[tuple[str, str]] = Counter()

    def record_run(self, state: dict[str, Any], status: str, duration_seconds: float) -> None:
        with self._lock:
            path = str(state.get("plan_path") or "none")
            self._runs[(status, path)] += 1
            self._duration_sum_seconds[status] += max(0.0, duration_seconds)
            for call in state.get("llm_calls") or []:
                self._llm_calls[(
                    str(call.get("operation") or "unknown"),
                    str(call.get("status") or "unknown"),
                    str(call.get("error_code") or "none"),
                )] += 1
                self._token_usage["prompt"] += int(call.get("prompt_tokens") or 0)
                self._token_usage["completion"] += int(call.get("completion_tokens") or 0)
                self._token_usage["total"] += int(call.get("total_tokens") or 0)
            for call in state.get("tool_calls") or []:
                self._tool_calls[(
                    str(call.get("operation") or "unknown"),
                    str(call.get("status") or "unknown"),
                )] += 1
                if call.get("operation") == "route_bundle_search":
                    self._bundle_search["hit" if call.get("cache_hit") else "miss"] += 1
            for phase in state.get("phase_log") or []:
                self._phases[(
                    str(phase.get("phase") or "unknown"),
                    str(phase.get("status") or "unknown"),
                )] += 1

    @staticmethod
    def _label(**labels: str) -> str:
        return ",".join(f'{key}="{value}"' for key, value in labels.items())

    def render_prometheus(self, snapshot: dict[str, Any] | None = None) -> str:
        with self._lock:
            runs = snapshot.get("runs", self._runs) if snapshot else self._runs
            duration_sum = snapshot.get("duration_seconds", self._duration_sum_seconds) if snapshot else self._duration_sum_seconds
            token_usage = snapshot.get("token_usage", self._token_usage) if snapshot else self._token_usage
            bundle_search = snapshot.get("bundle_search", self._bundle_search) if snapshot else self._bundle_search
            llm_calls = snapshot.get("llm_calls", self._llm_calls) if snapshot else self._llm_calls
            tool_calls = snapshot.get("tool_calls", self._tool_calls) if snapshot else self._tool_calls
            phases = snapshot.get("phases", self._phases) if snapshot else self._phases
            lines = [
                "# HELP gentrip_plan_runs_total Completed plan runs by result and path.",
                "# TYPE gentrip_plan_runs_total counter",
            ]
            for (status, path), value in sorted(runs.items()):
                lines.append(f"gentrip_plan_runs_total{{{self._label(status=status, path=path)}}} {value}")
            lines.extend([
                "# HELP gentrip_plan_run_duration_seconds Total duration of plan runs by result.",
                "# TYPE gentrip_plan_run_duration_seconds counter",
            ])
            for status, value in sorted(duration_sum.items()):
                lines.append(f"gentrip_plan_run_duration_seconds{{{self._label(status=status)}}} {value:.6f}")
            lines.extend([
                "# HELP gentrip_llm_tokens_total LLM token usage by token type.",
                "# TYPE gentrip_llm_tokens_total counter",
            ])
            for token_type, value in sorted(token_usage.items()):
                lines.append(f"gentrip_llm_tokens_total{{{self._label(token_type=token_type)}}} {value}")
            lines.extend([
                "# HELP gentrip_route_bundle_search_total RouteBundle cache searches by outcome.",
                "# TYPE gentrip_route_bundle_search_total counter",
            ])
            for outcome, value in sorted(bundle_search.items()):
                lines.append(f"gentrip_route_bundle_search_total{{{self._label(outcome=outcome)}}} {value}")
            lines.extend([
                "# HELP gentrip_llm_calls_total LLM calls by operation, status, and safe error code.",
                "# TYPE gentrip_llm_calls_total counter",
            ])
            for (operation, status, error_code), value in sorted(llm_calls.items()):
                lines.append(f"gentrip_llm_calls_total{{{self._label(operation=operation, status=status, error_code=error_code)}}} {value}")
            lines.extend([
                "# HELP gentrip_tool_calls_total Tool calls by operation and status.",
                "# TYPE gentrip_tool_calls_total counter",
            ])
            for (operation, status), value in sorted(tool_calls.items()):
                lines.append(f"gentrip_tool_calls_total{{{self._label(operation=operation, status=status)}}} {value}")
            lines.extend([
                "# HELP gentrip_plan_phases_total Completed graph phases by phase and status.",
                "# TYPE gentrip_plan_phases_total counter",
            ])
            for (phase, status), value in sorted(phases.items()):
                lines.append(f"gentrip_plan_phases_total{{{self._label(phase=phase, status=status)}}} {value}")
            return "\n".join(lines) + "\n"


runtime_metrics = RuntimeMetrics()
