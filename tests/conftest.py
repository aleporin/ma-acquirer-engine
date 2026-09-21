"""Share offline fixtures and prohibit socket connections.

Owns: Network isolation and reusable run dependencies for tests.
Does not own: Live provider integration or dataset loading.
"""

import io
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.settings import Settings, load_settings


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject network connection attempts in the unit-test process."""

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network is forbidden in unit tests")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.fixture
def settings() -> Settings:
    """Load real configuration without touching transaction data."""
    return load_settings(Path(__file__).resolve().parents[1] / "config")


@pytest.fixture
def deps(settings: Settings, tmp_path: Path) -> Iterator[Deps]:
    """Inject one isolated logger and settings snapshot per test."""
    with run_logger(tmp_path, "test-run", "a" * 40, "not_implemented", io.StringIO()) as log:
        yield Deps(settings=settings, logger=log)
