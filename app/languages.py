"""DubVerse language + voice map.

Each entry:
  name       display name
  google     code for machine translation (MyMemory / Google)
  gtts       gTTS language code, or None if gTTS has no voice for it
  edge       (locale, male_voice, female_voice) for Edge neural TTS, or None

Edge TTS is the primary dubbing voice because it offers real male and female
neural voices per language (needed for the speaker-gender matching rule).
gTTS is the automatic fallback where Edge is unavailable.
"""

LANGUAGES = {
    "en":    {"name": "English",    "google": "en",    "gtts": "en",    "edge": ("en-US", "en-US-ChristopherNeural", "en-US-JennyNeural")},
    "ur":    {"name": "Urdu",       "google": "ur",    "gtts": "ur",    "edge": ("ur-PK", "ur-PK-AsadNeural", "ur-PK-UzmaNeural")},
    "hi":    {"name": "Hindi",      "google": "hi",    "gtts": "hi",    "edge": ("hi-IN", "hi-IN-MadhurNeural", "hi-IN-SwaraNeural")},
    "ar":    {"name": "Arabic",     "google": "ar",    "gtts": "ar",    "edge": ("ar-SA", "ar-SA-HamadNeural", "ar-SA-ZariyahNeural")},
    "es":    {"name": "Spanish",    "google": "es",    "gtts": "es",    "edge": ("es-ES", "es-ES-AlvaroNeural", "es-ES-ElviraNeural")},
    "fr":    {"name": "French",     "google": "fr",    "gtts": "fr",    "edge": ("fr-FR", "fr-FR-HenriNeural", "fr-FR-DeniseNeural")},
    "de":    {"name": "German",     "google": "de",    "gtts": "de",    "edge": ("de-DE", "de-DE-ConradNeural", "de-DE-KatjaNeural")},
    "it":    {"name": "Italian",    "google": "it",    "gtts": "it",    "edge": ("it-IT", "it-IT-DiegoNeural", "it-IT-ElsaNeural")},
    "pt":    {"name": "Portuguese", "google": "pt",    "gtts": "pt",    "edge": ("pt-BR", "pt-BR-AntonioNeural", "pt-BR-FranciscaNeural")},
    "ru":    {"name": "Russian",    "google": "ru",    "gtts": "ru",    "edge": ("ru-RU", "ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural")},
    "tr":    {"name": "Turkish",    "google": "tr",    "gtts": "tr",    "edge": ("tr-TR", "tr-TR-AhmetNeural", "tr-TR-EmelNeural")},
    "fa":    {"name": "Persian",    "google": "fa",    "gtts": None,    "edge": ("fa-IR", "fa-IR-FaridNeural", "fa-IR-DilaraNeural")},
    "bn":    {"name": "Bengali",    "google": "bn",    "gtts": "bn",    "edge": ("bn-BD", "bn-BD-PradeepNeural", "bn-BD-NabanitaNeural")},
    "id":    {"name": "Indonesian", "google": "id",    "gtts": "id",    "edge": ("id-ID", "id-ID-ArdiNeural", "id-ID-GadisNeural")},
    "ms":    {"name": "Malay",      "google": "ms",    "gtts": "ms",    "edge": ("ms-MY", "ms-MY-OsmanNeural", "ms-MY-YasminNeural")},
    "zh-CN": {"name": "Chinese (Simplified)", "google": "zh-CN", "gtts": "zh-CN", "edge": ("zh-CN", "zh-CN-YunyangNeural", "zh-CN-XiaoxiaoNeural")},
    "ja":    {"name": "Japanese",   "google": "ja",    "gtts": "ja",    "edge": ("ja-JP", "ja-JP-KeitaNeural", "ja-JP-NanamiNeural")},
    "ko":    {"name": "Korean",     "google": "ko",    "gtts": "ko",    "edge": ("ko-KR", "ko-KR-InJoonNeural", "ko-KR-SunHiNeural")},
    "nl":    {"name": "Dutch",      "google": "nl",    "gtts": "nl",    "edge": ("nl-NL", "nl-NL-MaartenNeural", "nl-NL-ColetteNeural")},
    "pl":    {"name": "Polish",     "google": "pl",    "gtts": "pl",    "edge": ("pl-PL", "pl-PL-MarekNeural", "pl-PL-ZofiaNeural")},
    "uk":    {"name": "Ukrainian",  "google": "uk",    "gtts": "uk",    "edge": ("uk-UA", "uk-UA-OstapNeural", "uk-UA-PolinaNeural")},
    "sv":    {"name": "Swedish",    "google": "sv",    "gtts": "sv",    "edge": ("sv-SE", "sv-SE-MattiasNeural", "sv-SE-SofieNeural")},
    "he":    {"name": "Hebrew",     "google": "he",    "gtts": None,    "edge": ("he-IL", "he-IL-AvriNeural", "he-IL-HilaNeural")},
    "ps":    {"name": "Pashto",     "google": "ps",    "gtts": None,    "edge": ("ps-AF", "ps-AF-GulNawazNeural", "ps-AF-LatifaNeural")},
    "el":    {"name": "Greek",      "google": "el",    "gtts": "el",    "edge": None},
    "th":    {"name": "Thai",       "google": "th",    "gtts": "th",    "edge": None},
    "vi":    {"name": "Vietnamese", "google": "vi",    "gtts": "vi",    "edge": None},
    "sw":    {"name": "Swahili",    "google": "sw",    "gtts": "sw",    "edge": None},
    "ha":    {"name": "Hausa",      "google": "ha",    "gtts": "ha",    "edge": None},
    "am":    {"name": "Amharic",    "google": "am",    "gtts": "am",    "edge": None},
    "ne":    {"name": "Nepali",     "google": "ne",    "gtts": "ne",    "edge": None},
    "si":    {"name": "Sinhala",    "google": "si",    "gtts": "si",    "edge": None},
    "ta":    {"name": "Tamil",      "google": "ta",    "gtts": "ta",    "edge": None},
    "te":    {"name": "Telugu",     "google": "te",    "gtts": "te",    "edge": None},
    "mr":    {"name": "Marathi",    "google": "mr",    "gtts": "mr",    "edge": None},
    "pa":    {"name": "Punjabi",    "google": "pa",    "gtts": "pa",    "edge": None},
    "gu":    {"name": "Gujarati",   "google": "gu",    "gtts": "gu",    "edge": None},
    "ml":    {"name": "Malayalam",  "google": "ml",    "gtts": "ml",    "edge": None},
    "kn":    {"name": "Kannada",    "google": "kn",    "gtts": "kn",    "edge": None},
}


def language_list():
    return [
        {"code": code, "name": info["name"], "dubbing": bool(info["edge"] or info["gtts"])}
        for code, info in sorted(LANGUAGES.items(), key=lambda kv: kv[1]["name"])
    ]
