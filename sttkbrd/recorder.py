import collections
import io
import sys
import threading
import wave

import numpy as np
import sounddevice as sd

from .log import log

RATE = 16000


def _resolve(name):
    """Windows lists every microphone once per audio API (MME, DirectSound, WASAPI ...), so a bare name is
    ambiguous: pick the device of the default API."""
    if sys.platform != "win32" or not name:
        return name
    api = sd.default.hostapi
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] == api and d["max_input_channels"] > 0 and d["name"] == name:
            return i
    return name


def open_input(device_name, callback, blocksize=0):
    """Open a 16 kHz mono input stream on the named microphone, falling back to the system default
    if that device is gone or the name no longer matches (e.g. a USB mic that was unplugged)."""
    for device in ([device_name, None] if device_name else [None]):
        try:
            return sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=blocksize,
                                  device=_resolve(device), callback=callback)
        except (ValueError, sd.PortAudioError) as ex:
            if device is None:
                raise
            log.warning("Microphone %r unavailable (%s) - using the system default", device, ex)


def list_microphones():
    names = []
    for d in sd.query_devices():
        if sys.platform == "win32" and d["hostapi"] != sd.default.hostapi:
            continue
        if d["max_input_channels"] > 0 and d["name"] not in names:
            names.append(d["name"])
    return names


def pcm_to_wav(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._frames = []
        self._stream = None

    @property
    def recording(self):
        return self._stream is not None

    def start(self, device_name=""):
        with self._lock:
            if self._stream:
                return
            self._frames = []
            self._stream = open_input(device_name, self._on_audio)
            self._stream.start()

    def _on_audio(self, indata, frames, time, status):
        self._frames.append(indata.copy().tobytes())

    def stop(self):
        """Stop and return (wav bytes, seconds)."""
        with self._lock:
            stream, self._stream = self._stream, None
        if not stream:
            return b"", 0.0
        stream.stop()
        stream.close()
        pcm = b"".join(self._frames)
        return pcm_to_wav(pcm), len(pcm) / 2 / RATE


class MicMonitor:
    """Live level monitor: keeps a rolling list of recent peak levels (0..1) for a waveform display."""

    def __init__(self, bars=96):
        self._levels = collections.deque([0.0] * bars, maxlen=bars)
        self._stream = None
        self.error = ""

    def start(self, device_name=""):
        self.stop()
        self.error = ""
        try:
            self._stream = open_input(device_name, self._on_audio, RATE // 30)
            self._stream.start()
        except Exception as ex:  # noqa: BLE001 - shown in the UI instead of raised
            self._stream = None
            self.error = str(ex)

    def stop(self):
        stream, self._stream = self._stream, None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    def _on_audio(self, indata, frames, time, status):
        peak = float(np.abs(indata).max()) / 32768.0
        self._levels.append(min(1.0, peak ** 0.5))  # sqrt makes quiet speech visible

    def levels(self):
        return list(self._levels)
