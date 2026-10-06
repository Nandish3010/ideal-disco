# Load test results (offline, single instance)

`make loadtest`: one uvicorn worker running `api/offline_server.py` (the real app on an in-memory Firestore, Routes calls
failing as an outage so nothing is billed, rate limiter off) and Locust for 60 s. Three simulated vehicles replay the
`blr-two-vehicles` scenario ticks at 20x (one `/location` every 0.25 s each, the 720 a minute the limiter budgets for), and
one client polls `/health` every 0.5 s. Run on an Apple M4 laptop, Python 3.13, 2026-10-06.

| Endpoint | Requests | Failures | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| POST /location | 717 | 0 | 14 ms | 26 ms | 33 ms | 71 ms |
| GET /health | 118 | 0 | 4 ms | 9 ms | 13 ms | 24 ms |
| All 928 requests (incl. run start/end, confirm) | 928 | 0 | 13 ms | 25 ms | 33 ms | 71 ms |

Read it as the cost of the application code only. The in-memory store answers in microseconds, so a deployed Cloud Run
instance adds the Firestore round trips (a `/location` tick reads the run and writes the tick, the alert state and the
idempotency document) and the network. The Routes call, throttled to one per run every 20 s, is not in these numbers.
