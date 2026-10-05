"""Test harness: offline mode, an in-memory Firestore, no network. Env and the db stub must be in place before main imports."""

import os
import socket
import sys
from collections.abc import Iterator
from types import ModuleType

os.environ["OFFLINE_AI"] = "1"
os.environ["RATE_LIMIT_DISABLED"] = (
    "1"  # tests call far faster than a person; test_ratelimit.py turns it back on
)
os.environ.setdefault("GCP_PROJECT", "test-project")

import pytest
from fastapi.testclient import TestClient

from fakefs import FakeFirestore, seed

fake = FakeFirestore()
# the real firestore_client builds a credentialed client at import, so main and report get the fake instead
stub = ModuleType("firestore_client")
stub.db = fake  # type: ignore[attr-defined]
sys.modules["firestore_client"] = stub

import main  # noqa: E402
import ratelimit  # noqa: E402
import report  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def no_network() -> Iterator[None]:
    """Session-wide so module-scoped fixtures are covered too: no sockets, and report.py never builds a BigQuery client."""

    def refuse(*_: object, **__: object) -> None:
        raise RuntimeError("network is off in tests")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket.socket, "connect", refuse)
        mp.setattr(report, "to_bigquery", lambda doc: None)
        yield


@pytest.fixture(autouse=True)
def db() -> Iterator[FakeFirestore]:
    fake.clear()
    ratelimit._buckets.clear()
    yield fake


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def seeded(db: FakeFirestore) -> FakeFirestore:
    seed(db)
    return db
