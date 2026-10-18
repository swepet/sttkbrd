import sys

if sys.platform == "win32":
    from .autostart_win import (AutostartError, disable, enable, install_menu_entry, is_enabled,
                                menu_entry_enabled, refresh_if_stale, refresh_menu_if_stale, remove_menu_entry)
else:
    from .autostart_linux import (AutostartError, disable, enable, install_menu_entry, is_enabled,
                                  menu_entry_enabled, refresh_if_stale, refresh_menu_if_stale, remove_menu_entry)
