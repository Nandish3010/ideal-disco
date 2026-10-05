"""In-memory stand-in for the slice of Firestore that api/ uses. One dict keyed by document path, no emulator, no network."""

import copy
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud.firestore import DELETE_FIELD, SERVER_TIMESTAMP, ArrayUnion, Increment

OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": lambda a, b: a == b,
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "in": lambda a, b: a in b,
    "array_contains": lambda a, b: isinstance(a, list) and b in a,
}
MISSING = object()


def _get(data: dict, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return MISSING
        data = data[part]
    return data


def _put(d: dict, dotted: str, v: Any, merge: bool = False) -> None:
    """Write one (possibly dotted) field, resolving the transform sentinels."""
    *parents, leaf = dotted.split(".")
    for p in parents:
        d = d.setdefault(p, {})
    old = d.get(leaf)
    if v is DELETE_FIELD:
        d.pop(leaf, None)
    elif v is SERVER_TIMESTAMP:
        d[leaf] = datetime.now(UTC)
    elif isinstance(v, ArrayUnion):
        d[leaf] = [*(old or []), *(x for x in v.values if x not in (old or []))]
    elif isinstance(v, Increment):
        d[leaf] = (old or 0) + v.value
    elif isinstance(v, dict):
        d[leaf] = old if merge and isinstance(old, dict) else {}
        for k, x in v.items():
            _put(d[leaf], k, x, merge)
    else:
        d[leaf] = copy.deepcopy(v)


class Snapshot:
    def __init__(self, ref: "Doc", data: dict | None):
        self.reference, self.id, self._data = ref, ref.id, data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        return copy.deepcopy(self._data)


class Doc:
    def __init__(self, fs: "FakeFirestore", path: str):
        self.fs, self.path, self.id = fs, path, path.rsplit("/", 1)[-1]

    def collection(self, name: str) -> "Collection":
        return Collection(self.fs, f"{self.path}/{name}")

    def get(self, transaction: Any = None) -> Snapshot:
        return Snapshot(self, self.fs.docs.get(self.path))

    def set(self, data: dict, merge: bool = False) -> None:
        doc = self.fs.docs.get(self.path, {}) if merge else {}
        for k, v in data.items():
            _put(doc, k, v, merge)
        self.fs.docs[self.path] = doc

    def update(self, data: dict) -> None:
        if self.path not in self.fs.docs:
            raise NotFound(self.path)
        for k, v in data.items():
            _put(self.fs.docs[self.path], k, v)

    def delete(self) -> None:
        self.fs.docs.pop(self.path, None)


class Query:
    def __init__(
        self,
        fs: "FakeFirestore",
        match: Callable[[str], bool],
        filters: tuple = (),
        order: tuple | None = None,
        n: int | None = None,
    ):
        self.fs, self.match, self.filters, self.order, self.n = fs, match, filters, order, n

    def _with(self, **kw: Any) -> "Query":
        return Query(self.fs, self.match, **{"filters": self.filters, "order": self.order, "n": self.n, **kw})

    def where(
        self, field_path: str | None = None, op_string: Any = None, value: Any = None, *, filter: Any = None
    ) -> "Query":
        if filter:
            field_path, op_string, value = filter.field_path, filter.op_string, filter.value
        op = (
            op_string if isinstance(op_string, str) else "=="
        )  # FieldFilter turns "== None" into an IS_NULL unary
        return self._with(filters=(*self.filters, (field_path, op, value)))

    def order_by(self, field: str, direction: str = "ASCENDING") -> "Query":
        return self._with(order=(field, direction == "DESCENDING"))

    def limit(self, n: int) -> "Query":
        return self._with(n=n)

    def stream(self, transaction: Any = None) -> list[Snapshot]:
        rows = []
        for path, data in self.fs.docs.items():
            if self.match(path) and all(
                (v := _get(data, f)) is not MISSING and OPS[op](v, val) for f, op, val in self.filters
            ):
                rows.append(Snapshot(Doc(self.fs, path), data))
        if self.order:  # like Firestore, a document without the order field is left out
            field, desc = self.order
            rows = [r for r in rows if _get(r._data or {}, field) is not MISSING]
            rows.sort(key=lambda r: _get(r._data or {}, field), reverse=desc)
        return rows[: self.n]


class Collection(Query):
    def __init__(self, fs: "FakeFirestore", path: str):
        depth = path.count("/") + 1
        super().__init__(fs, lambda p: p.startswith(path + "/") and p.count("/") == depth)
        self.path = path

    def document(self, doc_id: str | None = None) -> Doc:
        return Doc(self.fs, f"{self.path}/{doc_id or uuid.uuid4().hex[:20]}")

    def add(self, data: dict) -> tuple[datetime, Doc]:
        ref = self.document()
        ref.set(data)
        return datetime.now(UTC), ref


class Transaction:
    """Just enough of firestore.Transaction for @firestore.transactional: writes apply at once (the fake has one thread of
    control), so a transaction here checks the call shape, not contention."""

    _id = b"tx"
    _max_attempts = 5
    _read_only = False

    def _clean_up(self) -> None: ...

    def _begin(self, retry_id: Any = None) -> None: ...

    def _commit(self) -> list:
        return []

    def _rollback(self) -> None: ...

    def update(self, ref: Doc, data: dict) -> None:
        ref.update(data)


class FakeFirestore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def transaction(self) -> Transaction:
        return Transaction()

    def clear(self) -> None:
        self.docs.clear()

    def collection(self, name: str) -> Collection:
        return Collection(self, name)

    def collection_group(self, name: str) -> Query:
        return Query(self, lambda p: p.count("/") % 2 == 1 and p.split("/")[-2] == name)


def seed(db: FakeFirestore) -> None:
    """Like scripts/demo_seed.py: three scenario vehicles and a junctions/{id} doc per corridor junction."""
    for plate, kind in [("KA01AB1234", "ambulance"), ("KA01AB4321", "ambulance"), ("KA01FE5678", "fire")]:
        db.collection("vehicles").document(plate).set({"type": kind, "agency": "test", "active": True})
    for f in sorted((Path(__file__).resolve().parents[2] / "data" / "corridors").glob("*.json")):
        c = json.loads(f.read_text())
        for j in c["junctions"]:
            db.collection("junctions").document(f"{c['id']}_{j['id']}").set(
                {"phase": None, "lang": c["lang"]}, merge=True
            )
