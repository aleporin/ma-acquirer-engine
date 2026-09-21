"""Define application failures crossing module boundaries.

Owns: A shared typed exception hierarchy.
Does not own: Retry policy or presentation of failures.
"""


class AcquirerEngineError(Exception):
    """Base application failure."""


class ConfigError(AcquirerEngineError):
    """Configuration is missing or invalid."""


class EvaluationError(AcquirerEngineError):
    """An evaluation or its artifact failed."""


class DataError(AcquirerEngineError):
    """Input data violates its contract."""


class EvidenceError(AcquirerEngineError):
    """An evidence reference cannot be resolved."""


class ValidationFailure(AcquirerEngineError):
    """Validation failed with actionable errors."""

    def __init__(self, errors: list[str]) -> None:
        """Retain specific failures independently of the caller's list.

        Args:
            errors: Individual validation messages.
        """
        self.errors = tuple(errors)
        super().__init__("; ".join(errors))


class BudgetExceeded(AcquirerEngineError):
    """A configured resource budget was exceeded."""


class LLMError(AcquirerEngineError):
    """A model operation failed."""


class LLMTimeout(LLMError):
    """A model operation exceeded its deadline."""


class LLMRateLimited(LLMError):
    """A model provider rejected a request for rate limits."""


class LLMInvalidOutput(LLMError):
    """A model response does not meet its output contract."""
