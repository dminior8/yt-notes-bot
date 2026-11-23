"""Główny przebieg: YouTube, a następnie linki z Twittera przesłane botowi na Telegramie."""

from .state import get_processed_videos, save_processed_video
from .twitter import get_twitter_links_from_telegram, process_twitter_video
from .vault import load_vault_index
from .youtube import get_videos_from_playlist, process_video

def main():
    print("Rozpoczynam sprawdzanie źródeł...")
    processed_videos = get_processed_videos()
    vault = load_vault_index()

    # 1. Przetwarzanie filmów z YouTube
    print("\n--- Sprawdzanie playlisty YouTube ---")
    for video in get_videos_from_playlist():
        if video['id'] in processed_videos:
            print(f"Pominięto YouTube (już przetworzone): {video['title']}")
            continue
        if process_video(video['id'], video['title'], vault):
            save_processed_video(video['id'])
            print(f"Zakończono sukcesem dla YouTube: {video['title']}")

    # 2. Przetwarzanie linków z Telegrama (Twitter/X)
    print("\n--- Sprawdzanie skrzynki Telegram (Twitter) ---")
    for item in get_twitter_links_from_telegram():
        if item['key'] in processed_videos:
            print(f"Pominięto Twitter (już przetworzone): {item['url']}")
            continue
        try:
            result = process_twitter_video(item, vault)
        except Exception as e:  # jeden zły link nie może przerwać reszty przebiegu
            print(f"Nieoczekiwany błąd dla {item['url']}: {e}")
            result = 'retry'
        if result in ('done', 'skip'):
            save_processed_video(item['key'])
            processed_videos.add(item['key'])
        print(f"Twitter {item['url']}: {result}.")


if __name__ == "__main__":
    main()
