<p align="center">
  <img src="art/icon-256.png" width="160" alt="sttkbrd icon">
</p>

<h1 align="center">sttkbrd</h1>

Hold a key combination, speak, release - the text is typed where the cursor is, as if typed on a keyboard.
Linux/X11. Lives as an icon by the clock (system tray). Uses OpenRouter for speech-to-text, like EgenAiAgent.

## Run
    ./sttkbrd.sh

On first start Settings opens: paste your OpenRouter key (or set `OPENROUTER_API_KEY`) and press **Load** for the model list (prices shown per minute).
Tray icon: **left button** does what the hotkey does - in auto mode a click pauses / resumes listening, otherwise hold
the button and speak (push-to-talk). **Right-click** opens the menu, which has Settings. Starting the app again also
opens Settings. Default hotkey: Ctrl+Shift+Space (change it in Settings).
Every change in Settings is saved and applied immediately - there is no Save button.
The waveform in Settings follows the selected microphone, so you can see that it works.

## Start without a terminal
Tick **Show in the application menu** in Settings (or run `./sttkbrd.sh --install-menu`, remove with `--remove-menu`).
It writes a standard freedesktop.org desktop entry to `$XDG_DATA_HOME/applications` (normally
`~/.local/share/applications`), which GNOME, KDE, Xfce, MATE, Cinnamon and the other desktops all read.
The entry points at the folder the app actually lives in, and only if `sttkbrd.sh` exists there. Starting the app
again while it runs just opens its Settings window. If you move the project, the entry is corrected on the next start.

## Auto mode
Tick **Auto mode** in Settings or in the tray menu (blue badge on the icon). The microphone is then listened to
continuously: when speech starts the icon turns red (just like holding the hotkey), and when you stop talking the
text is transcribed and typed. In auto mode the hotkey **pauses / resumes** listening instead of being push-to-talk
(plain icon = paused). Anything that sounds like speech is sent to the provider, which costs money.

## How text is typed
Real key presses through XTest, using your active keyboard layout (Shift/AltGr and dead keys included).
The keymap is never modified. Text the layout cannot type is pasted via the clipboard instead
(Ctrl+V, or Ctrl+Shift+V in terminals) and the previous clipboard text is restored.

## Autostart
Tick **Start automatically when the desktop starts** in Settings. The entry `~/.config/autostart/sttkbrd.desktop` is
written with the path where this copy of sttkbrd actually lives (and only if `sttkbrd.sh` exists there). If you move
the project, the entry is corrected the next time the app starts.

Config: `~/.config/sttkbrd/config.json` (mode 600). Log: `~/.local/state/sttkbrd/sttkbrd.log`.

## Dependencies (system packages)
python3-pynput, python3-sounddevice, python3-numpy, python3-requests, python3-xlib, python3-gi, gir1.2-xapp-1.0
