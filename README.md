# Academic Notes for Obsidian (YouTube + Twitter/X)

Automated pipeline that turns YouTube playlist videos and Twitter/X videos sent to a Telegram bot into structured academic Markdown (`.md`) research notes for Obsidian. It runs on GitHub Actions and reports via Telegram.

This repository holds only the code. The notes live in a separate (usually private) **notes repo**, which calls the reusable workflow from here on a schedule. See [Set Up Your Own Notes Repo](#set-up-your-own-notes-repo).

---

## Architecture Overview

```text
 [YouTube playlist]                    [Telegram chat: Twitter/X links]
        │                                        │
        ▼ (GitHub Actions - daily 20:00 UTC, or manual run)
 1a. Subtitles via yt-dlp               1b. Audio download via yt-dlp
     Fallback: audio download + Gemini      (only messages from TELEGRAM_CHAT_ID),
     Files API when no captions             uploaded to the Gemini Files API
        │                                        │
        └───────────────────┬────────────────────┘
                            ▼
 2. Content analysis via Google Gemini API (gemini-3.8-flash, fallback model chain)
    - Concept dictionary built from the tags of existing notes keeps tag names consistent
    - Structured extraction via Pydantic schema (theses, concepts, analysis, quotes, synthesis)
    - Quote verification via transcript 3-gram matching (YouTube with captions only)
    - Retries (incl. 429/5xx) rotating through the model chain (up to 8 attempts, backoff capped at 2 min, 20 min budget per summary) until the note reaches a minimum length (60% of it for Flash-Lite models), wikilink cleaning
                            │
                            ▼
 3. Markdown file written to `notes/` of the notes repo + Git commit & push
                            │
                            ▼
 4. Telegram notification (with GitHub note URL)
                            │
                            ▼
 [Obsidian] (sync via Obsidian Git)
```

### Twitter/X flow

1. Send a link to a tweet containing a video (`x.com` or `twitter.com`) to the bot, from the chat configured in `TELEGRAM_CHAT_ID`. Messages from other chats are ignored.
2. On the next run the script reads the bot's pending updates (Telegram keeps them for about 24 h), downloads the audio and sends it to Gemini.
3. The same audio pipeline is used for YouTube videos without captions (if the audio download fails, the YouTube URL is sent to Gemini directly). The required note length scales with the recording length: 35 words per minute, at least 900 and at most 2500 words. Longer recordings also get a longer request timeout (up to 15 min). Constants are in `notes_bot/config.py`.
4. Quotes from audio cannot be verified against a transcript, so they are kept as returned by the model.
5. Processed links are stored in `processed_videos.txt` as `tw_<message_id>_<hash>`. A link that can never work (no video, protected or unavailable tweet) is marked as processed; other failures are retried on the next run while the message is still available.

---

## Tech Stack

- **Runtime:** Python 3.11
- **Orchestration:** GitHub Actions
- **AI Processing:** Google Gemini API (`google-genai` SDK; primary: `gemini-3.8-flash`, fallbacks: `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, thinking level: `medium`, `low` for Flash-Lite)
- **Extraction:** `yt-dlp` (supports `cookies.txt` and Deno JS runtime for YouTube; ffmpeg for audio extraction)
- **Target Storage:** Obsidian Markdown (YAML Frontmatter, clean text)
- **Notifications and input for Twitter/X links:** Telegram Bot API

---

## Repository Structure

```text
.
├── .github/workflows/
│   └── summarize.yml      # Reusable workflow (workflow_call) run from a notes repo
├── template/              # Starter files for a notes repo (caller workflow, .gitignore, Obsidian config)
├── prompt.md              # Academic prompt template for Gemini API
├── requirements.txt       # Python dependencies
├── summarizer.py          # Entry point (calls notes_bot.main)
└── notes_bot/
    ├── main.py            # Orchestration: YouTube first, then Twitter/X links from Telegram
    ├── youtube.py         # Playlist, subtitles (yt-dlp), YouTube note pipeline
    ├── twitter.py         # Telegram links, Twitter/X note pipeline
    ├── gemini.py          # Prompt, client, retries, model chain, audio upload (shared)
    ├── media.py           # Audio download via yt-dlp (shared)
    ├── rendering.py       # Quote verification and Markdown rendering of the model output
    ├── vault.py           # Obsidian note writing, frontmatter, concept index
    ├── telegram.py        # Notifications and diagnostics
    ├── state.py           # processed_videos.txt handling
    ├── schema.py          # Pydantic response schema
    ├── config.py          # Secrets and constants
    └── http_utils.py      # Small HTTP helpers
```

---

The notes repo contains the generated notes and the bot's state:

```text
.
├── .github/workflows/notes.yml   # Schedule; calls summarize.yml from this repo
├── notes/                        # Generated Markdown notes (Obsidian vault content)
├── processed_videos.txt          # Processed YouTube IDs and Twitter/X link keys
└── prompt.md                     # (Optional) overrides the bot's prompt.md
```

---

## Set Up Your Own Notes Repo

1. Create a new **private** GitHub repository for your notes.
2. Copy the contents of [`template/`](template/) into it (including the hidden `.github/`, `.obsidian/` and `.gitignore`) and push.
3. Add the secrets listed below to the notes repo.
4. Open `Actions` -> `YouTube AI Summarizer to Obsidian` -> `Run workflow` to test it. After that it runs daily at 20:00 UTC (change the `cron` line in `notes.yml` to adjust).
5. Optionally open the repo in Obsidian (see [Obsidian Setup](#obsidian-setup)).

The caller workflow uses `@master` of this repo, so bot fixes reach you automatically. Pin a tag or commit SHA in `uses:` and in the `bot_ref` input if you prefer to update manually. If you fork the bot, change `uses:` and set the `bot_repository` input to your fork.

To customise the notes, put your own `prompt.md` in the root of the notes repo; it replaces the bundled one. Keep the length ranges in it compatible with `notes_bot/schema.py`.

Private repositories use the GitHub Actions minutes of your plan; a daily run usually takes a few to a dozen minutes.

---

## Required Secrets (GitHub Secrets)

Configure the following secrets in the **notes repo** under `Settings` -> `Secrets and variables` -> `Actions` (the caller workflow passes them on with `secrets: inherit`):

| Secret Name | Description |
| :--- | :--- |
| `YOUTUBE_API_KEY` | Google Cloud Console API key with YouTube Data API v3 enabled |
| `PLAYLIST_ID` | Targeted YouTube playlist ID |
| `GEMINI_API_KEY` | Google Gemini API key |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token obtained via `@BotFather` |
| `TELEGRAM_CHAT_ID` | Target Telegram chat ID (notifications; also the only chat accepted as a source of Twitter/X links) |
| `YOUTUBE_COOKIES` | *(Optional)* Raw content of `cookies.txt` to bypass bot detection |

### Workflow Inputs (optional, `with:` in `notes.yml`)
- `gemini_model`: Model override (Default: `gemini-3.8-flash`)
- `gemini_fallback_models`: Comma-separated fallback chain, tried in order (Default: `gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite`)
- `gemini_thinking_level`: Thinking level override (Default: `medium`)
- `bot_repository` / `bot_ref`: Where the bot code is checked out from (Default: `dminior8/yt-notes-bot` / `master`)
- `timeout_minutes`: Job timeout (Default: `45`)

### Environment Variables
The same names as the secrets and inputs above (`GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`, `GEMINI_THINKING_LEVEL`) are read from the environment. Paths are relative to the working directory, i.e. the notes repo:
- `NOTES_DIR` (Default: `notes`), `PROCESSED_FILE` (Default: `processed_videos.txt`), `COOKIES_FILE` (Default: `cookies.txt`)
- `PROMPT_FILE` (Default: `prompt.md` bundled with the bot)

---

## Running Locally

Run the bot from the notes repo directory, so notes and state are written there:

```bash
pip install -r path/to/yt-notes-bot/requirements.txt
# set the secrets above as environment variables, then, inside the notes repo:
python path/to/yt-notes-bot/summarizer.py
```

`ffmpeg` must be available on `PATH` for audio downloads (Twitter/X, and YouTube videos without captions; audio is extracted to MP3). The workflow installs it with `apt-get`, as the `ubuntu-latest` runner does not ship it.

---

## Output Note Schema

Each generated `.md` note adheres to the following structure:

```markdown
---
title: "Mechanizm kozła ofiarnego a geneza religii"
source: "Original Video Title"
url: "https://www.youtube.com/watch?v=... or https://x.com/..."
created: 2026-11-05
tags:
  - antropologia-religii
  - rene-girard
  - teoria-mimetyczna
---

# Mechanizm kozła ofiarnego a geneza religii

## Streszczenie
...

## Kontekst i uczestnicy
- ...

## Tezy główne
- **Teza** - ...

## Aparat pojęciowy
- **Pojęcie** - ...

## Analiza problemu
### Wątek tematyczny
...

## Przykłady, przypadki i dane
- **Przykład** - ...

## Kontrargumenty i spory
- ...

## Odniesienia
- **Odniesienie** - ...

## Wybrane cytaty
- "Dosłowny cytat" (Tłumaczenie) - Mówca

## Kwestie otwarte i ograniczenia
- ...

## Synteza
...
```

---

## Obsidian Setup

1. Clone the notes repo and open its root as an Obsidian vault (notes are in `notes/`; `Notatki.md` lists them with the **Dataview** plugin).
2. Install the **Obsidian Git** plugin (*Vinzent*) in Obsidian.
3. Configure your GitHub Personal Access Token (PAT) with access to the notes repo within the plugin settings (on mobile).
4. Enable **Pull updates on startup** to pull new notes on application open.