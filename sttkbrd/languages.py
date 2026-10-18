# Languages the speech-to-text models (Whisper family) accept as a language hint: ISO 639-1 code -> name.
LANGUAGES = {
    "af": "Afrikaans", "ar": "Arabic", "hy": "Armenian", "az": "Azerbaijani", "be": "Belarusian",
    "bs": "Bosnian", "bg": "Bulgarian", "ca": "Catalan", "zh": "Chinese", "hr": "Croatian", "cs": "Czech",
    "da": "Danish", "nl": "Dutch", "en": "English", "et": "Estonian", "fi": "Finnish", "fr": "French",
    "gl": "Galician", "de": "German", "el": "Greek", "he": "Hebrew", "hi": "Hindi", "hu": "Hungarian",
    "is": "Icelandic", "id": "Indonesian", "it": "Italian", "ja": "Japanese", "kn": "Kannada", "kk": "Kazakh",
    "ko": "Korean", "lv": "Latvian", "lt": "Lithuanian", "mk": "Macedonian", "ms": "Malay", "mr": "Marathi",
    "mi": "Maori", "ne": "Nepali", "no": "Norwegian", "fa": "Persian", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sr": "Serbian", "sk": "Slovak", "sl": "Slovenian", "es": "Spanish",
    "sw": "Swahili", "sv": "Swedish", "tl": "Tagalog", "ta": "Tamil", "th": "Thai", "tr": "Turkish",
    "uk": "Ukrainian", "ur": "Urdu", "vi": "Vietnamese", "cy": "Welsh",
}
AUTO = "Automatic"


def label(code):
    return "%s (%s)" % (LANGUAGES[code], code) if code in LANGUAGES else code


def labels(current=""):
    """Dropdown entries: Automatic, then the languages by name. A saved code that is not in the list stays selectable."""
    items = [AUTO] + [label(c) for c in sorted(LANGUAGES, key=LANGUAGES.get)]
    return items + ([current] if current and current not in LANGUAGES and current not in items else [])


def normalize(saved):
    """A saved value as one code: the provider takes a single language, so 'sv,en' means 'sv'."""
    parts = (saved or "").replace(";", ",").replace(" ", ",").split(",")
    return next((p.lower() for p in parts if p), "")


def code(entry):
    """Dropdown entry -> code ('' for Automatic)."""
    if entry in ("", None, AUTO):
        return ""
    return entry[entry.rindex("(") + 1:-1] if entry.endswith(")") else entry
