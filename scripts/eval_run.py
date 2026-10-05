#!/usr/bin/env python3
"""Evaluation runner: post clips to /triage, compare extracted fields to labels, compute accuracy."""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ponytail: vertex eval module import deferred to --vertex-eval flag handler


def get_api_base() -> str:
    """Get API base URL from env, default to Cloud Run URL."""
    return os.getenv("API_BASE", "https://green-corridor-2026-emg.run.app")


def bind_device(api_base: str, plate: str = "KA01AB1234", device_id: str = "eval-runner") -> str | None:
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
    clips = sorted(data_dir.glob("clip*.m4a")) + sorted(data_dir.glob("clip*.wav"))
    return [c.name for c in clips]


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
    # Exact match for other fields (including string complaint)
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
    lines.append("Expected output: data/eval/results.json")
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
                "plate": "KA01AB1234",
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
    api_base: str, run_id: str, clip_audio: str, mime: str, device_token: str | None = None
) -> dict | None:
    """Post clip to /triage endpoint, return response or None on error."""
    try:
        body = json.dumps(
            {"run_id": run_id, "vehicle_type": "ambulance", "audio_b64": clip_audio, "mime": mime}
        ).encode()
        headers = {"Content-Type": "application/json"}
        if device_token:
            headers["X-Device-Token"] = device_token
        req = urllib.request.Request(f"{api_base}/triage", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"HTTP {e.code}: {error_body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error posting clip: {e}", file=sys.stderr)
        return None


def run_evaluation(
    api_base: str, data_dir: Path, labels: dict, clips: list[str], device_token: str | None = None
) -> dict[str, Any]:
    """Run evaluation: post clips, compare results, compute accuracy."""
    results = {"clips": {}, "summary": {}}

    # Create incident and run (reused for all clips)
    run_id = create_incident_and_run(api_base, device_token)
    if not run_id:
        print("Failed to create incident/run", file=sys.stderr)
        return results

    field_accuracies = []
    tier_accuracies = []

    for clip_name in clips:
        clip_id = clip_to_id(clip_name)
        label = labels.get(clip_id)
        if not label:
            continue

        clip_path = data_dir / clip_name
        if not clip_path.exists():
            print(f"Warning: {clip_name} not found", file=sys.stderr)
            continue

        # Load and post clip
        audio_b64 = load_clip_audio(clip_path)
        mime = get_mime_type(clip_name)
        response = post_clip_to_triage(api_base, run_id, audio_b64, mime, device_token)
        if not response:
            results["clips"][clip_id] = {"error": "failed_to_post"}
            continue

        # Extract fields from response
        extracted = response.get("fields", {})
        suggested_tier = response.get("suggested_tier")
        expected = label.get("expected_fields", {})
        expected_tier = label.get("expected_tier")

        # Compute field accuracy
        field_names = ["age", "sex", "complaint", "conscious", "breathing", "vitals", "trapped_persons"]
        field_correct, field_total, field_details = compute_field_accuracy(expected, extracted, field_names)

        # Compute tier accuracy
        tier_match = suggested_tier == expected_tier
        if expected_tier:  # Only count if we have an expected tier
            tier_accuracies.append(tier_match)

        field_accuracies.append(field_correct / field_total if field_total > 0 else 0)

        results["clips"][clip_id] = {
            "description": label.get("description"),
            "expected_tier": expected_tier,
            "suggested_tier": suggested_tier,
            "tier_match": tier_match,
            "field_accuracy": field_correct / field_total if field_total > 0 else 0,
            "field_details": field_details,
            "extracted": extracted,
            "expected": expected,
        }

    # Compute summary
    if field_accuracies:
        results["summary"]["overall_accuracy"] = sum(field_accuracies) / len(field_accuracies)
        results["summary"]["field_count"] = len(field_accuracies)
    if tier_accuracies:
        results["summary"]["tier_accuracy"] = sum(tier_accuracies) / len(tier_accuracies)
        results["summary"]["tier_count"] = len(tier_accuracies)

    return results


def markdown_table(results: dict) -> str:
    """Generate markdown table of results."""
    lines = [
        "| Clip | Description | Expected Tier | Suggested Tier | Tier Match | Field Accuracy |",
        "|------|-------------|---------------|--------------------|--------------|",
    ]
    for clip_id in sorted(results.get("clips", {}).keys()):
        clip = results["clips"][clip_id]
        if "error" in clip:
            lines.append(f"| {clip_id} | ERROR | - | - | - | - |")
        else:
            desc = clip.get("description", "")[:40]
            exp_tier = clip.get("expected_tier", "N/A")
            sug_tier = clip.get("suggested_tier", "N/A")
            tier_match = "✓" if clip.get("tier_match") else "✗"
            field_acc = f"{clip.get('field_accuracy', 0):.0%}"
            lines.append(f"| {clip_id} | {desc} | {exp_tier} | {sug_tier} | {tier_match} | {field_acc} |")
    return "\n".join(lines)


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
        "--vertex-eval", action="store_true", help="Also submit to Vertex AI Evaluation Service (not run)"
    )
    args = parser.parse_args()

    data_dir = Path("data/eval")
    labels_path = Path("data/eval/labels.json")

    # Load or use template
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

    # Run evaluation
    api_base = get_api_base()
    print(f"Running evaluation against {api_base}...", file=sys.stderr)

    # Bind device to get token
    device_token = bind_device(api_base)
    if not device_token:
        print("Failed to bind device; continuing without token", file=sys.stderr)

    results = run_evaluation(api_base, data_dir, labels, clips, device_token)

    # Write results
    results_path = Path("data/eval/results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {results_path}", file=sys.stderr)

    # Print table
    print("\n## Evaluation Results\n")
    print(markdown_table(results))
    if results["summary"]:
        print("\n### Summary\n")
        for key, val in results["summary"].items():
            if isinstance(val, float):
                print(f"- **{key}**: {val:.1%}")
            else:
                print(f"- **{key}**: {val}")

    # Vertex eval (if requested)
    if args.vertex_eval:
        print("\nVertex AI Evaluation Service flag detected (--vertex-eval)", file=sys.stderr)
        submit_to_vertex_eval(results)


if __name__ == "__main__":
    main()
