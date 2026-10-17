import logging
import logging.handlers
import os
import sys
import threading

DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "sttkbrd")
PATH = os.path.join(DIR, "sttkbrd.log")

log = logging.getLogger("sttkbrd")


def setup():
    os.makedirs(DIR, exist_ok=True)
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(PATH, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)

    def hook(exc_type, exc, tb):
        log.error("Unhandled error", exc_info=(exc_type, exc, tb))

    def thread_hook(args):
        log.error("Unhandled error in thread %s", args.thread.name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = hook
    threading.excepthook = thread_hook
