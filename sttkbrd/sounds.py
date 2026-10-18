import io
import os
import shutil
import subprocess
import threading
import wave

import numpy as np
import sounddevice as sd

from . import paths
from .log import log

RATE = 44100
VOLUME = 0.25


def _beep(freq, ms):
    n = RATE * ms // 1000
    t = np.arange(n) / RATE
    fade = np.minimum(1.0, np.minimum(np.arange(n), np.arange(n)[::-1]) / (RATE * 0.008))  # 8 ms ramps avoid clicks
    return np.sin(2 * np.pi * freq * t) * fade


def _silence(ms):
    return np.zeros(RATE * ms // 1000)


# listening on: two short high beeps. Listening off: one slightly longer, lower beep.
ON = (np.concatenate([_beep(1000, 70), _silence(70), _beep(1000, 70)]) * VOLUME).astype(np.float32)
OFF = (_beep(600, 220) * VOLUME).astype(np.float32)
# something went wrong: five low beeps in a row
ALARM = (np.concatenate([np.concatenate([_beep(440, 120), _silence(100)]) for _ in range(5)]) * VOLUME * 1.6
         ).astype(np.float32)


def _wav_bytes(samples):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((samples * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


_PAPLAY = shutil.which("paplay")
_CACHE = os.path.join(paths.cache_dir(), "sounds")


def _wav_file(name, samples):
    """WAV file for paplay, written once and reused."""
    path = os.path.join(_CACHE, name + ".wav")
    if not os.path.exists(path):
        os.makedirs(_CACHE, exist_ok=True)
        with open(path, "wb") as f:
            f.write(_wav_bytes(samples))
    return path


def _play(samples, name):
    """Fire and forget. paplay (PulseAudio) is used when present: sd.play gave ALSA underruns here."""
    try:
        if _PAPLAY:
            path = _wav_file(name, samples)
            threading.Thread(target=lambda: subprocess.run([_PAPLAY, path], stdout=subprocess.DEVNULL,
                                                           stderr=subprocess.DEVNULL), daemon=True).start()
        else:
            sd.play(samples, RATE)
    except Exception:  # noqa: BLE001 - a missing speaker must never break dictation
        log.exception("Could not play the %s beep", name)


def listening_on():
    _play(ON, "listening-on")


def alarm():
    _play(ALARM, "alarm")


def listening_off():
    _play(OFF, "listening-off")
