"""The generated API documentation: /docs, /openapi.json, and that every endpoint is fully described."""

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

import main

ROOT = Path(__file__).resolve().parents[2]
HTTP = {"get", "post", "put", "patch", "delete"}


def schema(client: TestClient) -> dict:
    return client.get("/openapi.json").json()


def component(doc: dict, ref: str) -> dict:
    return doc["components"]["schemas"][ref.rsplit("/", 1)[1]]


def operations(doc: dict) -> list[tuple[str, str, dict]]:
    return [(m.upper(), p, op) for p, item in doc["paths"].items() for m, op in item.items() if m in HTTP]


def test_docs_and_the_schema_are_served(client: TestClient) -> None:
    assert "swagger-ui" in client.get("/docs").text
    info = schema(client)["info"]
    assert info["title"] == "Emergency Green Corridor API" and info["version"] == main.VERSION


def test_the_version_is_the_short_git_sha_from_the_environment() -> None:
    out = subprocess.run(
        [sys.executable, "-c", "import offline_server, main; print(main.VERSION)"],
        cwd=ROOT / "api",
        env={"PATH": "", "GIT_SHA": "0123456789abcdef"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.splitlines()[-1] == "0123456"


def test_every_endpoint_has_a_tag_a_summary_and_the_shared_error_responses(client: TestClient) -> None:
    doc = schema(client)
    tags = {t["name"] for t in doc["tags"]}
    ops = operations(doc)
    assert len(ops) == 16
    for method, path, op in ops:
        assert op["tags"] and set(op["tags"]) <= tags, f"{method} {path}"
        assert op["summary"], f"{method} {path}"
        for code in ("429", "500", "503"):
            assert op["responses"][code] == {"$ref": "#/components/responses/Error"}, (
                f"{method} {path} {code}"
            )


def test_the_error_envelope_is_one_shared_response(client: TestClient) -> None:
    doc = schema(client)
    shared = doc["components"]["responses"]["Error"]
    assert "X-Request-Id" in shared["headers"]
    assert shared["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ErrorEnvelope"}
    assert component(doc, "#/components/schemas/ErrorEnvelope")["examples"]
    assert "HTTPValidationError" not in doc["components"]["schemas"]  # 422 is the envelope here


def test_every_request_and_200_response_has_an_example(client: TestClient) -> None:
    doc = schema(client)
    for method, path, op in operations(doc):
        ok = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert component(doc, ok["$ref"]).get("examples"), f"{method} {path} response"
        body = op.get("requestBody")
        if body:
            req = body["content"]["application/json"]["schema"]
            assert component(doc, req["$ref"]).get("examples"), f"{method} {path} request"


def test_the_idempotency_header_is_documented_on_location(client: TestClient) -> None:
    op = schema(client)["paths"]["/location"]["post"]
    assert any(p["name"].lower() == "idempotency-key" for p in op["parameters"])
    assert "Idempotent-Replayed" in op["responses"]["200"]["headers"]


def test_the_committed_openapi_json_is_current() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "api.export_openapi", "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
