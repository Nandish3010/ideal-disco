"""Offline load test: the scenario's vehicles drive their recorded ticks at x20 against the in-memory app
(api/offline_server.py), `make loadtest`. Three vehicles tick every 0.25 s (720 /location a minute, the budget the rate
limiter allows), one user polls /health, and each vehicle starts a fresh run when its scenario ends. Scenario runs make no
Routes calls, so nothing here costs money."""

import itertools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from locust import HttpUser, constant, constant_pacing, task

SCENARIO = json.loads(
    (Path(__file__).resolve().parents[2] / "data" / "scenarios" / "blr-two-vehicles.json").read_text()
)
SPEEDUP = 20  # scenario ticks are 5 s apart: one every 0.25 s here
TICK_S = 5 / SPEEDUP
_next_vehicle = itertools.count()


class Vehicle(HttpUser):
    """One scenario vehicle: start a run, send its ticks, end it, start over."""

    fixed_count = 3
    wait_time = constant_pacing(TICK_S)

    def on_start(self) -> None:
        self.vehicle = SCENARIO["vehicles"][next(_next_vehicle) % len(SCENARIO["vehicles"])]
        self.ticks: list[dict] = []
        self.run_id = ""
        self.n = 0
        self.base = datetime.now(UTC)

    def start_run(self) -> None:
        v = self.vehicle
        inc = self.client.post(
            "/incidents",
            json={"type": "fire" if v["type"] == "fire" else "medical", "severity_note": "load test"},
        ).json()["incident_id"]
        self.run_id = self.client.post(
            "/runs",
            json={
                "action": "start",
                "plate": v["plate"],
                "incident_id": inc,
                "corridor": SCENARIO["corridor"],
                "source": "sim",
                "scenario": "blr-two-vehicles",
            },
            name="/runs (start)",
        ).json()["run_id"]
        if v["type"] == "ambulance":  # a confirmed patient on board: preemption applies
            self.client.post(
                f"/runs/{self.run_id}/confirm", json={"tier": v["tier"]}, name="/runs/{id}/confirm"
            )
        self.ticks, self.base, self.n = list(v["ticks"]), datetime.now(UTC), 0

    @task
    def tick(self) -> None:
        if not self.ticks:
            if self.run_id:
                self.client.post("/runs", json={"action": "end", "run_id": self.run_id}, name="/runs (end)")
            self.start_run()
        k = self.ticks.pop(0)
        self.n += 1
        with self.client.post(
            "/location",
            json={
                "run_id": self.run_id,
                "lat": k["lat"],
                "lng": k["lng"],
                "speed_mps": float(k["speed_mps"]),
                "source": "sim",
                "t": (self.base + timedelta(seconds=k["t"])).isoformat(),
            },
            headers={"Idempotency-Key": f"{self.run_id}-{self.n}"},
            name="/location",
            catch_response=True,
        ) as r:
            if r.status_code == 403 or (
                r.ok and r.json().get("state") == "arrived"
            ):  # arrived: the run is over
                self.ticks = []
                r.success()


class Health(HttpUser):
    fixed_count = 1
    wait_time = constant(0.5)

    @task
    def health(self) -> None:
        self.client.get("/health")
