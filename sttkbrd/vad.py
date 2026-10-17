import collections
import time as _time

import numpy as np

from .log import log
from .recorder import RATE, open_input, pcm_to_wav

BLOCK = RATE * 30 // 1000          # 30 ms per block
START_BLOCKS = 3                   # loud blocks in a row before speech counts as started (~90 ms)
PREROLL_BLOCKS = 10                # audio kept from before the trigger so word starts are not clipped (~300 ms)
END_SILENCE_BLOCKS = 27            # silence that ends an utterance (~0.8 s)
MAX_BLOCKS = 1000                  # hard cap per utterance (~30 s)
MIN_THRESHOLD = 600                # absolute RMS floor (int16 units) so a very quiet room does not trigger on a click
NOISE_FACTOR = 3.0                 # speech must be this many times louder than the tracked noise floor
WARMUP_BLOCKS = 16                # calibration after start (~0.5 s): never triggers, measures the room noise
WARMUP_PERCENTILE = 25            # low percentile: ignores the toggle beep and key clicks that fall inside the warm-up
MAX_FLOOR = 800                   # a user already talking during warm-up must not make the threshold unreachably high
HYSTERESIS = 0.6                   # while speaking, blocks above threshold * this still count as speech


class AutoListener:
    """Voice-activated recording. Behaves like holding the hotkey: speech start -> record -> silence -> submit.

    Energy-based detection with an adaptive noise floor. The callbacks run on the audio thread, so they
    must return quickly: on_speech_start() and on_utterance(wav, seconds).
    is_blocked() returning True (e.g. the hotkey is held) suspends detection and drops any partial utterance.
    """

    def __init__(self, on_speech_start, on_utterance, is_blocked):
        self._on_start, self._on_utterance, self._blocked = on_speech_start, on_utterance, is_blocked
        self._stream = None
        self._last_audio = 0.0
        self._warm = None
        self._reset()
        self._floor = float(MIN_THRESHOLD) / NOISE_FACTOR

    def _reset(self):
        self._preroll = collections.deque(maxlen=PREROLL_BLOCKS)
        self._frames = []
        self._speaking = False
        self._loud = 0
        self._silence = 0

    @property
    def running(self):
        return self._stream is not None

    @property
    def speaking(self):
        """True while an utterance is being recorded. False if the stream has gone silent (died)."""
        return self._stream is not None and self._speaking and not self.stalled(1.0)

    def stalled(self, seconds=2.0):
        """The stream is supposed to run but has delivered no audio for a while (e.g. the sound server restarted)."""
        return self._stream is not None and _time.monotonic() - self._last_audio > seconds

    def start(self, device_name=""):
        self.stop()
        self._reset()
        self._warm = []  # calibration blocks (rms); detection starts once WARMUP_BLOCKS have been seen
        self._last_audio = _time.monotonic()
        self._stream = open_input(device_name, self._on_audio, BLOCK)
        self._stream.start()
        log.info("Auto mode listening (device=%r)", device_name or "default")

    def stop(self):
        stream, self._stream = self._stream, None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                log.exception("Could not stop the auto-mode stream")
        self._reset()

    def threshold(self):
        return max(MIN_THRESHOLD, self._floor * NOISE_FACTOR)

    def _on_audio(self, indata, frames, time, status):
        if self._stream is None:  # stopped while this block was in flight: must not start an utterance
            return
        self._last_audio = _time.monotonic()
        if self._blocked():
            if self._speaking or self._loud:
                self._reset()
            return
        block = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
        if self._warm is not None:
            # Calibration: the first moments after starting are exactly when the toggle beep plays and the hotkey
            # was pressed, and the noise floor is still unknown. Keep audio for the pre-roll, never trigger.
            self._preroll.append(block.tobytes())
            self._warm.append(rms)
            if len(self._warm) >= WARMUP_BLOCKS:
                self._floor = min(float(np.percentile(self._warm, WARMUP_PERCENTILE)), MAX_FLOOR)
                self._warm = None
                log.info("Calibrated noise floor=%.0f threshold=%.0f", self._floor, self.threshold())
            return
        thr = self.threshold()

        if not self._speaking:
            if rms < thr:  # track the noise floor only from non-speech blocks
                self._floor = 0.97 * self._floor + 0.03 * rms
            self._preroll.append(block.tobytes())
            self._loud = self._loud + 1 if rms > thr else 0
            if self._loud >= START_BLOCKS:
                self._speaking = True
                self._frames = list(self._preroll)
                self._silence = 0
                log.info("Speech detected (rms=%.0f threshold=%.0f)", rms, thr)
                self._on_start()
            return

        self._frames.append(block.tobytes())
        self._silence = 0 if rms > thr * HYSTERESIS else self._silence + 1
        if self._silence >= END_SILENCE_BLOCKS or len(self._frames) >= MAX_BLOCKS:
            # drop the trailing silence but keep a little so the last word is not cut
            keep = max(0, len(self._frames) - self._silence + 5)
            pcm = b"".join(self._frames[:keep])
            seconds = (len(self._frames) - self._silence) * BLOCK / RATE
            self._reset()
            self._on_utterance(pcm_to_wav(pcm), seconds)
