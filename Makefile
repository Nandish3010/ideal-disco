# Python tooling comes from api/requirements-dev.txt (see CONTRIBUTING.md).
.PHONY: lint format test cov build run seed reset replay-offline openapi contract loadtest

lint:
	ruff check .
	ruff format --check .
	mypy api

format:
	ruff check --fix .
	ruff format .

test:
	pytest

cov:
	pytest --cov --cov-fail-under=80

# both images; api/data is the copy the deploy workflow makes (the build context is api/)
build:
	mkdir -p api/data && cp -r data/corridors data/scenarios api/data/
	docker build -t corridor-api api
	docker build -f Dockerfile.job -t corridor-job .

# no paid Google calls; Firestore is still the real database, so GOOGLE_APPLICATION_CREDENTIALS must be set
run:
	cd api && OFFLINE_AI=1 GEMINI_MODEL=offline uvicorn main:app --reload --port 8080

seed:
	python scripts/demo_seed.py

reset:
	python scripts/demo_reset.py

# starts a local OFFLINE_AI=1 API, replays data/scenarios/blr-two-vehicles.json against it, stops it
replay-offline:
	(cd api && OFFLINE_AI=1 RATE_LIMIT_DISABLED=1 DEVICE_TOKENS_DISABLED=1 GEMINI_MODEL=offline exec uvicorn main:app --port 8080) & pid=$$!; \
	sleep 4; (cd api && RATE_LIMIT_DISABLED=1 python offline_replay.py); rc=$$?; kill $$pid; exit $$rc

# api/openapi.json is generated from the app; CI runs `python -m api.export_openapi --check` and fails if it is stale
openapi:
	python -m api.export_openapi

# schemathesis against the in-memory app (api/offline_server.py) over loopback: every check, stateless, no Google calls
contract:
	(cd api && RATE_LIMIT_DISABLED=1 exec uvicorn offline_server:app --port 8081 --log-level warning) & pid=$$!; \
	curl -sf --retry 30 --retry-connrefused --retry-delay 1 http://127.0.0.1:8081/health >/dev/null && \
	schemathesis --config-file api/schemathesis.toml run http://127.0.0.1:8081/openapi.json \
	  --checks all --max-examples 20 --phases examples,coverage,fuzzing --seed 1; \
	rc=$$?; kill $$pid; exit $$rc

# 60 s of the scenario's three vehicles at x20 against the in-memory app; needs: pip install -r api/loadtest/requirements.txt
loadtest:
	(cd api && RATE_LIMIT_DISABLED=1 exec uvicorn offline_server:app --port 8082 --log-level warning) & pid=$$!; \
	curl -sf --retry 30 --retry-connrefused --retry-delay 1 http://127.0.0.1:8082/health >/dev/null && \
	locust -f api/loadtest/locustfile.py --headless -u 4 -r 4 -t 60s --host http://127.0.0.1:8082 --only-summary; \
	rc=$$?; kill $$pid; exit $$rc
