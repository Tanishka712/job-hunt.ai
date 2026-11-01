"""Per-run, per-user, and per-model token budget guard and async TPM rate pacer."""

import asyncio
import time

DEFAULT_MODEL_DAILY_TPD: dict[str, int] = {
    "allam-2-7b": 500_000,
    "openai/gpt-oss-120b": 200_000,
    "openai/gpt-oss-20b": 200_000,
    "qwen/qwen3.8-27b": 200_000,
    "openai/gpt-oss-safeguard-20b": 200_000,
}


class BudgetExceededError(Exception):
    """Raised when a run, user, or model exceeds its configured token budget."""


class TokenBudgetGuard:
    """Tracks token consumption across runs, users, and Groq model buckets."""

    def __init__(
        self,
        *,
        max_tokens_per_run: int = 25_000,
        max_tokens_per_user_day: int = 150_000,
        max_tokens_per_model_day: dict[str, int] | None = None,
    ) -> None:
        self._max_run = max_tokens_per_run
        self._max_user_day = max_tokens_per_user_day
        self._max_model_day = dict(DEFAULT_MODEL_DAILY_TPD)
        if max_tokens_per_model_day:
            self._max_model_day.update(max_tokens_per_model_day)

        self._run_used: dict[str, int] = {}
        self._user_used: dict[str, int] = {}
        self._model_used: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._last_call_ts: dict[str, float] = {}

    def remaining_model_tokens(self, model: str) -> int:
        """Return remaining daily tokens for `model`."""
        cap = self._max_model_day.get(model, 100_000)
        return max(cap - self._model_used.get(model, 0), 0)

    def should_overflow_model(self, model: str, threshold_ratio: float = 0.85) -> bool:
        """Return True if `model` has consumed >= `threshold_ratio` (default 85%) of daily TPD."""
        cap = self._max_model_day.get(model, 100_000)
        used = self._model_used.get(model, 0)
        return used >= int(cap * threshold_ratio)

    async def consume(
        self,
        *,
        run_id: str,
        user_id: str,
        model: str,
        tokens: int,
        min_interval_seconds: float = 0.0,
    ) -> None:
        """Record `tokens` and raise BudgetExceededError if any ceiling is breached."""
        async with self._lock:
            if min_interval_seconds > 0:
                now = time.monotonic()
                prev = self._last_call_ts.get(model, 0.0)
                wait_for = (prev + min_interval_seconds) - now
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
                self._last_call_ts[model] = time.monotonic()

            new_run = self._run_used.get(run_id, 0) + tokens
            if new_run > self._max_run:
                raise BudgetExceededError(
                    f"Exceeded run budget for '{run_id}': {new_run} > {self._max_run}"
                )

            new_user = self._user_used.get(user_id, 0) + tokens
            if new_user > self._max_user_day:
                raise BudgetExceededError(
                    f"Exceeded user daily budget for '{user_id}': {new_user} > {self._max_user_day}"
                )

            model_cap = self._max_model_day.get(model, 100_000)
            new_model = self._model_used.get(model, 0) + tokens
            if new_model > model_cap:
                raise BudgetExceededError(
                    f"Exceeded model daily budget for '{model}': {new_model} > {model_cap}"
                )

            self._run_used[run_id] = new_run
            self._user_used[user_id] = new_user
            self._model_used[model] = new_model
