import sys

from . import autostart
from .log import setup


def _menu_command(flag):
    """--install-menu / --remove-menu: manage the application menu entry, without starting the app."""
    setup()
    try:
        if flag == "--install-menu":
            print("Menu entry written: " + autostart.install_menu_entry())
        else:
            autostart.remove_menu_entry()
            print("Menu entry removed.")
    except autostart.AutostartError as ex:
        print("Error: %s" % ex, file=sys.stderr)
        sys.exit(1)


if len(sys.argv) > 1 and sys.argv[1] in ("--install-menu", "--remove-menu"):
    _menu_command(sys.argv[1])
else:
    from .app import main

    main()
