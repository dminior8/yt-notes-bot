"""Notatki z YouTube: playlista, napisy (yt-dlp), analiza transkrypcji lub nagrania przez Gemini."""

import os
import re
import urllib.parse

import yt_dlp
from google.genai import types

from .config import (
    COOKIES_FILE, GEMINI_REQUEST_TIMEOUT_S, MIN_NOTE_WORDS,
    MIN_NOTE_WORDS_WITHOUT_TRANSCRIPT, MIN_TRANSCRIPT_CHARS, NOTE_TO_TRANSCRIPT_RATIO,
    PLAYLIST_ID, PREFERRED_SUB_LANGS, YOUTUBE_API_KEY,
)
from .gemini import (
    audio_request_limits, build_audio_prompt, call_gemini_with_retries, gemini_models, load_prompt,
    make_client, summarize_audio,
)
from .http_utils import http_json
from .media import MediaDownloadError, cleanup_temp_media, download_audio
from .rendering import drop_unverified_quotes, render_note_body, strip_wikilinks
from .telegram import send_telegram_notification
from .vault import add_to_vault, note_web_url, save_note

# YouTube: lista filmów z playlisty
# ---------------------------------------------------------------------------

def get_videos_from_playlist():
    print("Pobieranie listy filmów z playlisty YouTube...")
    query = urllib.parse.urlencode({
        "part": "snippet", "maxResults": 50, "playlistId": PLAYLIST_ID, "key": YOUTUBE_API_KEY,
    })
    try:
        data = http_json(f"https://www.googleapis.com/youtube/v3/playlistItems?{query}")
        return [
            {"id": item['snippet']['resourceId']['videoId'], "title": item['snippet']['title']}
            for item in data.get('items', [])
        ]
    except Exception as e:
        print(f"Błąd pobierania playlisty: {e}")
        return []

# ---------------------------------------------------------------------------
# Napisy (yt-dlp)
# ---------------------------------------------------------------------------

class _YtdlpLogger:
    def __init__(self):
        self._seen = set()

    def debug(self, msg): pass
    def info(self, msg): pass

    def warning(self, msg):
        self._emit(msg)

    def error(self, msg):
        self._emit(msg)

    def _emit(self, msg):
        if msg not in self._seen:
            self._seen.add(msg)
            print(f"  [yt-dlp] {msg}")

def _vtt_to_text(content):
    text_lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line or '-->' in line or line.startswith(('WEBVTT', 'Kind:', 'Language:')):
            continue
        clean_line = re.sub(r'<[^>]+>', '', line)
        if clean_line and clean_line not in text_lines:
            text_lines.append(clean_line)
    return " ".join(text_lines)

def _pick_subtitle_candidates(info):
    manual = info.get('subtitles') or {}
    auto = info.get('automatic_captions') or {}
    candidates = []

    for lang in PREFERRED_SUB_LANGS:
        if lang in manual:
            candidates.append((lang, 'ręczne', manual[lang]))
    for lang in PREFERRED_SUB_LANGS:
        if f'{lang}-orig' in auto:
            candidates.append((f'{lang}-orig', 'automatyczne (oryginalne)', auto[f'{lang}-orig']))
    for lang, tracks in auto.items():
        if lang.endswith('-orig') and all(c[0] != lang for c in candidates):
            candidates.append((lang, 'automatyczne (oryginalne)', tracks))

    return candidates, manual, auto

def _ytdlp_base_options():
    opts = {'quiet': True, 'logger': _YtdlpLogger()}
    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 10:
        opts['cookiefile'] = COOKIES_FILE
    else:
        print(f"  Uwaga: brak pliku {COOKIES_FILE}, pobieranie bez zalogowania.")
    return opts

def _ytdlp_options():
    return {**_ytdlp_base_options(), 'skip_download': True, 'ignore_no_formats_error': True}

def get_transcript_via_ytdlp(video_url, video_id):
    print(f"Próba pobrania napisów tekstowych przez yt-dlp dla {video_id}...")
    try:
        with yt_dlp.YoutubeDL(_ytdlp_options()) as ydl:
            info = ydl.extract_info(video_url, download=False)
            candidates, manual, auto = _pick_subtitle_candidates(info)

            if not candidates:
                print(f"Brak pasujących napisów. Dostępne ręczne: {sorted(manual)}; automatyczne: {sorted(auto)[:20]}")
                return None

            for lang, kind, tracks in candidates:
                track = next((t for t in tracks if t.get('ext') == 'vtt' and t.get('url')), None)
                if not track:
                    print(f"  Napisy '{lang}' nie mają wariantu VTT, pomijam.")
                    continue

                print(f"Pobieranie napisów {kind} '{lang}'...")
                try:
                    content = ydl.urlopen(track['url']).read().decode('utf-8', errors='ignore')
                except Exception as e:
                    print(f"  Nie udało się pobrać napisów '{lang}': {e}")
                    continue

                full_text = _vtt_to_text(content)
                if len(full_text) > MIN_TRANSCRIPT_CHARS:
                    print(f"Pomyślnie wyciągnięto tekst przez yt-dlp ('{lang}', {len(full_text)} znaków).")
                    return full_text
                print(f"  Napisy '{lang}' są puste lub zbyt krótkie ({len(full_text)} znaków).")

            print("Żadna ze ścieżek napisów nie dała użytecznego tekstu.")
            return None
    except Exception as e:
        print(f"Błąd podczas pobierania napisów przez yt-dlp: {e}")
        return None


def _build_gemini_contents(title, video_url, transcript, vault):
    if transcript:
        print("Model Gemini analizuje transkrypcję z rygorystycznymi wytycznymi akademickimi...")
        source_section = f"Transkrypcja wideo:\n{transcript}"
        return load_prompt(title, video_url, source_section, vault)

    print("Model Gemini analizuje nagranie bezpośrednio z YouTube (brak napisów)...")
    source_section = ("Materiał źródłowy: nagranie wideo załączone do tego zapytania. "
                      "Oprzyj analizę na jego ścieżce dźwiękowej i treści.")
    return types.Content(parts=[
        types.Part(
            file_data=types.FileData(file_uri=video_url),
            video_metadata=types.VideoMetadata(fps=0.2),
        ),
        types.Part(text=load_prompt(title, video_url, source_section, vault)),
    ])


def generate_summary(title, video_url, transcript=None, vault=None):
    vault = vault or {'concepts': []}
    client = make_client(GEMINI_REQUEST_TIMEOUT_S)
    contents = _build_gemini_contents(title, video_url, transcript, vault)
    if transcript:
        min_words = min(MIN_NOTE_WORDS, len(transcript.split()) // NOTE_TO_TRANSCRIPT_RATIO)
    else:
        min_words = MIN_NOTE_WORDS_WITHOUT_TRANSCRIPT
    return call_gemini_with_retries(client, gemini_models(), contents, min_words)


def generate_summary_from_audio(title, video_url, vault):
    """No captions: download the audio and send it to Gemini (lighter and more reliable than passing the
    YouTube URL). If the audio cannot be downloaded, fall back to analysing the URL directly."""
    try:
        audio_path, _, duration_s = download_audio(
            video_url, default_title=title, extra_opts=_ytdlp_base_options())
    except MediaDownloadError as e:
        print(f"{e}")
        print("Nie udało się pobrać audio - przechodzę na analizę linku YouTube bezpośrednio przez Gemini.")
        return generate_summary(title, video_url, transcript=None, vault=vault)

    timeout_s, min_words = audio_request_limits(duration_s)
    try:
        print(f"Nagranie: {(duration_s or 0) / 60:.0f} min, wymagane minimum: {min_words} słów.")
        prompt = build_audio_prompt(title, video_url, duration_s, vault, "z YouTube")
        return summarize_audio(audio_path, prompt, timeout_s, min_words)
    except Exception as e:
        print(f"Błąd analizy audio przez Gemini: {e}")
        return None
    finally:
        cleanup_temp_media()


def process_video(video_id, title, vault):
    """Pełna ścieżka dla jednego filmu. Zwraca nazwę zapisanego pliku albo None."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"\nPrzetwarzanie nowego filmu: {title}")

    transcript = get_transcript_via_ytdlp(video_url, video_id)
    if transcript:
        ai_result = generate_summary(title, video_url, transcript=transcript, vault=vault)
    else:
        print("Brak napisów - pobieram audio i analizuję je przez Gemini.")
        ai_result = generate_summary_from_audio(title, video_url, vault)
    if not ai_result:
        print("Błąd generowania podsumowania (Gemini). Pomijam.")
        return None

    drop_unverified_quotes(ai_result, transcript)
    summary = strip_wikilinks(render_note_body(ai_result))
    tags = ai_result.get('tags') or []
    note_title = (ai_result.get('title') or '').strip() or title
    print(f"Tytuł notatki: {note_title}")
    print(f"Wygenerowane pojęcia: {tags}")

    filename = save_note(note_title, title, video_url, summary, tags)
    if not filename:
        return None

    add_to_vault(vault, tags)
    send_telegram_notification(note_title, title, video_url, tags, note_web_url(filename))
    return filename
