"""Alert audio: translate to the junction language, synthesize MP3, store in the media bucket. Failure -> None, never raises."""
import hashlib
import json
import os

from google.api_core.exceptions import GoogleAPIError
from google.cloud import storage, texttospeech, translate_v3

PROJECT = os.environ.get("GCP_PROJECT", "green-corridor-2026")
BUCKET = os.environ.get("MEDIA_BUCKET", "green-corridor-2026-media")
# Wavenet/Neural2 where the language has one; te-IN has only Standard. Unknown language falls back to en-IN.
VOICES = {"kn": ("kn-IN", "kn-IN-Wavenet-A"), "te": ("te-IN", "te-IN-Standard-A"), "en": ("en-IN", "en-IN-Neural2-A")}
TIMEOUT_S = 8
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


def speak(text: str, lang: str, path: str) -> tuple:
    """Returns (audio_url, text_local); (None, None) when translation or synthesis fails.
    `path` is the object name, e.g. alerts/{run_id}/{junction}/{stage}-{n}.mp3."""
    key = hashlib.sha256(f"{lang}\0{text}".encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    stage = "translate"
    try:
        local = translate(text, lang)
        stage = "synthesize"
        code, name = VOICES.get(lang, VOICES["en"])
        audio = texttospeech.TextToSpeechClient().synthesize_speech(
            input=texttospeech.SynthesisInput(text=local),
            voice=texttospeech.VoiceSelectionParams(language_code=code, name=name),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
            timeout=TIMEOUT_S).audio_content
        stage = "upload"
        storage.Client(project=PROJECT).bucket(BUCKET).blob(path).upload_from_string(
            audio, content_type="audio/mpeg", timeout=TIMEOUT_S)
    except GoogleAPIError as e:
        _log(event="tts_error", stage=stage, status=getattr(e, "code", type(e).__name__), detail=str(e)[:200])
        return None, None
    _cache[key] = (f"https://storage.googleapis.com/{BUCKET}/{path}", local)
    return _cache[key]


if __name__ == "__main__":  # offline self-check: stub the three clients
    from types import SimpleNamespace as NS
    calls = []
    translate_v3.TranslationServiceClient = lambda: NS(translate_text=lambda **k: NS(translations=[NS(translated_text="K:" + k["contents"][0])]))
    texttospeech.TextToSpeechClient = lambda: NS(synthesize_speech=lambda **k: calls.append(k["voice"].name) or NS(audio_content=b"mp3"))
    storage.Client = lambda project: NS(bucket=lambda b: NS(blob=lambda p: NS(upload_from_string=lambda *a, **k: calls.append(p))))
    assert speak("hi", "kn", "a/1.mp3") == (f"https://storage.googleapis.com/{BUCKET}/a/1.mp3", "K:hi")
    assert speak("hi", "kn", "a/2.mp3")[0].endswith("a/1.mp3") and len(calls) == 2  # cache hit, no new calls
    assert speak("yo", "xx", "a/3.mp3")[1] == "K:yo" and "en-IN-Neural2-A" in calls  # unknown lang -> en-IN voice
    assert speak("yo", "en", "a/4.mp3")[1] == "yo"
    print("tts ok")
