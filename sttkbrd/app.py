import sys

if sys.platform == "win32":
    from .app_win import main
else:
    from .app_gtk import main
