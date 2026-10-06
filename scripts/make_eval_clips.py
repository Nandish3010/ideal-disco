#!/usr/bin/env python3
"""Synthesize the evaluation clips with Cloud Text-to-Speech (synthetic voices, not field recordings).

Reads data/eval/labels.template.json, writes data/eval/synthetic/clipNN.mp3 (rotating en-IN voices and rates),
plus a Kannada-English mixed version of two clips (clipNN-kn.mp3, kn-IN voice), and synthetic/labels.json.
Skips clips that already exist, so a rerun costs nothing. One TTS call per clip; one retry on error.

Usage: GOOGLE_APPLICATION_CREDENTIALS=<key.json> python3 scripts/make_eval_clips.py
Paid calls: Cloud Text-to-Speech, one per clip written (12).
"""

import base64
import copy
import json
import sys
from pathlib import Path

from google.auth import default
from google.auth.transport.requests import AuthorizedSession

ROOT = Path(__file__).resolve().parent.parent / "data" / "eval"
OUT = ROOT / "synthetic"
EN_VOICES = ["en-IN-Neural2-A", "en-IN-Neural2-B", "en-IN-Neural2-C", "en-IN-Neural2-D"]
RATES = [0.95, 1.0, 1.05, 1.1, 1.0]
KN_VOICES = {"clip01": "kn-IN-Wavenet-A", "clip05": "kn-IN-Wavenet-B"}
# Mixed register as spoken on a call: Kannada glue words, English clinical terms and numbers.
KN_SCRIPTS = {
    "clip01": "ರೋಗಿಗೆ chest pain ಇದೆ. 58 ವರ್ಷದ male. BP 85 by 50, SpO2 91 percent. Conscious ಇದ್ದಾರೆ, breathing ಇದೆ.",
    "clip05": "ರೋಗಿಗೆ breathing difficulty ಇದೆ. 55 ವರ್ಷದ male. Respiratory rate 32, SpO2 89 percent, BP 130 by 80. Conscious ಇದ್ದಾರೆ.",
}

session = AuthorizedSession(default(scopes=["https://www.googleapis.com/auth/cloud-platform"])[0])
calls = 0


def synth(text: str, voice: str, rate: float) -> bytes:
    global calls
    body = {
        "input": {"text": text},
        "voice": {"languageCode": voice[:5], "name": voice},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": rate},
    }
    for attempt in (1, 2):  # one retry, no more
        calls += 1
        r = session.post("https://texttospeech.googleapis.com/v1/text:synthesize", json=body, timeout=30)
        if r.ok:
            return base64.b64decode(r.json()["audioContent"])
        print(f"TTS {voice} attempt {attempt}: HTTP {r.status_code} {r.text[:200]}", file=sys.stderr)
    raise SystemExit(f"TTS failed for {voice}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    clips = json.loads((ROOT / "labels.template.json").read_text())["clips"]
    labels = copy.deepcopy(clips)
    for i, (cid, c) in enumerate(sorted(clips.items())):
        labels[cid]["voice"] = EN_VOICES[i % len(EN_VOICES)]
        labels[cid]["speaking_rate"] = RATES[i % len(RATES)]
        labels[cid]["language"] = "en-IN"
        path = OUT / f"{cid}.mp3"
        if not path.exists():
            path.write_bytes(synth(c["script"], labels[cid]["voice"], labels[cid]["speaking_rate"]))
        if cid in KN_SCRIPTS:
            kn = copy.deepcopy(labels[cid])
            kn.update(
                script=KN_SCRIPTS[cid],
                voice=KN_VOICES[cid],
                speaking_rate=1.0,
                language="kn-IN mixed with English",
                description=c["description"] + " (Kannada-English mixed)",
            )
            labels[f"{cid}-kn"] = kn
            kpath = OUT / f"{cid}-kn.mp3"
            if not kpath.exists():
                kpath.write_bytes(synth(kn["script"], kn["voice"], 1.0))
    (OUT / "labels.json").write_text(
        json.dumps({"clips": dict(sorted(labels.items()))}, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"{len(list(OUT.glob('*.mp3')))} clips, {calls} TTS calls")


if __name__ == "__main__":
    main()
