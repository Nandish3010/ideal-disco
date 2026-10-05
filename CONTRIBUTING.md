# Contributing

## Flow

1. Branch from `main`: `git switch -c <area>/<what>` (for example `chore/python-quality`, `fix/ack-latency`).
2. Keep commits small and logical, with a short imperative subject. Commits carry no co-author trailers or tool attributions.
3. Open a pull request against `main`. Checks must be green; merge with squash, the pull request title becomes the commit subject, delete the branch.
4. Merges to `main` deploy: `api/**` and `data/**` redeploy the API, `jobs/**` and `Dockerfile.job` redeploy the traffic logger, `web/**` redeploys the site.

The `checks` workflow also greps the whole tree for tool attributions. `pre-commit install` runs the same grep locally, plus ruff and the web linters.

## Set up

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r api/requirements-dev.txt -r api/requirements.txt
pre-commit install            # optional; web hooks also need: cd web && npm ci
```

`make lint` (ruff, ruff format check, mypy), `make format`, `make test`, `make cov` (fails under 80% coverage).

## Offline testing, no cost

Tests never call Google. `OFFLINE_AI=1` is set for them: no Gemini, Translation, Text-to-Speech, Storage or Routes calls, and an in-memory Firestore stands in for the database (`api/tests/fakefs.py`). Network sockets are refused during the test run, so an accidental call fails loudly instead of billing.

- `make test` runs everything in about two seconds. The scenario replay (`api/tests/test_replay.py`) drives `data/scenarios/blr-two-vehicles.json` through the API with no sleeping.
- `make run` starts the API with `OFFLINE_AI=1` against the real Firestore (needs `GOOGLE_APPLICATION_CREDENTIALS`); `make replay-offline` replays the scenario against it. See `SCHEMA.md`, "Dev-only: OFFLINE_AI=1".

## Cost rule

Paid Google APIs (Gemini, Routes, Text-to-Speech, Translation, BigQuery queries) are never called from tests, scripts you run casually, or CI. If you need a live call, make it once, by hand, on a small input, and say so in the pull request. Never set `OFFLINE_AI` in a deploy workflow.

## Style

Python: ruff (line length 110) and mypy; `api/tests` and new modules are fully typed, older modules are checked but not required to be annotated. Web: eslint and prettier in `web/`. Keep changes small, and update `SCHEMA.md` when an endpoint or a Firestore field changes.
