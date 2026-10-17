import copy
import json
import os

from . import commands

DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "sttkbrd")
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


def load():
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    cfg["commands"] = commands.upgrade(cfg["commands"])
    if not cfg["api_key"]:
        cfg["api_key"] = os.environ.get("OPENROUTER_API_KEY", "")
    return cfg


def save(cfg):
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    tmp = PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PATH)
