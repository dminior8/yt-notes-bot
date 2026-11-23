"""Telegram: wysyłanie powiadomień i diagnostyka konfiguracji bota."""

import urllib.error
import urllib.parse

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .http_utils import http_error_body, http_json

def telegram_api(method, data=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    encoded = urllib.parse.urlencode(data).encode('utf-8') if data else None
    return http_json(url, data=encoded, method='POST' if data else None)

def send_telegram_notification(note_title, source_title, video_url, tags, note_url=None):
    message = (f"📑 {note_title}\n\n"
               f"Nowa notatka w vaulcie Obsidian.\n"
               f"Materiał: {source_title}\n"
               f"Tagi: {', '.join(tags)}\n"
               f"Link do materiału: {video_url}")
    if note_url:
        message += f"\nNotatka: {note_url}"
    try:
        telegram_api("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except urllib.error.HTTPError as e:
        print(f"Błąd Telegram API: {e.code}\n{http_error_body(e)}")
        _telegram_diagnostics()
    except Exception as e:
        print(f"Błąd podczas wysyłania powiadomienia Telegram: {e}")

def _telegram_diagnostics():
    print("  [Telegram] Diagnostyka:")
    cid = TELEGRAM_CHAT_ID
    shape = (f"długość {len(cid)}, "
             f"{'tylko cyfry' if cid.lstrip('-').isdigit() else 'ZAWIERA ZNAKI INNE NIŻ CYFRY'}, "
             f"{'ujemny (grupa/kanał)' if cid.startswith('-') else 'dodatni (czat prywatny)'}")
    print(f"  [Telegram] Skonfigurowany chat_id: {shape}.")

    try:
        me = telegram_api("getMe")["result"]
        print(f"  [Telegram] Token poprawny, bot: @{me.get('username')} (id {me.get('id')}).")
    except Exception as e:
        print(f"  [Telegram] getMe nie powiodło się - token jest błędny: {e}")
        return

    try:
        updates = telegram_api("getUpdates").get("result", [])
    except Exception as e:
        print(f"  [Telegram] getUpdates nie powiodło się: {e}")
        return

    chats = {}
    for update in updates:
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if chat:
                name = chat.get("title") or chat.get("username") or chat.get("first_name") or "?"
                chats[chat["id"]] = f"{chat.get('type')} '{name}'"

    if not chats:
        print(f"  [Telegram] Bot nie otrzymał jeszcze ŻADNEJ wiadomości. Napisz /start do @{me.get('username')}...")
        return

    print("  [Telegram] Czaty widoczne dla bota (id: typ 'nazwa'):")
    for chat_id, description in chats.items():
        marker = "  <-- zgodny z sekretem" if str(chat_id) == cid else ""
        print(f"    {chat_id}: {description}{marker}")
