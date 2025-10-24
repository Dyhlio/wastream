# ===========================
# Languages Dictionary
# ===========================
LANGUAGES = {
    "Arab": ["arab"],
    "Bengali": ["bengali"],
    "Chinese": ["chinese"],
    "English": ["english"],
    "French": ["french", "vf", "vostfr", "truefrench"],
    "French (Canada)": ["french (canada)"],
    "FRENCH AD": ["french ad"],
    "German": ["german"],
    "Hindi": ["hindi"],
    "Italian": ["italian"],
    "Japanese": ["japanese"],
    "Korean": ["korean"],
    "Mandarin": ["mandarin"],
    "Portuguese": ["portuguese"],
    "Russian": ["russian"],
    "Spanish": ["spanish"],
    "Turkish": ["turkish"],
    "Danish": ["danish"],
    "Finnish": ["finnish"],
    "Swedish": ["swedish"],
    "Bulgarian": ["bulgarian", "bulgare"],
    "Dutch": ["dutch"],
    "Persian": ["persian"],
    "Indonesian": ["indonesian"],
    "Hebrew": ["hebrew"],
    "Thai": ["thai"],
    "Czech": ["czech"],
    "Albanian": ["albanian"],
    "Greek": ["greek"],
    "Hungarian": ["hungarian"],
    "Malaysian": ["malaysian"],
    "Norwegian": ["norwegian"],
    "Norwegian Bokmål": ["norwegian bokmål"],
    "Polish": ["polish"],
    "Lithuanian": ["lithuanian"],
    "Croatian": ["croatian"],
    "Malay": ["malay"],
    "Romanian": ["romanian"],
    "Ukrainian": ["ukrainian"],
    "Vietnamese": ["vietnamese"],
    "Sámegiella": ["sámegiella"],
    "Muet": ["muet"],
    "Georgian": ["georgian"],
    "Nigerian": ["nigerian"],
    "Maasai": ["maasai"],
    "Estonian": ["estonian"],
    "Serbian": ["serbian"],
    "Slovak": ["slovak"],
    "Slovenian": ["slovenian"],
    "Amharic": ["amharic"],
    "Belarusian": ["belarusian"],
    "Bosnian": ["bosnian"],
    "Burmese": ["burmese", "myanmar"],
    "Dzongkha": ["dzongkha"],
    "Icelandic": ["icelandic"],
    "Kazakh": ["kazakh"],
    "Kurdish": ["kurdish"],
    "Latin": ["latin"],
    "Latvian": ["latvian"],
    "Macedonian": ["macedonian"],
    "Maori": ["maori"],
    "Mongolian": ["mongolian"],
    "Serbo-Croatian": ["serbo-croatian"],
    "Tagalog": ["tagalog"],
    "Tibetan": ["tibetan"],
    "Walloon": ["walloon"],
    "Wolof": ["wolof"],
    "Yoruba": ["yoruba"],
    "Moore": ["moore"],
    "Quechuan": ["quechuan"],
    "Rwanda": ["rwanda"],
    "Filipino": ["filipino"],
    "Afrikaans": ["afrikaans"],
    "Créole": ["créole"],
    "Haitian Creole": ["haitian creole"],
    "Gujarati": ["gujarati"],
    "Cantonese": ["cantonese"],
    "Armenian": ["armenian"],
    "Azerbaijani": ["azerbaijani"],
    "Basque": ["basque"],
    "Catalan": ["catalan"],
    "Cebuano": ["cebuano"],
    "Chichewa": ["chichewa"],
    "Corsican": ["corsican"],
    "Esperanto": ["esperanto"],
    "Frisian": ["frisian"],
    "Galician": ["galician"],
    "Hausa": ["hausa"],
    "Hawaiian": ["hawaiian"],
    "Igbo": ["igbo"],
    "Irish": ["irish"],
    "Javanese": ["javanese"],
    "Kannada": ["kannada"],
    "Khmer": ["khmer"],
    "Kyrgyz": ["kyrgyz"],
    "Lao": ["lao"],
    "Luxembourgish": ["luxembourgish"],
    "Malagasy": ["malagasy"],
    "Maltese": ["maltese"],
    "Marathi": ["marathi"],
    "Nepali": ["nepali"],
    "Pashto": ["pashto"],
    "Punjabi": ["punjabi"],
    "Sindhi": ["sindhi"],
    "Sinhala": ["sinhala"],
    "Somali": ["somali"],
    "Swahili": ["swahili"],
    "Tajik": ["tajik"],
    "Tamil": ["tamil"],
    "Telugu": ["telugu"],
    "Uzbek": ["uzbek"],
    "Welsh": ["welsh"],
    "Xhosa": ["xhosa"],
    "Yiddish": ["yiddish"],
    "Zulu": ["zulu"],
    "VO": ["vo"],
    "Multi": ["multi"],
    "Unknown": ["unknown"],
}

# ===========================
# Reverse Language Mapping
# ===========================
LANGUAGE_MAPPING = {}
for standard_lang, variants in LANGUAGES.items():
    for variant in variants:
        LANGUAGE_MAPPING[variant.lower()] = standard_lang

# ===========================
# Available Languages
# ===========================
AVAILABLE_LANGUAGES = sorted(list(LANGUAGES.keys()))

# ===========================
# Multi-Language Constants
# ===========================
MULTI_LANGUAGE_PREFIX = "multi ("
MULTI_PREFIX_LENGTH = len(MULTI_LANGUAGE_PREFIX)

# ===========================
# Language Normalization
# ===========================
def normalize_language(raw_language: str) -> str:
    if not raw_language or raw_language is None:
        return "Unknown"

    normalized = raw_language.lower().strip()

    if normalized.upper() in ["N/A", "NULL", "UNKNOWN", "INCONNU", ""]:
        return "Unknown"

    if normalized.startswith(MULTI_LANGUAGE_PREFIX) and normalized.endswith(")"):
        inner_lang = normalized[MULTI_PREFIX_LENGTH:-1].strip()
        mapped_inner = LANGUAGE_MAPPING.get(inner_lang)
        if mapped_inner:
            return mapped_inner

    mapped = LANGUAGE_MAPPING.get(normalized)
    if mapped:
        return mapped

    return "Unknown"

# ===========================
# Subtitle Normalization
# ===========================
def normalize_subtitle(raw_subtitle: str) -> str:
    return normalize_language(raw_subtitle)

# ===========================
# Multi-Languages Normalization
# ===========================
def normalize_multi_languages(languages_list: list) -> str:
    if not languages_list:
        return "Unknown"

    normalized_languages = []
    for lang_dict in languages_list:
        if isinstance(lang_dict, dict):
            lang_name = lang_dict.get("name", "")
            if lang_name:
                normalized = normalize_language(lang_name)
                if normalized and normalized != "Unknown":
                    normalized_languages.append(normalized)

    return ", ".join(normalized_languages) if normalized_languages else "Unknown"

# ===========================
# Multi-Subtitles Normalization
# ===========================
def normalize_multi_subtitles(subtitles_list: list) -> str:
    return normalize_multi_languages(subtitles_list)

# ===========================
# Language Combination
# ===========================
def combine_languages(audio_langs: list, subtitle_langs: list, user_prefs: list = None) -> str:
    normalized_audio = []
    for lang in audio_langs:
        if lang:
            normalized = normalize_language(lang)
            normalized_audio.append(normalized)

    normalized_subs = []
    for lang in subtitle_langs:
        if lang:
            normalized = normalize_language(lang)
            normalized_subs.append(normalized)

    all_langs = []
    for lang in normalized_audio:
        if lang not in all_langs:
            all_langs.append(lang)
    for lang in normalized_subs:
        if lang not in all_langs:
            all_langs.append(lang)

    if user_prefs and "Unknown" not in user_prefs:
        all_langs = [lang for lang in all_langs if lang != "Unknown"]

    if len(all_langs) == 0:
        return "Unknown"

    if len(all_langs) == 1 and all_langs[0] == "Multi":
        return "Multi"

    if len(all_langs) == 1:
        return all_langs[0]

    if len(all_langs) > 1:
        if user_prefs:
            filtered_langs = [lang for lang in all_langs if lang in user_prefs]
            if filtered_langs:
                return f"Multi ({', '.join(filtered_langs)})"
            return f"Multi ({', '.join(all_langs)})"

        return f"Multi ({', '.join(all_langs)})"

    return "Unknown"
