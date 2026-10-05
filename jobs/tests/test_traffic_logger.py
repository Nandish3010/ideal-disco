"""traffic_logger with httpx and BigQuery stubbed: no network, no credentials."""

import importlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

KEY = "test-maps-key"


def encode(points: list[tuple[float, float]]) -> str:
    """Google encoded polyline, just enough to build fixtures."""
    out, prev = "", (0, 0)
    for lat, lng in points:
        cur = (round(lat * 1e5), round(lng * 1e5))
        for d in (cur[0] - prev[0], cur[1] - prev[1]):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out += chr((0x20 | (v & 0x1F)) + 63)
                v >>= 5
            out += chr(v + 63)
        prev = cur
    return out


# 4 points 0.001 deg of latitude apart: three segments of about 111 m, stop line at the end
PTS = [(12.9, 77.6), (12.901, 77.6), (12.902, 77.6), (12.903, 77.6)]
ROUTE = {
    "polyline": {"encodedPolyline": encode(PTS)},
    "duration": "95s",
    "travelAdvisory": {
        "speedReadingIntervals": [
            {"endPolylinePointIndex": 1, "speed": "NORMAL"},
            {"startPolylinePointIndex": 1, "endPolylinePointIndex": 2, "speed": "SLOW"},
            {"startPolylinePointIndex": 2, "endPolylinePointIndex": 3, "speed": "TRAFFIC_JAM"},
        ]
    },
}
SEG = 0.001 * 111320


@pytest.fixture
def tl(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("MAPS_SERVER_KEY", KEY + "\n")  # a secret mounted with a trailing newline
    monkeypatch.delitem(sys.modules, "traffic_logger", raising=False)
    return importlib.import_module("traffic_logger")


class FakeBQ:
    last: "FakeBQ"

    def __init__(self, **kw: Any):
        self.kw, self.rows, self.errors = kw, [], []
        FakeBQ.last = self

    def create_dataset(self, *a: Any, **kw: Any) -> None: ...
    def create_table(self, *a: Any, **kw: Any) -> None: ...

    def insert_rows_json(self, table: str, rows: list[dict]) -> list:
        self.rows += rows
        return self.errors


def test_key_is_stripped(tl: ModuleType) -> None:
    assert tl.KEY == KEY


def test_decode_google_reference_polyline(tl: ModuleType) -> None:
    assert tl.decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert tl.decode(encode(PTS)) == PTS
    assert tl.decode("") == []


def test_spans_from_speed_reading_intervals(tl: ModuleType) -> None:
    ivs = tl.spans(ROUTE)
    assert [i["speed"] for i in ivs] == ["NORMAL", "SLOW", "TRAFFIC_JAM"]
    assert ivs[0]["from_m"] == 0 and ivs[0]["to_m"] == pytest.approx(SEG, rel=0.01)
    assert ivs[1]["from_m"] == ivs[0]["to_m"] and ivs[2]["to_m"] == pytest.approx(3 * SEG, rel=0.01)
    assert tl.spans({"polyline": ROUTE["polyline"], "duration": "1s"}) == []  # no advisory: NORMAL


def run_main(tl: ModuleType, monkeypatch: pytest.MonkeyPatch, post: Any) -> FakeBQ:
    calls: list[dict] = []

    def fake_post(url: str, json: dict, headers: dict, timeout: float) -> Any:
        calls.append({"url": url, "headers": headers, "body": json})
        return post(len(calls))

    monkeypatch.setattr(tl.httpx, "post", fake_post)
    monkeypatch.setattr(tl.bigquery, "Client", FakeBQ)
    tl.main()
    FakeBQ.last.calls = calls  # type: ignore[attr-defined]
    return FakeBQ.last


def ok(route: dict = ROUTE) -> Any:
    return SimpleNamespace(status_code=200, json=lambda: {"routes": [route]})


def test_main_logs_one_row_per_approach(
    tl: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bq = run_main(tl, monkeypatch, lambda n: ok())
    calls = bq.calls  # type: ignore[attr-defined]
    assert bq.kw["location"] == "asia-south1" and len(calls) == len(bq.rows) > 0
    assert {c["headers"]["X-Goog-Api-Key"] for c in calls} == {KEY}  # no trailing newline in the header
    assert all(c["headers"]["X-Goog-FieldMask"] == tl.MASK for c in calls)
    row = bq.rows[0]
    assert row["junction_id"].startswith(("blr_", "hyd_")) and row["approach"] and row["routes_eta_s"] == 95.0
    assert row["jam_m"] == pytest.approx(
        SEG + 0.5 * SEG, rel=0.01
    )  # JAM span plus half the SLOW span, stops at NORMAL
    assert row["slow_m"] == pytest.approx(SEG, rel=0.01)
    assert f"inserted={len(bq.rows)} errors=[]" in capsys.readouterr().out


def test_failed_calls_leave_a_gap_and_never_log_the_key(
    tl: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def post(n: int) -> Any:
        if n == 1:
            return SimpleNamespace(status_code=429, json=lambda: {})
        if n == 2:
            raise tl.httpx.ConnectError(
                f"boom, key={KEY}"
            )  # a repr that carries the secret must not be printed
        return ok()

    bq = run_main(tl, monkeypatch, post)
    out = capsys.readouterr()
    assert len(bq.rows) == len(bq.calls) - 2  # type: ignore[attr-defined]
    assert "status=429" in out.err and "status=ConnectError" in out.err
    assert KEY not in out.out + out.err


def test_insert_errors_fail_the_job(tl: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    class BadBQ(FakeBQ):
        def __init__(self, **kw: Any):
            super().__init__(**kw)
            self.errors = [{"index": 0}]

    monkeypatch.setattr(tl.httpx, "post", lambda *a, **k: ok())
    monkeypatch.setattr(tl.bigquery, "Client", BadBQ)
    with pytest.raises(SystemExit) as e:
        tl.main()
    assert e.value.code == 1
