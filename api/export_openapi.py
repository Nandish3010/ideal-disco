"""Write the OpenAPI document to api/openapi.json, or with --check fail if the committed file is stale:
    python -m api.export_openapi [--check]        (make openapi)
The document is built with GIT_SHA unset, so the version in it is always "dev"."""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / "openapi.json"


def render() -> str:
    os.environ.pop("GIT_SHA", None)
    sys.path.insert(0, str(HERE))
    from offline_server import (
        app,
    )  # the real app on a fake Firestore: importing main must not need credentials

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text() != text:
            print("api/openapi.json is stale: run `make openapi` and commit the result", file=sys.stderr)
            sys.exit(1)
        print("api/openapi.json is up to date")
    else:
        TARGET.write_text(text)
        print(f"wrote {TARGET.relative_to(HERE.parent)}")
