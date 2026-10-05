"""Alert audio: localize (conversational English by default; ALERT_LANG=kn/te/corridor for colloquial Kannada/Telugu with English loanwords), synthesize MP3, store in the media bucket. Failure -> None, never raises."""
import hashlib
import json
import os

import re

from google import genai
from google.api_core.exceptions import GoogleAPIError
from google.cloud import storage, texttospeech, translate_v3
from google.genai import types

PROJECT = os.environ.get("GCP_PROJECT", "green-corridor-2026")
BUCKET = os.environ.get("MEDIA_BUCKET", "green-corridor-2026-media")
# Wavenet/Neural2 where the language has one; te-IN has only Standard. Unknown language falls back to en-IN.
VOICES = {"kn": ("kn-IN", "kn-IN-Wavenet-A"), "te": ("te-IN", "te-IN-Standard-A"), "en": ("en-IN", "en-IN-Neural2-A")}
TIMEOUT_S = 8
LOCALIZE_TIMEOUT_MS = 6000
_loc_cache: dict = {}  # (text_en, lang) -> localized line
SYSTEM_EN = (
    "Rewrite this traffic-police alert as a traffic constable would hear it on a radio, in conversational spoken Indian English. "
    "Short sentences, plain words, numbers spoken naturally (a 520 metre queue, about 2 minutes), no bullets, no symbols, no capital-letter "
    "shouting. Write numbers as digits, never spelled out. Stay close to the wording of the examples. End with an imperative "
    "(Start clearing now / Keep clearing). Keep every number exactly. Output plain text, no quotes.")
SYSTEM = (
    "Rewrite this traffic-police alert as a Bengaluru traffic constable would say it aloud in everyday spoken Kannada "
    "(for `kn`) / Hyderabad spoken Telugu (for `te`). Keep these words in English, Latin script: ambulance, fire engine, "
    "police, critical, urgent, left, right, straight, signal, queue, metre(s), minute(s), second(s), side. Use colloquial "
    "verb forms (e.g. ಬರ್ತಿದೆ, ಹೋಗ್ತಿದೆ, ಇದೆ), short phrases, no honorific formality, no pure-Kannada coinages for "
    "technical words. Keep every number exactly. Output one line, no quotes.")
NAMES = {"en": "English", "kn": "Kannada", "te": "Telugu"}
SCRIPT = {"kn": "\u0c80-\u0cff", "te": "\u0c00-\u0c7f"}  # a Telugu answer for kn (or the reverse) is a failure
SHOTS = {
    "en": [
        ("AMBULANCE CRITICAL · 520 m queue on your south-east approach · going STRAIGHT · arrives in 2 min",
         "Ambulance coming, critical case. There's a 520 metre queue on your south-east side. It's going straight. Reaches you in about 2 minutes. Start clearing now."),
        ("STOP CROSS TRAFFIC · AMBULANCE CRITICAL · 80 m queue on your north approach · turning LEFT · arrives in 30 s",
         "Stop cross traffic now. Ambulance is 30 seconds out, turning left."),
        ("UPDATE · AMBULANCE CRITICAL · 700 m queue on your south-east approach · going STRAIGHT · arrives in 3 min",
         "Update. Queue on your south-east side has grown to 700 metres. Ambulance still about 3 minutes away. Keep clearing."),
    ],
    "kn": [
        ("AMBULANCE CRITICAL · 520 m queue on your south-east approach · going STRAIGHT · arrives in 2 min",
         "Ambulance critical · ನಿಮ್ಮ south-east side ಇಂದ 520 metre queue ಇದೆ · straight ಹೋಗ್ತಿದೆ · 2 minute ಅಲ್ಲಿ ಬರ್ತಿದೆ"),
        ("STOP CROSS TRAFFIC · AMBULANCE CRITICAL · 80 m queue on your north approach · turning LEFT · arrives in 30 s",
         "Cross traffic ನಿಲ್ಲಿಸಿ · ambulance 30 second ಅಲ್ಲಿ ಬರ್ತಿದೆ · left ತಿರುಗ್ತಿದೆ"),
        ("UPDATE · FIRE ENGINE URGENT · 640 m queue on your west approach · turning RIGHT · arrives in 3 min",
         "Update · fire engine urgent · ನಿಮ್ಮ west side ಇಂದ queue ಈಗ 640 metre ಆಗಿದೆ · right ತಿರುಗ್ತಿದೆ · 3 minute ಅಲ್ಲಿ ಬರ್ತಿದೆ"),
    ],
    "te": [
        ("AMBULANCE CRITICAL · 520 m queue on your south-east approach · going STRAIGHT · arrives in 2 min",
         "Ambulance critical · మీ south-east side నుంచి 520 metre queue ఉంది · straight వెళ్తోంది · 2 minute లో వస్తోంది"),
        ("STOP CROSS TRAFFIC · AMBULANCE CRITICAL · 80 m queue on your north approach · turning LEFT · arrives in 30 s",
         "Cross traffic ఆపండి · ambulance 30 second లో వస్తోంది · left తిరుగుతోంది"),
    ],
}
def _alert_lang(lang: str) -> str:
    """ALERT_LANG overrides the corridor language for alerts; `corridor` keeps it. Default en (judges read English)."""
    a = os.environ.get("ALERT_LANG", "en")
    return lang if a == "corridor" else a


# fallback template pieces: same mixed register, English loanwords in Latin script
T = {"kn": dict(stop="Cross traffic ನಿಲ್ಲಿಸಿ", update="Update", side="ನಿಮ್ಮ {a} side ಇಂದ {n} metre queue ಇದೆ", noq="ನಿಮ್ಮ {a} side ನಲ್ಲಿ queue ಇಲ್ಲ",
                straight="straight ಹೋಗ್ತಿದೆ", turn="{m} ತಿರುಗ್ತಿದೆ", eta="{n} {u} ಅಲ್ಲಿ ಬರ್ತಿದೆ"),
     "te": dict(stop="Cross traffic ఆపండి", update="Update", side="మీ {a} side నుంచి {n} metre queue ఉంది", noq="మీ {a} side లో queue లేదు",
                straight="straight వెళ్తోంది", turn="{m} తిరుగుతోంది", eta="{n} {u} లో వస్తోంది")}
_cache: dict = {}  # ponytail: per-instance dict keyed by text+lang; a cold instance just regenerates


def _log(**kw):
    print(json.dumps(kw), flush=True)


def translate(text: str, lang: str) -> str:
    """Cloud Translation; raises GoogleAPIError. No-op for English."""
    if lang == "en":
        return text
    r = translate_v3.TranslationServiceClient().translate_text(
        contents=[text], target_language_code=lang, source_language_code="en", mime_type="text/plain",
        parent=f"projects/{PROJECT}/locations/global", timeout=TIMEOUT_S)
    return r.translations[0].translated_text


def parse_alert(text_en: str) -> dict:
    """Recover alert parts from main.alert_text()'s English line (used when the caller passes no `parts`)."""
    segs = [x.strip() for x in text_en.split(" · ")]
    stage = {"STOP CROSS TRAFFIC": "STOP", "UPDATE": "UPDATE"}.get(segs[0], "PREPARE")
    if stage != "PREPARE":
        segs = segs[1:]
    who = segs[0].lower().split()
    vehicle = "fire engine" if who[:2] == ["fire", "engine"] else who[0]
    tier = " ".join(who[2 if vehicle == "fire engine" else 1:])
    q = re.search(r"(?:(\d+) m queue|no queue) on your (\S+) approach", segs[1])
    mv = re.search(r"(going|turning) (\w+)", segs[2])
    eta = re.search(r"(\d+) (s|min)", segs[3])
    return {"vehicle": vehicle, "tier": tier, "jam_m": int(q[1] or 0) if q else 0, "approach": q[2] if q else "",
            "exit_move": mv[2].lower() if mv else "straight", "eta_s": int(eta[1]) * (60 if eta[2] == "min" else 1) if eta else 0, "stage": stage}


def _template_en(p: dict) -> str:
    n, u = (round(p["eta_s"]), "second") if p["eta_s"] < 60 else (max(round(p["eta_s"] / 60), 1), "minute")
    eta = f"{n} {u}{'' if n == 1 else 's'}"
    who = p["vehicle"].capitalize()
    move = "going straight" if p["exit_move"] == "straight" else f"turning {p['exit_move']}"
    if p["stage"] == "STOP":
        return f"Stop cross traffic now. {who} is {eta} out, {move}."
    queue = f"{round(p['jam_m'])} metre queue"
    if p["stage"] == "UPDATE":
        return f"Update. Queue on your {p['approach']} side has grown to {round(p['jam_m'])} metres. {who} still about {eta} away. Keep clearing."
    return (f"{who} coming{', ' + p['tier'] + ' case' if p['tier'] else ''}. "
            + (f"There's a {queue} on your {p['approach']} side. " if p["jam_m"] else f"No queue on your {p['approach']} side. ")
            + f"It's {move}. Reaches you in about {eta}. Start clearing now.")


def _template(p: dict, lang: str) -> str:
    if lang == "en":
        return _template_en(p)
    t = T[lang]
    n, u = (f"{round(p['eta_s'])} second" if p["eta_s"] < 60 else f"{round(p['eta_s'] / 60)} minute").split()
    side = t["side"].format(a=p["approach"], n=round(p["jam_m"])) if p["jam_m"] else t["noq"].format(a=p["approach"])
    move = t["straight"] if p["exit_move"] == "straight" else t["turn"].format(m=p["exit_move"])
    eta = t["eta"].format(n=n, u=u)
    if p["stage"] == "STOP":  # the cop only needs: stop cross traffic, who, when, which way
        return " · ".join([t["stop"], p["vehicle"], eta, move])
    who = " ".join(x for x in (p["vehicle"], p["tier"]) if x).capitalize()
    return " · ".join(([t["update"]] if p["stage"] == "UPDATE" else []) + [who, side, move, eta])


def localize_alert(text_en: str, lang: str, parts: dict | None = None) -> str:
    """Spoken-register alert line (conversational Indian English for `en`; Bengaluru Kannada / Hyderabad Telugu with English loanwords) via Gemini; on any
    failure a deterministic template of the same register. Never raises. `parts`: vehicle, tier, jam_m, approach,
    exit_move, eta_s, stage; parsed from text_en when omitted."""
    if lang not in SHOTS:
        return text_en
    key = (text_en, lang)
    if key not in _loc_cache:
        try:
            client = genai.Client(vertexai=True, project=PROJECT, location=os.environ.get("GEMINI_LOCATION", "global"),
                                  http_options=types.HttpOptions(timeout=LOCALIZE_TIMEOUT_MS))  # keep a reference: a temporary Client closes its session on GC
            shots = "".join(f"EN: {e}\n{lang.upper()}: {k}\n\n" for e, k in SHOTS[lang])
            resp = client.models.generate_content(
                model=os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview"), contents=f"Target language: {NAMES[lang]}\n\n{shots}EN: {text_en}\n{lang.upper()}:",
                config=types.GenerateContentConfig(system_instruction=SYSTEM_EN if lang == "en" else SYSTEM, temperature=0.2,
                                                   thinking_config=types.ThinkingConfig(thinking_budget=0)))  # no thinking: 1 s vs 5-9 s on the preview model
            out = " ".join((resp.text or "").split()).strip("\"' ")
            nums = re.findall(r"\d+", out)
            if lang in SCRIPT and not re.search(f"[{SCRIPT[lang]}]", out):
                raise ValueError("wrong script")
            if not out or not nums or set(nums) - set(re.findall(r"\d+", text_en)):  # digits required, none invented or altered (dropping the queue on STOP is fine)
                raise ValueError("numbers changed")
        except Exception as e:  # any Gemini/network/parse failure -> template
            _log(event="localize_fallback", lang=lang, error=type(e).__name__, detail=str(e)[:200])
            try:
                out = _template(parts or parse_alert(text_en), lang)
            except Exception:  # unparseable line: plain Cloud Translation, else English
                try:
                    out = translate(text_en, lang)
                except Exception:
                    out = text_en
        _loc_cache[key] = out
    return _loc_cache[key]


def speak(text: str, lang: str, path: str, parts: dict | None = None) -> tuple:
    """Returns (audio_url, text_local); (None, None) when synthesis fails.
    `path` is the object name, e.g. alerts/{run_id}/{junction}/{stage}-{n}.mp3."""
    lang = _alert_lang(lang)
    key = hashlib.sha256(f"{lang}\0{text}".encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    stage = "localize"
    try:
        local = localize_alert(text, lang, parts)
        stage = "synthesize"
        code, name = VOICES.get(lang, VOICES["en"])
        audio = texttospeech.TextToSpeechClient().synthesize_speech(
            input=texttospeech.SynthesisInput(text=local),
            voice=texttospeech.VoiceSelectionParams(language_code=code, name=name),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3, speaking_rate=1.05 if lang == "en" else 1.0),
            timeout=TIMEOUT_S).audio_content
        stage = "upload"
        storage.Client(project=PROJECT).bucket(BUCKET).blob(path).upload_from_string(
            audio, content_type="audio/mpeg", timeout=TIMEOUT_S)
    except GoogleAPIError as e:
        _log(event="tts_error", stage=stage, status=getattr(e, "code", type(e).__name__), detail=str(e)[:200])
        return None, None
    _cache[key] = (f"https://storage.googleapis.com/{BUCKET}/{path}", local)
    return _cache[key]


def store_photo(data: bytes, mime: str, path: str):
    """Upload a monitor photo to the media bucket (public read like alerts) -> URL, or None when the upload fails."""
    try:
        storage.Client(project=PROJECT).bucket(BUCKET).blob(path).upload_from_string(data, content_type=mime, timeout=TIMEOUT_S)
    except GoogleAPIError as e:
        _log(event="photo_upload_error", path=path, status=getattr(e, "code", type(e).__name__), detail=str(e)[:200])
        return None
    return f"https://storage.googleapis.com/{BUCKET}/{path}"


if __name__ == "__main__":  # offline self-check: stub every client
    from types import SimpleNamespace as NS
    calls = []
    translate_v3.TranslationServiceClient = lambda: NS(translate_text=lambda **k: NS(translations=[NS(translated_text="K:" + k["contents"][0])]))
    texttospeech.TextToSpeechClient = lambda: NS(synthesize_speech=lambda **k: calls.append(k["voice"].name) or NS(audio_content=b"mp3"))
    storage.Client = lambda project: NS(bucket=lambda b: NS(blob=lambda p: NS(upload_from_string=lambda *a, **k: calls.append(p))))
    assert store_photo(b"x", "image/png", "photos/r/0.jpg") == f"https://storage.googleapis.com/{BUCKET}/photos/r/0.jpg"
    calls.clear()
    gem = []  # Gemini stub: a canned line, call count, or an exception
    def fake_client(**k):
        def gen(**kw):
            gem.append(kw["contents"])
            if isinstance(gem[0], Exception):
                raise gem[0]
            return NS(text=gem[0])
        return NS(models=NS(generate_content=gen))
    genai.Client = fake_client
    EN = "STOP CROSS TRAFFIC · AMBULANCE CRITICAL · 520 m queue on your south-east approach · going STRAIGHT · arrives in 30 s"
    assert parse_alert(EN) == {"vehicle": "ambulance", "tier": "critical", "jam_m": 520, "approach": "south-east", "exit_move": "straight", "eta_s": 30, "stage": "STOP"}
    assert parse_alert("FIRE ENGINE · no queue on your north approach · turning LEFT · arrives in 2 min")["eta_s"] == 120
    assert _template(parse_alert(EN), "kn") == "Cross traffic ನಿಲ್ಲಿಸಿ · ambulance · 30 second ಅಲ್ಲಿ ಬರ್ತಿದೆ · straight ಹೋಗ್ತಿದೆ"
    up = "UPDATE · FIRE ENGINE URGENT · 640 m queue on your west approach · turning RIGHT · arrives in 3 min"
    assert _template(parse_alert(up), "te") == "Update · Fire engine urgent · మీ west side నుంచి 640 metre queue ఉంది · right తిరుగుతోంది · 3 minute లో వస్తోంది"
    gem[:] = [Exception("boom")]
    assert localize_alert(EN, "kn").startswith("Cross traffic")  # Gemini failure -> template
    gem[:] = ["Cross traffic ನಿಲ್ಲಿಸಿ · ambulance 31 second ಅಲ್ಲಿ ಬರ್ತಿದೆ 520"]
    assert "30 second" in localize_alert(EN + " ", "kn")  # altered number -> template
    gem[:] = ['"Cross traffic ನಿಲ್ಲಿಸಿ · 520 · 30"\n']
    assert localize_alert(EN + "  ", "kn") == "Cross traffic ನಿಲ್ಲಿಸಿ · 520 · 30"  # quotes stripped, numbers kept
    n = len(gem)
    localize_alert(EN + "  ", "kn")
    assert len(gem) == n and localize_alert("hi", "xx") == "hi"  # cache hit; unknown lang untouched
    # English: conversational template and Gemini path
    assert _template(parse_alert(EN), "en") == "Stop cross traffic now. Ambulance is 30 seconds out, going straight."
    pre = "AMBULANCE CRITICAL · 520 m queue on your south-east approach · going STRAIGHT · arrives in 2 min"
    assert _template(parse_alert(pre), "en") == ("Ambulance coming, critical case. There's a 520 metre queue on your south-east side. "
                                                  "It's going straight. Reaches you in about 2 minutes. Start clearing now.")
    assert _template(parse_alert(up), "en") == ("Update. Queue on your west side has grown to 640 metres. Fire engine still about 3 minutes away. Keep clearing.")
    gem[:] = [Exception("boom")]
    assert localize_alert(pre, "en").startswith("Ambulance coming, critical case.")  # Gemini failure -> English template
    gem[:] = ["Ambulance coming.\nThere's a 520 metre queue. Reaches you in about 2 minutes."]
    assert localize_alert(pre + " ", "en") == "Ambulance coming. There's a 520 metre queue. Reaches you in about 2 minutes."
    gem[:] = ["Queue is 900 metres."]  # invented number -> template
    assert "520 metre" in localize_alert(pre + "  ", "en")
    # speak: ALERT_LANG default en overrides the corridor language, `corridor` keeps it
    pre2 = pre + "   "  # fresh cache key
    gem[:] = ["Ambulance coming. 520 metres. 2 minutes."]
    calls.clear()
    assert speak(pre2, "kn", "a/1.mp3") == (f"https://storage.googleapis.com/{BUCKET}/a/1.mp3", "Ambulance coming. 520 metres. 2 minutes.")
    assert calls == ["en-IN-Neural2-A", "a/1.mp3"]
    assert speak(pre2, "kn", "a/2.mp3")[0].endswith("a/1.mp3") and len(calls) == 2  # cache hit, no new calls
    os.environ["ALERT_LANG"] = "corridor"
    gem[:] = ["Ambulance critical · ಇದೆ 520 · 2"]
    assert speak(pre2, "kn", "a/3.mp3")[1] == "Ambulance critical · ಇದೆ 520 · 2" and calls[-2] == "kn-IN-Wavenet-A"
    assert speak("yo", "xx", "a/4.mp3")[1] == "yo" and calls[-2] == "en-IN-Neural2-A"  # unknown lang -> en-IN voice, text untouched
    os.environ["ALERT_LANG"] = "te"
    speak(pre2, "kn", "a/5.mp3")
    assert calls[-2] == "te-IN-Standard-A"
    print("tts ok")
