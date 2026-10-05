import os

from google.cloud import firestore

db = firestore.Client(project=os.environ.get("GCP_PROJECT", "green-corridor-2026"))
