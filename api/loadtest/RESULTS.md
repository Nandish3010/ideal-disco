# Load test results (offline, single instance)

`make loadtest`: one uvicorn worker running `api/offline_server.py` (the real app on an in-memory Firestore, Routes calls
failing as an outage so nothing is billed, rate limiter off) and Locust for 60 s. Three simulated vehicles replay the
`blr-two-vehicles` scenario ticks at 20x (one `/location` every 0.25 s each, the 720 a minute the limiter budgets for), and
one client polls `/health` every 0.5 s. Run on an Apple M4 laptop, Python 3.13, 2026-10-06, while other jobs were using the machine: an earlier quieter run gave
`/location` 14 / 26 ms and `/health` 4 / 9 ms (p50 / p95), so read the tail as noisy.

| Endpoint | Requests | Failures | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| POST /location | 720 | 0 | 17 ms | 37 ms | 62 ms | 87 ms |
| GET /health | 118 | 0 | 4 ms | 21 ms | 43 ms | 77 ms |
| All 931 requests (incl. run start/end, confirm) | 931 | 0 | 15 ms | 33 ms | 61 ms | 87 ms |

Read it as the cost of the application code only. The in-memory store answers in microseconds, so a deployed Cloud Run
instance adds the Firestore round trips (a `/location` tick reads the run and writes the tick, the alert state and the
idempotency document) and the network. The Routes call, throttled to one per run every 20 s, is not in these numbers.
