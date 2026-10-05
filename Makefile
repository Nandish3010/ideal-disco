# Python tooling comes from api/requirements-dev.txt (see CONTRIBUTING.md).
.PHONY: lint format test cov build run seed reset replay-offline

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
