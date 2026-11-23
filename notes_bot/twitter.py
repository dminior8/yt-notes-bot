"""Notatki z Twittera/X: linki z Telegrama, pobieranie audio (yt-dlp), analiza nagrania przez Gemini."""

import hashlib
import re

from .config import TELEGRAM_CHAT_ID, TWITTER_PERMANENT_ERRORS
from .gemini import audio_request_limits, build_audio_prompt, summarize_audio
from .media import MediaDownloadError, cleanup_temp_media, download_audio
from .rendering import render_note_body, strip_wikilinks
from .telegram import send_telegram_notification, telegram_api
from .vault import add_to_vault, note_web_url, save_note

_TWITTER_URL = re.compile(r'https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/[^\s]+')

def get_twitter_links_from_telegram():
    """Linki do tweetów z wiadomości wysłanych botowi przez właściciela (TELEGRAM_CHAT_ID)."""
    print("Sprawdzanie skrzynki Telegram...")
    try:
        data = telegram_api("getUpdates")
    except Exception as e:
        print(f"Błąd odczytu Telegrama: {e}")
        return []

    updates = data.get('result', [])
    print(f"Telegram: pobrano aktualizacji: {len(updates)}.")

    links = []
    for update in updates:
        msg = update.get('message')
        if not msg:
            kinds = [k for k in update if k != 'update_id']
            print(f"  Pominięto aktualizację {update.get('update_id')}: brak pola 'message' (typ: {', '.join(kinds) or '?'}).")
            continue
        chat_id = (msg.get('chat') or {}).get('id')
        if str(chat_id) != str(TELEGRAM_CHAT_ID):
            # Obcy nadawca - nie uruchamiamy kosztownego przetwarzania.
            print(f"  Pominięto wiadomość {msg.get('message_id')}: inny czat ({chat_id}), oczekiwano zgodnie z TELEGRAM_CHAT_ID.")
            continue
        text = msg.get('text') or msg.get('caption') or ''
        urls = list(dict.fromkeys(u.rstrip('.,;:!?)>]"\'') for u in _TWITTER_URL.findall(text)))
        if not urls:
            print(f"  Pominięto wiadomość {msg.get('message_id')}: brak linku do Twittera/X.")
        for url in urls:
            # Klucz łączy wiadomość i link, a prefiks odróżnia go od identyfikatorów z YouTube.
            digest = hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]
            links.append({"key": f"tw_{msg.get('message_id')}_{digest}", "url": url})
    return links


def process_twitter_video(item, vault):
    """Returns 'done' (saved), 'skip' (permanently unprocessable link) or 'retry' (try again on the next run)."""
    url = item['url']
    print(f"\nPrzetwarzanie linku z Twittera: {url}")

    try:
        audio_path, title, duration_s = download_audio(
            url, default_title='Nagranie z Twittera', permanent_markers=TWITTER_PERMANENT_ERRORS)
    except MediaDownloadError as e:
        print(f"{e}")
        return 'skip' if e.permanent else 'retry'

    timeout_s, min_words = audio_request_limits(duration_s)
    try:
        print(f"Nagranie: {(duration_s or 0) / 60:.0f} min, wymagane minimum: {min_words} słów.")
        prompt = build_audio_prompt(title, url, duration_s, vault, "z Twittera (X)")
        ai_result = summarize_audio(audio_path, prompt, timeout_s, min_words)
    except Exception as e:
        print(f"Błąd analizy nagrania z Twittera: {e}")
        return 'retry'
    finally:
        cleanup_temp_media()

    if not ai_result:
        print("Błąd generowania podsumowania (Gemini). Pomijam.")
        return 'retry'

    # No transcript, so quotes cannot be verified (same as the YouTube path without captions).
    summary = strip_wikilinks(render_note_body(ai_result))
    tags = ai_result.get('tags') or []
    note_title = (ai_result.get('title') or '').strip() or title
    print(f"Tytuł notatki: {note_title}")
    print(f"Wygenerowane pojęcia: {tags}")

    filename = save_note(note_title, title, url, summary, tags)
    if not filename:
        return 'retry'

    add_to_vault(vault, tags)
    send_telegram_notification(note_title, title, url, tags, note_web_url(filename))
    return 'done'
