"""Konfiguracja: sekrety ze zmiennych środowiskowych i stałe sterujące przebiegiem."""

import os

def _secret(name, default=""):
    return (os.environ.get(name) or default).strip()

YOUTUBE_API_KEY = _secret("YOUTUBE_API_KEY")
PLAYLIST_ID = _secret("PLAYLIST_ID")
GEMINI_API_KEY = _secret("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = _secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _secret("TELEGRAM_CHAT_ID")

GEMINI_MODEL = _secret("GEMINI_MODEL", "gemini-3.8-flash")
# Comma-separated, tried in order after the main model (attempts rotate through the whole chain).
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in _secret("GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",")
    if m.strip()
]
# Flash models think longer (more accurate extraction from a long transcript); Flash-Lite stays at "low".
GEMINI_THINKING_LEVEL = _secret("GEMINI_THINKING_LEVEL", "medium")
GEMINI_LITE_THINKING_LEVEL = "low"
# Flash-Lite writes shorter notes; demanding the full length would trigger pointless retries or padding
# and hallucinations. A lite model's note counts as complete at this fraction of the required minimum.
GEMINI_LITE_MIN_WORDS_FACTOR = 0.6
# Limit obejmuje też tokeny myślenia - przy domyślnym długa notatka bywa ucinana.
GEMINI_MAX_OUTPUT_TOKENS = 65536
GEMINI_MAX_ATTEMPTS = 8
GEMINI_RETRY_BASE_DELAY = 15
GEMINI_RETRY_MAX_DELAY = 120
# Overall cap for one summary (all attempts and waits), so the 45 min job limit is never hit mid-run
# (the commit step would be skipped and finished notes lost).
GEMINI_TOTAL_BUDGET_S = 20 * 60
# Notatka ma kilka tysięcy słów, a model myśli przed pisaniem - odpowiedź trwa do kilku minut.
GEMINI_REQUEST_TIMEOUT_S = 300
# 502/503/504 are transient server-side failures (overload, deadline exceeded); 504 used to be treated as permanent.
GEMINI_RETRYABLE_CODES = {429, 500, 502, 503, 504}
# Notatka krótsza niż ~1/6 transkrypcji (maks. MIN_NOTE_WORDS słów) jest ponawiana jako niekompletna.
MIN_NOTE_WORDS = 900
MIN_NOTE_WORDS_WITHOUT_TRANSCRIPT = 400

# Audio sources (Twitter/X, and YouTube videos without captions): the required note length grows with the
# recording length (the prompt assumes roughly 2500-4000 words per hour). The threshold is deliberately
# below that range and capped - demanding too much encourages padding and hallucinations instead of
# a fuller description of the content.
AUDIO_WORDS_PER_MINUTE = 35
AUDIO_MAX_MIN_WORDS = 2500
AUDIO_TIMEOUT_BASE_S = 300
AUDIO_TIMEOUT_PER_MIN_S = 5
AUDIO_TIMEOUT_MAX_S = 900
GEMINI_FILE_ACTIVE_TIMEOUT_S = 300
TWITTER_PERMANENT_ERRORS = ("no video could be found", "no video", "unsupported url",
                            "this tweet is unavailable", "tweet is protected")
NOTE_TO_TRANSCRIPT_RATIO = 6

PREFERRED_SUB_LANGS = ['pl', 'en']
# Paths are relative to the working directory, which is the notes repo (the bot code lives elsewhere).
COOKIES_FILE = _secret("COOKIES_FILE", "cookies.txt")
MIN_TRANSCRIPT_CHARS = 100

PROCESSED_FILE = _secret("PROCESSED_FILE", "processed_videos.txt")
TEMP_MEDIA_BASENAME = "temp_audio"
# Defaults to the prompt shipped with the bot; a notes repo can override it with its own file.
PROMPT_FILE = _secret(
    "PROMPT_FILE", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompt.md"))
# Katalog z notatkami; commitowany przez workflow i otwierany w Obsidianie jako vault.
NOTES_DIR = _secret("NOTES_DIR", "notes")
MAX_FILENAME_CHARS = 120

# Ile istniejących pojęć przekazywać modelowi (słownik rośnie z archiwum).
MAX_INDEXED_CONCEPTS = 600
