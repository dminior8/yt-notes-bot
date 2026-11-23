"""Gemini: prompt, klient, ponawianie zapytań i obsługa wgrywanych plików (wspólne dla YouTube i Twittera)."""

import json
import os
import time

from google import genai
from google.genai import types

from .config import (
    AUDIO_MAX_MIN_WORDS, AUDIO_TIMEOUT_BASE_S, AUDIO_TIMEOUT_MAX_S, AUDIO_TIMEOUT_PER_MIN_S,
    AUDIO_WORDS_PER_MINUTE, GEMINI_API_KEY, GEMINI_FALLBACK_MODELS, GEMINI_FILE_ACTIVE_TIMEOUT_S,
    GEMINI_LITE_MIN_WORDS_FACTOR, GEMINI_LITE_THINKING_LEVEL, GEMINI_MAX_ATTEMPTS, GEMINI_MAX_OUTPUT_TOKENS, GEMINI_MODEL,
    GEMINI_RETRY_BASE_DELAY, GEMINI_RETRY_MAX_DELAY, GEMINI_RETRYABLE_CODES, GEMINI_THINKING_LEVEL,
    GEMINI_TOTAL_BUDGET_S, MAX_INDEXED_CONCEPTS, MIN_NOTE_WORDS, PROMPT_FILE,
)
from .rendering import note_word_count
from .schema import SummaryResult

def _existing_concepts(vault):
    """Słownik pojęć z archiwum dla promptu - pozwala modelowi zachować spójne nazwy tagów."""
    if not vault['concepts']:
        return "(brak - to pierwsza notatka w archiwum)"
    return "; ".join(vault['concepts'][:MAX_INDEXED_CONCEPTS])


def load_prompt(title, video_url, source_section, vault):
    # Jeśli prompt.md nie istnieje, używamy awaryjnie zakodowanego stringa
    if not os.path.exists(PROMPT_FILE):
        print("Nie znaleziono pliku prompt.md, używam wbudowanego prompta awaryjnego.")
        return f"Podsumuj film {title} ({video_url}).\n\n{source_section}"

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        template = f.read()
    return (template
            .replace("{{TITLE}}", title)
            .replace("{{VIDEO_URL}}", video_url)
            .replace("{{EXISTING_CONCEPTS}}", _existing_concepts(vault))
            .replace("{{SOURCE}}", source_section))


def make_client(timeout_s):
    return genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))


def gemini_models():
    """Main model followed by the fallback chain, without duplicates."""
    return list(dict.fromkeys([GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]))


def build_audio_prompt(title, url, duration_s, vault, origin):
    """Prompt for an attached recording; origin is e.g. 'z Twittera (X)' or 'z YouTube'."""
    length = f" Nagranie trwa około {round(duration_s / 60)} min." if duration_s else ""
    source_section = (f"Materiał źródłowy: nagranie {origin} załączone do tego zapytania."
                      f"{length} Oprzyj analizę na jego ścieżce dźwiękowej. Objętość notatki "
                      "wynika wyłącznie z treści nagrania - niczego nie dopowiadaj i nie "
                      "rozwlekaj, by osiągnąć długość; używaj poprawnej polszczyzny, bez "
                      "zbędnych anglicyzmów.")
    return load_prompt(title, url, source_section, vault)


def audio_request_limits(duration_s):
    """(request timeout in s, minimum note words) scaled to the recording length."""
    minutes = (duration_s or 0) / 60
    timeout_s = min(AUDIO_TIMEOUT_MAX_S, AUDIO_TIMEOUT_BASE_S + minutes * AUDIO_TIMEOUT_PER_MIN_S)
    min_words = min(AUDIO_MAX_MIN_WORDS, max(MIN_NOTE_WORDS, round(minutes * AUDIO_WORDS_PER_MINUTE)))
    return timeout_s, min_words


def summarize_audio(audio_path, prompt, timeout_s, min_words):
    """Uploads the audio to Gemini, summarizes it with the model chain and always removes the cloud file."""
    client = make_client(timeout_s)
    uploaded_file = None
    try:
        uploaded_file = upload_and_wait(client, audio_path)
        contents = types.Content(parts=[
            types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=uploaded_file.mime_type),
            types.Part.from_text(text=prompt),
        ])
        return call_gemini_with_retries(client, gemini_models(), contents, min_words)
    finally:
        if uploaded_file is not None:
            delete_gemini_file(client, uploaded_file)


def _wait_until_active(client, uploaded_file):
    """Pliki wgrane do Gemini bywają chwilę w stanie PROCESSING - generowanie przed ACTIVE kończy się błędem 400."""
    deadline = time.monotonic() + GEMINI_FILE_ACTIVE_TIMEOUT_S
    while True:
        state = getattr(getattr(uploaded_file, 'state', None), 'name', None) or str(uploaded_file.state or '')
        if state in ('', 'ACTIVE'):
            return uploaded_file
        if state == 'FAILED':
            raise RuntimeError("Gemini nie przetworzyło wgranego pliku (stan FAILED).")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Plik w Gemini nie osiągnął stanu ACTIVE (stan: {state}).")
        time.sleep(5)
        uploaded_file = client.files.get(name=uploaded_file.name)


def upload_and_wait(client, path):
    """Wgrywa plik do Gemini i czeka na stan ACTIVE; przy błędzie sprząta plik w chmurze."""
    print(f"Wysyłanie pliku {path} do Gemini...")
    uploaded_file = client.files.upload(file=path)
    try:
        return _wait_until_active(client, uploaded_file)
    except Exception:
        delete_gemini_file(client, uploaded_file)
        raise


def delete_gemini_file(client, uploaded_file):
    try:
        client.files.delete(name=uploaded_file.name)
    except Exception as e:
        print(f"Nie udało się usunąć pliku z chmury Gemini: {e}")


def _gemini_config(model):
    level = GEMINI_LITE_THINKING_LEVEL if 'lite' in model else GEMINI_THINKING_LEVEL
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=SummaryResult,
        max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(thinking_level=level),
    )

def _required_words(model, min_words):
    """Minimum note length for this model: Flash-Lite models are held to a lower bar."""
    return round(min_words * GEMINI_LITE_MIN_WORDS_FACTOR) if 'lite' in model else min_words

def _finish_reason(response):
    candidates = getattr(response, 'candidates', None) or []
    reason = getattr(candidates[0], 'finish_reason', None) if candidates else None
    return getattr(reason, 'name', reason) or '?'

def call_gemini_with_retries(client, models, contents, min_words):
    """Zwraca pierwszą notatkę o długości >= min_words; po wyczerpaniu prób - najdłuższą otrzymaną."""
    models = list(models)
    best, best_words = None, 0
    began = time.monotonic()
    for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
        if not models:
            break
        if attempt > 1 and time.monotonic() - began > GEMINI_TOTAL_BUDGET_S:
            print(f"Gemini: przekroczono łączny limit czasu ({GEMINI_TOTAL_BUDGET_S // 60} min), kończę próby.")
            break
        model = models[(attempt - 1) % len(models)]
        started = time.monotonic()
        try:
            response = client.models.generate_content(model=model, contents=contents,
                                                      config=_gemini_config(model))
            finish = _finish_reason(response)
            print(f"Gemini ({model}): odpowiedź po {time.monotonic() - started:.0f} s, "
                  f"zakończenie: {finish}.")
            if not response.text:
                raise ValueError(f"pusta odpowiedź (zakończenie: {finish})")
            result = json.loads(response.text)
            words = note_word_count(result)
            required = _required_words(model, min_words)
            print(f"Gemini ({model}): notatka ma {words} słów (wymagane minimum: {required}).")
            if words > best_words:
                best, best_words = result, words
            if words >= required:
                return result
            print(f"Gemini ({model}): notatka niekompletna (próba {attempt}/{GEMINI_MAX_ATTEMPTS}), ponawiam...")
            continue
        except Exception as e:
            elapsed = time.monotonic() - started
            code = getattr(e, 'code', None)
            is_timeout = 'timeout' in type(e).__name__.lower()
            if not (code in GEMINI_RETRYABLE_CODES or is_timeout):
                print(f"Błąd analizy Gemini ({model}): {e}")
                models.remove(model)
                continue
            if attempt >= GEMINI_MAX_ATTEMPTS:
                print(f"Błąd analizy Gemini ({model}): {e}")
                break
            delay = min(GEMINI_RETRY_MAX_DELAY, GEMINI_RETRY_BASE_DELAY * 2 ** (attempt - 1))
            print(f"Gemini ({model}): błąd przejściowy {code or 'timeout'} po {elapsed:.0f} s "
                  f"(próba {attempt}/{GEMINI_MAX_ATTEMPTS}), ponawiam za {delay} s...")
            time.sleep(delay)
    if best:
        print(f"Gemini: brak notatki o wymaganej długości - zapisuję najdłuższą ({best_words} słów).")
        return best
    print("Gemini: wyczerpano próby.")
    return None
