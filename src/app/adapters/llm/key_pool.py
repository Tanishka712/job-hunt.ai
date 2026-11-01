"""Multi-key round-robin pool and rate-limit state tracker for Groq API keys."""


class NoAvailableGroqKeyError(RuntimeError):
    """Raised when no Groq API keys are configured in the pool."""


class GroqKeyPool:
    """Manages a pool of Groq API keys and tracks per-(key, model) remaining quota."""

    def __init__(self, api_keys: list[str]) -> None:
        cleaned = [k.strip() for k in api_keys if k.strip()]
        self._keys: list[str] = cleaned
        self._cursor: int = 0
        self._exhausted_pairs: set[tuple[str, str]] = set()
        self._remaining_tokens: dict[tuple[str, str], int] = {}

    @property
    def size(self) -> int:
        """Number of configured keys in the pool."""
        return len(self._keys)

    def acquire(self, model: str, *, user_api_key: str | None = None) -> str:
        """Return an available API key for `model` (or `user_api_key` if BYOK provided)."""
        if user_api_key and user_api_key.strip():
            return user_api_key.strip()
        if not self._keys:
            raise NoAvailableGroqKeyError("No GROQ_API_KEYS configured in GroqKeyPool")

        n = len(self._keys)
        for _ in range(n):
            key = self._keys[self._cursor % n]
            self._cursor = (self._cursor + 1) % n
            if (key, model) not in self._exhausted_pairs:
                return key

        # All keys exhausted for this model -> return next key for fallback model
        key = self._keys[self._cursor % n]
        self._cursor = (self._cursor + 1) % n
        return key

    def record_response(
        self,
        api_key: str,
        model: str,
        *,
        status_code: int,
        remaining_tokens: int | None = None,
        remaining_requests: int | None = None,
    ) -> None:
        """Update rate-limit status for `(api_key, model)` from Groq response headers."""
        if remaining_tokens is not None:
            self._remaining_tokens[(api_key, model)] = remaining_tokens
        if (
            status_code == 429
            or (remaining_tokens is not None and remaining_tokens < 1_000)
            or (remaining_requests is not None and remaining_requests <= 0)
        ):
            self._exhausted_pairs.add((api_key, model))
