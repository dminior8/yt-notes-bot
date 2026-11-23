"""Stan: lista przetworzonych materiałów (YouTube i Twitter) zapisywana w pliku tekstowym."""

import os

from .config import PROCESSED_FILE

def get_processed_videos():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return {line.strip() for line in f if line.strip()}

def save_processed_video(video_id):
    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{video_id}\n")
