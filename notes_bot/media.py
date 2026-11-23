"""Audio download via yt-dlp, shared by the YouTube (no captions) and Twitter/X pipelines."""

import glob
import os

import yt_dlp

from .config import TEMP_MEDIA_BASENAME


class MediaDownloadError(Exception):
    def __init__(self, message, permanent=False):
        super().__init__(message)
        self.permanent = permanent


def cleanup_temp_media():
    for path in glob.glob(f"{TEMP_MEDIA_BASENAME}.*"):
        try:
            os.remove(path)
        except OSError:
            pass


def download_audio(url, default_title, permanent_markers=(), extra_opts=None):
    """Returns (path, title, duration in s). Raises MediaDownloadError (permanent=True: retrying is pointless)."""
    print(f"Pobieranie audio: {url}")
    cleanup_temp_media()
    opts = {
        'format': 'm4a/bestaudio/best',  # audio only, or the whole video when there is no audio-only format
        'outtmpl': f'{TEMP_MEDIA_BASENAME}.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        # Re-encoding to plain MP3 fixes broken timestamps (HLS in MP4), after which
        # Gemini ended file processing in the FAILED state.
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '64'}],
        **(extra_opts or {}),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get('entries'):  # a post with several videos - take the first one
                info = next((e for e in info['entries'] if e), info)
            downloads = info.get('requested_downloads') or []
            path = downloads[0].get('filepath') if downloads else None
            path = path or ydl.prepare_filename(info)
            if not path or not os.path.exists(path):
                raise MediaDownloadError("yt-dlp nie utworzył pliku z nagraniem.", permanent=True)
            title = (info.get('title') or '').strip() or default_title
            return path, title, info.get('duration')
    except MediaDownloadError:
        cleanup_temp_media()
        raise
    except Exception as e:
        cleanup_temp_media()
        permanent = any(marker in str(e).lower() for marker in permanent_markers)
        raise MediaDownloadError(f"Błąd yt-dlp: {e}", permanent=permanent) from e
