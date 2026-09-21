"""Persist content-addressed model responses for network-free replay.

Owns: Stable request identity and atomic response storage.
Does not own: Calling providers or treating cached responses as already verified.
"""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from pydantic_ai.messages import ModelResponse
from pydantic_core import to_jsonable_python

from acquirer_engine.errors import LLMInvalidOutput


def _stable(value: object) -> object:
    if isinstance(value, dict):
        return {
            k: _stable(v)
            for k, v in value.items()
            if k not in {"timestamp", "run_id", "conversation_id", "provider_response_id"}
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def request_key(identity: str, messages: object, parameters: object) -> str:
    """Hash all causal inputs while dropping volatile transport identities.

    Args:
        identity: Model, configuration, and schema/prompt version fingerprint.
        messages: Full request history, including core evidence and tool returns.
        parameters: Request settings and tool/output schemas.
    Returns:
        A deterministic SHA-256 cache key.
    """
    payload = to_jsonable_python(
        {"identity": identity, "messages": messages, "parameters": parameters}
    )
    return hashlib.sha256(json.dumps(_stable(payload), sort_keys=True).encode()).hexdigest()


class ResponseCache:
    """Local response cache with strict misses and atomic refresh writes."""

    def __init__(self, root: Path) -> None:
        """Retain the local cache root without reading response content."""
        self.root = root

    def load(self, key: str) -> ModelResponse:
        """Read a cached response; a miss never falls back to a provider.

        Args:
            key: SHA-256 request identity.
        Returns:
            The previously observed response.
        Raises:
            LLMInvalidOutput: Response is missing or corrupt.
        """
        try:
            return TypeAdapter(ModelResponse).validate_json(
                (self.root / f"{key}.json").read_bytes()
            )
        except (OSError, ValidationError) as error:
            raise LLMInvalidOutput(f"Replay cache missing or invalid for {key}") from error

    def store(self, key: str, response: ModelResponse) -> None:
        """Atomically store a response, replacing that request on a fresh run.

        Args:
            key: Request identity.
            response: Raw observed output and usage, even if later rejected.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{uuid4().hex}.tmp"
        try:
            temporary.write_bytes(TypeAdapter(ModelResponse).dump_json(response))
            temporary.replace(self.root / f"{key}.json")
        finally:
            temporary.unlink(missing_ok=True)
