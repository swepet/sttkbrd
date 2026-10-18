import copy
import json
import os

from . import commands, paths, secret
from .log import log

DIR = paths.config_dir()
PATH = os.path.join(DIR, "config.json")

DEFAULTS = {
    "provider": "OpenRouter",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key": "",
    "model": "openai/whisper-large-v3",
    "hotkey": "ctrl+shift+space",
    "language": "",
    "microphone": "",
    "trailing_space": True,
    "auto": False,
    "commands_enabled": True,
    "commands": commands.DEFAULTS,
}


# The key as it is on disk ("api_key" and/or "api_key_encrypted", exactly as written there) and as plain text
# after loading. An existing key is never rewritten: only a key that differs from the loaded one is encrypted.
_disk_key = {}
_loaded_key = ""


def load():
    """The config, with the API key as plain text in cfg["api_key"] (on disk it is "api_key_encrypted").

    An older config with a plain "api_key" is read as it is and left alone."""
    global _disk_key, _loaded_key
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    cfg["commands"] = commands.upgrade(cfg["commands"])
    encrypted = cfg.pop("api_key_encrypted", "")
    _disk_key = {k: v for k, v in (("api_key", cfg["api_key"]), ("api_key_encrypted", encrypted)) if v}
    if encrypted:
        try:
            cfg["api_key"] = secret.decrypt(encrypted)
        except ValueError as ex:
            log.warning("Could not decrypt the API key in the config (%s) - enter it again in Settings", ex)
            cfg["api_key"] = ""
    if not cfg["api_key"]:
        cfg["api_key"] = os.environ.get("OPENROUTER_API_KEY", "")
    _loaded_key = cfg["api_key"]
    return cfg


def save(cfg):
    global _disk_key, _loaded_key
    cfg = dict(cfg)
    key = cfg.pop("api_key", "")
    if key == _loaded_key:
        cfg.update(_disk_key or {"api_key_encrypted": ""})  # not changed: whatever is on disk stays as it is
    else:
        cfg["api_key_encrypted"] = secret.encrypt(key) if key else ""  # a key was entered: encrypt it
        _disk_key, _loaded_key = {"api_key_encrypted": cfg["api_key_encrypted"]} if key else {}, key
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    tmp = PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PATH)
