import os
from typing import Any

from google.cloud import firestore

# Any: the call sites read untyped documents (to_dict() is Optional), and tests swap in an in-memory fake
db: Any = firestore.Client(project=os.environ.get("GCP_PROJECT", "green-corridor-2026"))
