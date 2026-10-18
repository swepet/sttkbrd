# sttkbrd

- The version lives in `sttkbrd/__init__.py` (`__version__`) and nowhere else. Raise it with every change that is
  committed (patch for fixes and small things, minor for new features), so the version in the Settings title and in
  the exe name always tells which build it is.
- `build-windows.bat` builds `dist\sttkbrd-v<version>.exe`; the version is also in its file properties.
- Do not run tests against the real config (`%APPDATA%\sttkbrd` / `~/.config/sttkbrd`): point `APPDATA`,
  `LOCALAPPDATA` or `XDG_CONFIG_HOME` at a temporary directory.
