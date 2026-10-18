import base64
import re

import requests

from .log import log

DEFAULT_MODEL = "openai/whisper-large-v3"
FALLBACK_MODELS = [DEFAULT_MODEL, "openai/whisper-large-v3-turbo", "openai/whisper-1"]


class SttError(Exception):
    pass


def _base(base_url):
    return (base_url or "").strip().rstrip("/") or "https://openrouter.ai/api/v1"


def _headers(api_key, base_url):
    h = {}
    if api_key:
        h["Authorization"] = "Bearer " + api_key
    if "openrouter.ai" in _base(base_url):
        h["HTTP-Referer"] = "https://sttkbrd.local"
        h["X-Title"] = "sttkbrd"
    return h


def _error(resp):
    try:
        msg = resp.json()["error"]["message"]
        if msg:
            return "%s (HTTP %d)" % (msg, resp.status_code)
    except (ValueError, KeyError, TypeError):
        pass
    return "HTTP %d: %s" % (resp.status_code, resp.text[:240])


def _dollars(amount):
    if amount >= 1:
        return "$%.2f" % amount
    return "$" + ("%.6f" % amount).rstrip("0").rstrip(".")


def price_note(row):
    """Price as text, e.g. '$0.0050/min'. OpenRouter prices transcription per second."""
    pricing = row.get("pricing") or {}

    def num(key):
        try:
            return max(float(pricing.get(key) or 0), 0.0)
        except (TypeError, ValueError):
            return 0.0

    prompt, completion, request = num("prompt"), num("completion"), num("request")
    if prompt > 0 and completion <= 0:
        return _dollars(prompt * 60) + "/min"
    if prompt > 0 or completion > 0:
        return "%s / %s per 1M" % (_dollars(prompt * 1e6), _dollars(completion * 1e6))
    if request > 0:
        return _dollars(request) + "/request"
    return ""


def load_models(api_key, base_url):
    """List of (id, price note) for transcription models, default model first."""
    try:
        resp = requests.get(_base(base_url) + "/models", params={"output_modalities": "transcription"},
                            headers=_headers(api_key, base_url), timeout=60)
    except requests.RequestException as ex:
        log.error("Model list failed: %s", ex)
        raise SttError("Could not load models: %s" % ex)
    if not resp.ok:
        log.error("Model list HTTP %d: %s", resp.status_code, resp.text[:300])
        raise SttError(_error(resp))
    models = {}
    for row in resp.json().get("data", []):
        mid = row.get("id", "")
        if mid and mid not in models:
            models[mid] = price_note(row)
    if not models:
        raise SttError("The provider returned no transcription models.")
    log.info("Loaded %d models", len(models))
    return sorted(models.items(), key=lambda kv: (kv[0] != DEFAULT_MODEL, kv[0].lower()))


def _language(value):
    """The provider accepts only ONE language code (e.g. 'sv'), not lists like 'sv,en'."""
    value = (value or "").strip()
    if not value:
        return ""
    first = re.split(r"[,\s;]+", value)[0].lower()
    if first != value.lower():
        log.warning("Language '%s' is a list - using only '%s'", value, first)
    return first


def transcribe(api_key, model, base_url, wav, language=""):
    if not api_key:
        raise SttError("API key missing. Open Settings from the tray menu.")
    model = model or DEFAULT_MODEL
    lang = _language(language)
    url = _base(base_url) + "/audio/transcriptions"
    audio = {"data": base64.b64encode(wav).decode("ascii"), "format": "wav"}
    timeout = (10, 30 + len(wav) // 32000)  # connect, read: half a minute plus the length of the recording
    for attempt_lang in ([lang, ""] if lang else [""]):
        body = {"model": model, "input_audio": audio}
        if attempt_lang:
            body["language"] = attempt_lang
        log.info("POST %s model=%s lang=%r wavBytes=%d", url, model, attempt_lang, len(wav))
        try:
            resp = requests.post(url, json=body, headers=_headers(api_key, base_url), timeout=timeout)
        except requests.Timeout:
            log.error("Request timed out after %d s", timeout[1])
            raise SttError("The model did not answer within %d seconds." % timeout[1])
        except requests.RequestException as ex:
            log.error("Request failed: %s", ex)
            raise SttError("Could not reach the speech-to-text model: %s" % ex)
        if resp.ok:
            try:
                answer = resp.json()
                text = answer["text"]
            except (ValueError, KeyError, TypeError):
                log.error("Unusable answer: %s", resp.text[:300])
                raise SttError("The model returned no transcription - it may not support speech-to-text.")
            text = (text or "").strip()
            log.info("Heard %d characters", len(text))
            return text
        log.error("HTTP %d: %s", resp.status_code, resp.text[:500])
        if attempt_lang and resp.status_code == 400:
            log.warning("Retrying without a language hint")
            continue
        raise SttError(_error(resp))
