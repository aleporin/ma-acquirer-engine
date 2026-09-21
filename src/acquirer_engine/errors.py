"""Define application failures crossing module boundaries.

Owns: A shared typed exception hierarchy.
Does not own: Retry policy or presentation of failures.
"""


class AcquirerEngineError(Exception):
    """Base application failure."""


class ConfigError(AcquirerEngineError):
    """Configuration is missing or invalid."""
