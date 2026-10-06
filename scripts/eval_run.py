#!/usr/bin/env python3
"""Evaluation runner: post clips to /triage, compare extracted fields to labels, compute accuracy."""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ponytail: vertex eval module import deferred to --vertex-eval flag handler


def get_api_base() -> str:
    """Get API base URL from env, default to Cloud Run URL."""
    return os.getenv("API_BASE", "https://corridor-api-919512130399.asia-south1.run.app")


# ponytail: the second registered ambulance, so a run does not supersede a demo run or rotate the demo token of KA01AB1234
PLATE = os.getenv("EVAL_PLATE", "KA01AB4321")
PACE_S = 6.5  # /triage and /log share a 10-per-minute per-IP bucket


def bind_device(api_base: str, plate: str = PLATE, device_id: str = "eval-runner") -> str | None:
    """Bind device to vehicle and return device_token (or None on error)."""
    try:
        body = json.dumps({"plate": plate, "device_id": device_id}).encode()
        req = urllib.request.Request(
            f"{api_base}/vehicles/bind",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            response = json.loads(resp.read())
            # Extract device_token from response (schema: returns the vehicle doc with bound_device_id)
            # The token should be in response or we use the device_id as fallback
            return response.get("device_token") or device_id
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"Error binding device (HTTP {e.code}): {error_body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error binding device: {e}", file=sys.stderr)
        return None


def load_labels(path: Path) -> dict[str, Any]:
    """Load expected labels from JSON file."""
    with open(path) as f:
        return json.load(f)["clips"]


def list_clips(data_dir: Path) -> list[str]:
    """List all clip files in order."""
    clips = [c for ext in ("m4a", "wav", "mp3") for c in data_dir.glob(f"clip*.{ext}")]
    return sorted(c.name for c in clips)


def clip_to_id(clip_name: str) -> str:
    """Convert clip filename to clip ID (e.g., clip01.m4a -> clip01)."""
    return Path(clip_name).stem


def load_clip_audio(path: Path) -> str:
    """Load audio file and return base64-encoded string."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def get_mime_type(clip_name: str) -> str:
    """Infer MIME type from file extension."""
    if clip_name.endswith(".m4a"):
        return "audio/mp4"
    elif clip_name.endswith(".wav"):
        return "audio/wav"
    elif clip_name.endswith(".mp3"):
        return "audio/mp3"
    else:
        return "audio/webm"


def vitals_match(expected: Any, actual: Any, tolerance: int = 5) -> bool:
    """Compare vitals dict with tolerance for numeric values."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False

    for key in set(expected.keys()) | set(actual.keys()):
        exp_val = expected.get(key)
        act_val = actual.get(key)
        if exp_val is None and act_val is None:
            continue
        if exp_val is None or act_val is None:
            return False
        if isinstance(exp_val, (int, float)) and isinstance(act_val, (int, float)):
            if abs(exp_val - act_val) > tolerance:
                return False
        elif exp_val != act_val:
            return False
    return True


def field_matches(expected: Any, actual: Any, field_name: str) -> bool:
    """Check if a field matches expected value (with tolerance for vitals)."""
    if field_name == "vitals":
        return vitals_match(expected, actual)
    if field_name == "trapped_persons":  # not stated means none, as acuity.py reads it
        return (expected or 0) == (actual or 0)
    # Exact match for other fields; strings compare case-insensitively
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    return expected == actual


def compute_field_accuracy(expected: dict, actual: dict, field_names: list[str]) -> tuple:
    """Compute accuracy for a set of fields. Returns (correct_count, total_count)."""
    correct = 0
    total = len(field_names)
    details = {}
    for field in field_names:
        exp = expected.get(field)
        act = actual.get(field)
        match = field_matches(exp, act, field)
        details[field] = match
        if match:
            correct += 1
    return correct, total, details


def dry_run_plan(data_dir: Path, labels: dict, clips: list[str]) -> str:
    """Return text description of what would be done."""
    lines = [f"DRY RUN: Would process {len(clips)} clips from {data_dir}"]
    lines.append("")
    for clip_name in clips:
        clip_id = clip_to_id(clip_name)
        label = labels.get(clip_id)
        if label:
            lines.append(f"  {clip_id}: {label.get('description', 'N/A')}")
    lines.append("")
    lines.append("Expected output: results.json next to the clips")
    return "\n".join(lines)


def create_incident_and_run(
    api_base: str, device_token: str | None = None, corridor: str = "blr"
) -> str | None:
    """Create a throwaway incident and run, return run_id (or None on error)."""
    try:
        # Create incident
        incident_body = json.dumps({"type": "medical", "severity_note": "Evaluation run"}).encode()
        req = urllib.request.Request(
            f"{api_base}/incidents",
            data=incident_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            incident_data = json.loads(resp.read())
            incident_id = incident_data.get("incident_id")

        # Create run
        run_body = json.dumps(
            {
                "action": "start",
                "plate": PLATE,
                "incident_id": incident_id,
                "corridor": corridor,
                "source": "sim",
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        if device_token:
            headers["X-Device-Token"] = device_token
        req = urllib.request.Request(f"{api_base}/runs", data=run_body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            run_data = json.loads(resp.read())
            return run_data.get("run_id")
    except Exception as e:
        print(f"Error creating incident/run: {e}", file=sys.stderr)
        return None


def post_clip_to_triage(
    api_base: str,
    run_id: str,
    clip_audio: str,
    mime: str,
    device_token: str | None = None,
    vehicle_type: str = "ambulance",
    path: str = "/triage",
) -> dict | None:
    """Post clip to /triage (or /log), return response or None on error (no retry: the API already retries once)."""
    try:
        body = json.dumps(
            {"run_id": run_id, "vehicle_type": vehicle_type, "audio_b64": clip_audio, "mime": mime}
        ).encode()
        headers = {"Content-Type": "application/json"}
        if device_token:
            headers["X-Device-Token"] = device_token
        req = urllib.request.Request(f"{api_base}{path}", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"HTTP {e.code}: {error_body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error posting clip: {e}", file=sys.stderr)
        return None


FIELDS = ["age", "sex", "complaint", "conscious", "breathing", "vitals", "trapped_persons"]


def interventions_match(expected: list, actual: list) -> bool:
    """Same set of intervention names (case-insensitive). Dose and time are not scored."""
    names = lambda xs: {(x.get("name") or "").strip().lower() for x in xs or []}  # noqa: E731
    return names(expected) == names(actual)


def run_evaluation(
    api_base: str, data_dir: Path, labels: dict, clips: list[str], device_token: str | None = None
) -> dict[str, Any]:
    """Post each clip once (no retry: the API already retries internally); returns raw responses, see score()."""
    run_id = create_incident_and_run(api_base, device_token)
    if not run_id:
        print("Failed to create incident/run", file=sys.stderr)
        return {"clips": {}, "summary": {}}
    raw = {"run_id": run_id, "clips": {}}
    for n, clip_name in enumerate(clips):
        clip_id = clip_to_id(clip_name)
        label = labels.get(clip_id)
        clip_path = data_dir / clip_name
        if not label or not clip_path.exists():
            print(f"Warning: {clip_name} has no label or file", file=sys.stderr)
            continue
        expected = label.get("expected_fields", {})
        endpoint = "/log" if "interventions" in expected else "/triage"  # an intervention note goes to /log
        vehicle_type = "fire" if expected.get("incident_type") == "fire" else "ambulance"
        if n:
            time.sleep(PACE_S)
        t0 = time.monotonic()
        response = post_clip_to_triage(
            api_base,
            run_id,
            load_clip_audio(clip_path),
            get_mime_type(clip_name),
            device_token,
            vehicle_type,
            endpoint,
        )
        raw["clips"][clip_id] = {
            "endpoint": endpoint,
            "latency_s": round(time.monotonic() - t0, 2),
            "response": response,
        }
    return raw


def score(raw: dict, labels: dict) -> dict[str, Any]:
    """Score raw responses against labels. A clip with no response (422 or any failure) is wrong on everything."""
    results = {"run_id": raw.get("run_id"), "clips": {}, "summary": {}}
    field_hits = {f: [] for f in FIELDS}
    field_accuracies, tier_accuracies, latencies, interventions_ok = [], [], [], []

    for clip_id, r in raw["clips"].items():
        label = labels[clip_id]
        expected = label.get("expected_fields", {})
        expected_tier = label.get("expected_tier")
        is_log = r["endpoint"] == "/log"
        response = r["response"]
        entry = {
            "description": label.get("description"),
            "endpoint": r["endpoint"],
            "latency_s": r["latency_s"],
            "raw": r,
        }
        if not response:
            entry.update(error="failed_to_post", expected_tier=expected_tier, tier_match=False)
            if is_log:
                interventions_ok.append(False)
            else:
                field_accuracies.append(0.0)
                for f in FIELDS:
                    field_hits[f].append(False)
                if expected_tier:
                    tier_accuracies.append(False)
            results["clips"][clip_id] = entry
            continue

        extracted = response.get("fields", {})
        latencies.append(r["latency_s"])
        entry.update(extracted=extracted, expected=expected, transcript_en=response.get("transcript_en"))
        if is_log:
            ok = interventions_match(expected.get("interventions"), response.get("interventions"))
            interventions_ok.append(ok)
            entry.update(interventions_match=ok, interventions=response.get("interventions"))
        else:
            suggested_tier = response.get("suggested_tier")
            field_correct, field_total, field_details = compute_field_accuracy(expected, extracted, FIELDS)
            for f, hit in field_details.items():
                field_hits[f].append(hit)
            field_accuracies.append(field_correct / field_total)
            tier_match = suggested_tier == expected_tier
            if expected_tier:
                tier_accuracies.append(tier_match)
            entry.update(
                expected_tier=expected_tier,
                suggested_tier=suggested_tier,
                tier_match=tier_match,
                field_accuracy=field_correct / field_total,
                field_details=field_details,
            )
        results["clips"][clip_id] = entry

    s = results["summary"]
    if field_accuracies:
        s["overall_accuracy"] = sum(field_accuracies) / len(field_accuracies)
        s["field_count"] = len(field_accuracies)
        s["per_field_accuracy"] = {f: sum(h) / len(h) for f, h in field_hits.items() if h}
    if tier_accuracies:
        s["tier_accuracy"] = sum(tier_accuracies) / len(tier_accuracies)
        s["tier_count"] = len(tier_accuracies)
    if interventions_ok:
        s["interventions_accuracy"] = sum(interventions_ok) / len(interventions_ok)
        s["interventions_count"] = len(interventions_ok)
    if latencies:
        s["latency_mean_s"] = round(sum(latencies) / len(latencies), 2)
        s["latency_max_s"] = max(latencies)
    s["failed_clips"] = sum(1 for c in results["clips"].values() if "error" in c)
    return results


def markdown_table(results: dict) -> str:
    """Generate markdown table of results."""
    lines = [
        "| Clip | Description | Endpoint | Expected Tier | Suggested Tier | Tier Match | Field Accuracy | Latency |",
        "|------|-------------|----------|---------------|----------------|------------|----------------|---------|",
    ]
    for clip_id in sorted(results.get("clips", {})):
        c = results["clips"][clip_id]
        desc = c.get("description") or ""
        lat = f"{c['latency_s']:.1f} s"
        if "error" in c:
            lines.append(
                f"| {clip_id} | {desc} | {c['endpoint']} | {c.get('expected_tier') or '-'} | ERROR | ✗ | 0% | {lat} |"
            )
        elif c["endpoint"] == "/log":
            lines.append(
                f"| {clip_id} | {desc} | /log | - | - | - | interventions {'✓' if c['interventions_match'] else '✗'} | {lat} |"
            )
        else:
            tm = "✓" if c["tier_match"] else "✗"
            lines.append(
                f"| {clip_id} | {desc} | /triage | {c['expected_tier']} | {c['suggested_tier']} | {tm} | {c['field_accuracy']:.0%} | {lat} |"
            )
    s = results.get("summary", {})
    if "per_field_accuracy" in s:
        lines += ["", "| Field | Accuracy |", "|-------|----------|"]
        lines += [f"| {f} | {a:.0%} |" for f, a in s["per_field_accuracy"].items()]
    return "\n".join(lines)


def firestore_runs(project: str = "green-corridor-2026") -> list[dict]:
    """All docs in Firestore `runs` via the public REST API (reads are open), as {field: string value}."""
    base = f"https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/runs"
    runs, token = [], ""
    while True:
        url = f"{base}?pageSize=300&mask.fieldPaths=acuity_tier&mask.fieldPaths=confirmed_tier" + (
            f"&pageToken={token}" if token else ""
        )
        with urllib.request.urlopen(url, timeout=20) as resp:
            page = json.loads(resp.read())
        for d in page.get("documents", []):
            runs.append({k: v.get("stringValue") for k, v in d.get("fields", {}).items()})
        token = page.get("nextPageToken", "")
        if not token:
            return runs


def agreement() -> dict:
    """Crew agreement: suggested tier (acuity_tier, from /triage) vs the crew's tap (confirmed_tier), runs with both."""
    both = [r for r in firestore_runs() if r.get("acuity_tier") and r.get("confirmed_tier")]
    same = sum(r["acuity_tier"] == r["confirmed_tier"] for r in both)
    return {"n": len(both), "agree": same, "agreement": same / len(both) if both else None}


def submit_to_vertex_eval(results: dict) -> None:
    """Submit clip/response pairs to Vertex AI Gen AI Evaluation Service (vertex-eval flag)."""
    # ponytail: deferred implementation - create EvalTask with exact_match metric
    # import vertexai
    # from vertexai.evaluation import EvalTask
    # Only runs if --vertex-eval is set; cannot run without proper credentials
    print("Vertex AI Evaluation Service submission is not yet implemented.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Evaluation runner for triage clips")
    parser.add_argument("--dry-run", action="store_true", help="List plan without posting to API")
    parser.add_argument(
        "--clips", type=Path, default=Path("data/eval"), help="directory of clipNN.{m4a,wav,mp3}"
    )
    parser.add_argument("--labels", type=Path, default=Path("data/eval/labels.json"))
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="re-score the raw responses in <clips>/results.json (no API calls)",
    )
    parser.add_argument(
        "--agreement",
        action="store_true",
        help="crew agreement: suggested vs confirmed tier over Firestore runs (free, no clips)",
    )
    parser.add_argument(
        "--vertex-eval", action="store_true", help="Also submit to Vertex AI Evaluation Service (not run)"
    )
    args = parser.parse_args()

    if args.agreement:
        a = agreement()
        print(json.dumps(a))
        if a["n"]:
            print(f"Crew agreement: {a['agree']}/{a['n']} = {a['agreement']:.0%} (runs with both tiers)")
        return

    data_dir, labels_path = args.clips, args.labels

    if not labels_path.exists():
        print(
            f"Error: {labels_path} not found. Create from labels.template.json and name it labels.json.",
            file=sys.stderr,
        )
        sys.exit(1)

    labels = load_labels(labels_path)
    clips = list_clips(data_dir)

    if args.dry_run:
        # For dry-run, show plan based on labels even if clips don't exist yet
        if not clips:
            clips = sorted([f"clip{i:02d}.m4a" for i in range(1, len(labels) + 1)])
        print(dry_run_plan(data_dir, labels, clips))
        return

    if not clips:
        print(f"Error: No audio clips found in {data_dir}", file=sys.stderr)
        sys.exit(1)

    results_path = data_dir / "results.json"
    if args.rescore:
        raw = json.loads(results_path.read_text())
        raw = {"run_id": raw.get("run_id"), "clips": {k: c["raw"] for k, c in raw["clips"].items()}}
    else:
        api_base = get_api_base()
        print(f"Running evaluation against {api_base}...", file=sys.stderr)
        device_token = bind_device(api_base)
        if not device_token:
            print("Failed to bind device; continuing without token", file=sys.stderr)
        raw = run_evaluation(api_base, data_dir, labels, clips, device_token)
    results = score(raw, labels)

    # Write results and the markdown table next to the clips
    results_path.write_text(json.dumps(results, indent=2) + "\n")
    table = markdown_table(results)
    (data_dir / "results.md").write_text(table + "\n")
    print(f"Results written to {results_path}", file=sys.stderr)

    print("\n## Evaluation Results\n")
    print(table)
    if results["summary"]:
        print("\n### Summary\n")
        for key, val in results["summary"].items():
            if isinstance(val, float) and not key.endswith("_s"):
                print(f"- **{key}**: {val:.1%}")
            elif not isinstance(val, dict):
                print(f"- **{key}**: {val}")

    if args.vertex_eval:
        print("\nVertex AI Evaluation Service flag detected (--vertex-eval)", file=sys.stderr)
        submit_to_vertex_eval(results)


if __name__ == "__main__":
    main()
