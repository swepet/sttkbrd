import sys

if sys.platform == "win32":
    from .typer_win import Typer

    def create():
        return Typer()
else:
    from .typer_x11 import Typer

    def create():
        from .clipboard import Clipboard
        return Typer(Clipboard())
