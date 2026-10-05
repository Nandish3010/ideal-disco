from types import SimpleNamespace
from typing import Any

import pytest

import brief
import tts

PREPARE = "AMBULANCE CRITICAL · 520 m queue on your south-east approach · going STRAIGHT · arrives in 2 min"
STOP = "STOP CROSS TRAFFIC · AMBULANCE CRITICAL · 520 m queue on your south-east approach · going STRAIGHT · arrives in 30 s"
UPDATE = "UPDATE · FIRE ENGINE URGENT · 640 m queue on your west approach · turning RIGHT · arrives in 3 min"


def test_parse_alert() -> None:
    assert tts.parse_alert(STOP) == {
        "vehicle": "ambulance", "tier": "critical", "jam_m": 520, "approach": "south-east",
        "exit_move": "straight", "eta_s": 30, "stage": "STOP",
    }  # fmt: skip
    p = tts.parse_alert("FIRE ENGINE · no queue on your north approach · turning LEFT · arrives in 2 min")
    assert (p["vehicle"], p["jam_m"], p["exit_move"], p["eta_s"], p["stage"]) == (
        "fire engine",
        0,
        "left",
        120,
        "PREPARE",
    )


def test_english_template_keeps_the_numbers() -> None:
    assert (
        tts._template(tts.parse_alert(STOP), "en")
        == "Stop cross traffic now. Ambulance is 30 seconds out, going straight."
    )
    assert tts._template(tts.parse_alert(PREPARE), "en") == (
        "Ambulance coming, critical case. There's a 520 metre queue on your south-east side. "
        "It's going straight. Reaches you in about 2 minutes. Start clearing now."
    )
    assert tts._template(tts.parse_alert(UPDATE), "en") == (
        "Update. Queue on your west side has grown to 640 metres. Fire engine still about 3 minutes away. Keep clearing."
    )


def test_localised_template_keeps_loanwords_and_numbers() -> None:
    kn = tts._template(tts.parse_alert(PREPARE), "kn")
    assert "520" in kn and "2 minute" in kn and "straight" in kn
    assert "640" in tts._template(tts.parse_alert(UPDATE), "te")


def test_offline_returns_english_untouched() -> None:
    assert tts.localize_alert(STOP, "kn") == STOP
    assert tts.speak(STOP, "kn", "a/1.mp3") == (None, STOP)


def test_gemini_failure_falls_back_to_the_english_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFLINE_AI", "0")

    def boom(**_: object) -> None:
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(tts.genai, "Client", boom)
    text = PREPARE + " "  # unique cache key
    out = tts.localize_alert(text, "en")
    assert out.startswith("Ambulance coming, critical case.") and "520 metre" in out and "2 minutes" in out


def test_brief_stub_shape_offline() -> None:
    out, model = brief.generate({}, [])
    assert model == "offline"
    brief.Brief.model_validate(out)  # the stub satisfies the real schema
    assert set(out) == {"atmist", "checklist", "summary"}
    assert set(out["atmist"]) == {"age", "time", "mechanism", "injuries", "signs", "treatment"}
    assert 3 <= len(out["checklist"]) <= 8


@pytest.mark.parametrize("n", [2, 9])
def test_brief_checklist_length_enforced(n: int) -> None:
    bad = {"atmist": {k: "x" for k in brief.Atmist.model_fields}, "checklist": ["a"] * n, "summary": "s"}
    with pytest.raises(ValueError):
        brief.Brief.model_validate(bad)


# ---- localize and speak with every Google client stubbed -----------------------------------------------------------------


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Online mode with a canned Gemini: gem[0] is the reply (or an exception to raise); the list also records prompts."""
    monkeypatch.setenv("OFFLINE_AI", "0")
    monkeypatch.setattr(tts, "_loc_cache", {})
    monkeypatch.setattr(tts, "_cache", {})
    gem: list[Any] = []

    def generate_content(**kw: Any) -> Any:
        gem.append(kw["contents"])
        if isinstance(gem[0], Exception):
            raise gem[0]
        return SimpleNamespace(text=gem[0])

    monkeypatch.setattr(
        tts.genai,
        "Client",
        lambda **_: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
    )
    return gem


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """TTS and Storage stubs; the list records the voice name and each uploaded object path."""
    calls: list[str] = []

    def synth(**k: Any) -> Any:
        calls.append(k["voice"].name)
        return SimpleNamespace(audio_content=b"mp3")

    def upload(path: str) -> Any:
        return SimpleNamespace(upload_from_string=lambda *a, **k: calls.append(path))

    monkeypatch.setattr(
        tts.texttospeech, "TextToSpeechClient", lambda: SimpleNamespace(synthesize_speech=synth)
    )
    monkeypatch.setattr(
        tts.storage, "Client", lambda project: SimpleNamespace(bucket=lambda b: SimpleNamespace(blob=upload))
    )
    monkeypatch.setattr(
        tts.translate_v3,
        "TranslationServiceClient",
        lambda: SimpleNamespace(
            translate_text=lambda **k: SimpleNamespace(
                translations=[SimpleNamespace(translated_text="K:" + k["contents"][0])]
            )
        ),
    )
    return calls


def test_gemini_reply_is_cleaned_and_cached(gemini: list[Any]) -> None:
    gemini[:] = ["Ambulance coming.\nThere's a 520 metre queue. Reaches you in about 2 minutes."]
    line = PREPARE + "  "
    assert (
        tts.localize_alert(line, "en")
        == "Ambulance coming. There's a 520 metre queue. Reaches you in about 2 minutes."
    )
    n = len(gemini)
    tts.localize_alert(line, "en")
    assert len(gemini) == n  # cache hit, no second call
    assert tts.localize_alert("hi", "xx") == "hi"  # unknown language untouched


@pytest.mark.parametrize(
    ("lang", "reply"),
    [
        ("en", "Queue is 900 metres."),  # invented number
        ("kn", "Cross traffic ನಿಲ್ಲಿಸಿ · ambulance 31 second ಅಲ್ಲಿ ಬರ್ತಿದೆ 520"),  # altered number
        ("kn", "Cross traffic · ambulance 30 second 520"),  # wrong script
        ("kn", RuntimeError("boom")),
    ],
)
def test_bad_gemini_output_falls_back_to_the_template(gemini: list[Any], lang: str, reply: Any) -> None:
    gemini[:] = [reply]
    out = tts.localize_alert(STOP + " ", lang)
    assert out == tts._template(tts.parse_alert(STOP), lang) and "30" in out


def test_good_kannada_reply_is_kept(gemini: list[Any]) -> None:
    gemini[:] = ['"Cross traffic ನಿಲ್ಲಿಸಿ · 520 · 30"\n']
    assert tts.localize_alert(STOP + "   ", "kn") == "Cross traffic ನಿಲ್ಲಿಸಿ · 520 · 30"


def test_speak_voice_follows_alert_lang(
    gemini: list[Any], google: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    gemini[:] = ["Ambulance coming. 520 metres. 2 minutes."]
    text = PREPARE + "    "
    url, local = tts.speak(
        text, "kn", "a/1.mp3"
    )  # ALERT_LANG defaults to en and wins over the corridor language
    assert url == f"https://storage.googleapis.com/{tts.BUCKET}/a/1.mp3" and local.startswith(
        "Ambulance coming"
    )
    assert google == ["en-IN-Neural2-A", "a/1.mp3"]
    assert tts.speak(text, "kn", "a/2.mp3")[0].endswith("a/1.mp3") and len(google) == 2  # cached

    monkeypatch.setenv("ALERT_LANG", "corridor")
    gemini[:] = ["Ambulance critical · ಇದೆ 520 · 2"]
    assert (
        tts.speak(text, "kn", "a/3.mp3")[1] == "Ambulance critical · ಇದೆ 520 · 2"
        and google[-2] == "kn-IN-Wavenet-A"
    )
    assert (
        tts.speak("yo", "xx", "a/4.mp3")[1] == "yo" and google[-2] == "en-IN-Neural2-A"
    )  # unknown language: en voice
    monkeypatch.setenv("ALERT_LANG", "te")
    tts.speak(text, "kn", "a/5.mp3")
    assert google[-2] == "te-IN-Standard-A"


def test_translate_and_photo_upload(google: list[str]) -> None:
    assert tts.translate("hello", "en") == "hello"
    assert tts.translate("hello", "kn") == "K:hello"
    assert (
        tts.store_photo(b"x", "image/png", "photos/r/0.jpg")
        == f"https://storage.googleapis.com/{tts.BUCKET}/photos/r/0.jpg"
    )
    assert google == ["photos/r/0.jpg"]
