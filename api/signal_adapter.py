from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone


class SignalAdapter(ABC):
    """Phase 2 drops a real controller adapter in here; today only SimAdapter exists."""

    @abstractmethod
    def request_green(self, junction_id: str, approach: str, duration_s: float, run_ids: list[str],
                      sequence: list[dict] | None = None) -> None: ...


class SimAdapter(SignalAdapter):
    def __init__(self, db):  # db: google.cloud.firestore.Client on the (default) database
        self.db = db

    def request_green(self, junction_id, approach, duration_s, run_ids, sequence=None):
        until = datetime.now(timezone.utc) + timedelta(seconds=duration_s)
        self.db.collection("junctions").document(junction_id).set(
            {"phase": {"approach": approach, "until": until, "run_ids": run_ids, "sequence": sequence or []}}, merge=True)
