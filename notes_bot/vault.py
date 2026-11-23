"""Vault Obsidian: nazwy plików, frontmatter, zapis notatek i indeks pojęć z archiwum."""

import datetime
import json
import os
import re
import urllib.parse

from .config import MAX_FILENAME_CHARS, NOTES_DIR

def _safe_filename(text):
    # Poza znakami zabronionymi w systemach plików usuwamy też #^[]|, które psują linki [[...]] w Obsidianie.
    name = re.sub(r'[\\/*?:"<>|#^\[\]]', '', text)
    name = re.sub(r'\s+', ' ', name).strip(' .')
    return name[:MAX_FILENAME_CHARS].rstrip(' .') or "Notatka"


def _obsidian_tag(text):
    # Tagi w Obsidianie nie mogą zawierać spacji i muszą mieć choć jeden znak niebędący cyfrą.
    tag = re.sub(r'\s+', '-', text.strip().lower())
    tag = re.sub(r'[^\w\-/]', '', tag).strip('-')
    return tag if re.search(r'\D', tag) else ''


def _yaml_str(text):
    # Łańcuch JSON jest poprawnym łańcuchem YAML w cudzysłowie - bezpieczne escapowanie " i \.
    return json.dumps(text, ensure_ascii=False)


def _read_concepts(path):
    """Pojęcia notatki z frontmattera: lista `concepts` (starsze notatki) albo, gdy jej brak, `tags`."""
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')
    if not lines or lines[0] != '---':
        return []
    legacy, from_tags, current = [], [], None
    for line in lines[1:]:
        if line == '---':
            break
        if line in ('concepts:', 'tags:'):
            current = line[:-1]
        elif current and line.startswith('  - '):
            value = line[4:].strip()
            if current == 'concepts':
                # strip('[]') - najstarsze notatki zapisywały pojęcia jako "[[pojęcie]]".
                legacy.append(json.loads(value).strip('[]') if value.startswith('"') else value.strip('[]'))
            else:
                # Tag to pojęcie z myślnikami zamiast spacji (i małymi literami).
                from_tags.append(value.replace('-', ' '))
        else:
            current = None
    return legacy or from_tags


def load_vault_index():
    """Słownik pojęć z frontmatterów istniejących notatek, od najczęstszych."""
    note_count, concept_counts = 0, {}
    if os.path.isdir(NOTES_DIR):
        for name in os.listdir(NOTES_DIR):
            if not name.endswith('.md'):
                continue
            try:
                concepts = _read_concepts(os.path.join(NOTES_DIR, name))
            except Exception as e:
                print(f"  Pominięto w indeksie {name}: {e}")
                continue
            note_count += 1
            for c in concepts:
                # Notatki bez listy concepts dają pojęcia małymi literami - zachowujemy wariant z dużymi.
                key = next((k for k in concept_counts if k.lower() == c.lower()), c)
                if key.islower() and not c.islower():
                    concept_counts[c] = concept_counts.pop(key)
                    key = c
                concept_counts[key] = concept_counts.get(key, 0) + 1
    # Najczęstsze pojęcia najpierw - przy obcięciu do limitu zostają najważniejsze węzły grafu.
    concepts = sorted(concept_counts, key=lambda c: (-concept_counts[c], c.lower()))
    print(f"Archiwum: {note_count} notatek, {len(concepts)} pojęć.")
    return {'concepts': concepts}


def _build_note_markdown(note_title, source_title, video_url, summary, tags, created):
    tag_lines = [f"  - {t}" for t in dict.fromkeys(_obsidian_tag(t) for t in tags) if t]
    frontmatter = [
        "---",
        f"title: {_yaml_str(note_title)}",
        f"source: {_yaml_str(source_title)}",
        f"url: {_yaml_str(video_url)}",
        f"created: {created}",
        "tags:", *tag_lines,
        "---",
    ]
    return "\n".join(frontmatter) + f"\n\n# {note_title}\n\n{summary.strip()}\n"


def save_note(note_title, source_title, video_url, summary, tags):
    """Zapisuje notatkę do NOTES_DIR i zwraca nazwę pliku (None przy błędzie)."""
    created = datetime.date.today().isoformat()
    base = _safe_filename(note_title)
    try:
        os.makedirs(NOTES_DIR, exist_ok=True)
        filename, n = f"{base}.md", 2
        while os.path.exists(os.path.join(NOTES_DIR, filename)):
            filename, n = f"{base} ({n}).md", n + 1
        with open(os.path.join(NOTES_DIR, filename), 'w', encoding='utf-8', newline='\n') as f:
            f.write(_build_note_markdown(note_title, source_title, video_url, summary, tags, created))
        print(f"Zapisano notatkę: {NOTES_DIR}/{filename}")
        return filename
    except Exception as e:
        print(f"Błąd podczas zapisu notatki: {e}")
        return None


def note_web_url(filename):
    """Link do notatki na GitHubie (zmienne ustawiane automatycznie przez Actions); None lokalnie."""
    server, repo = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY")
    branch = os.environ.get("GITHUB_REF_NAME") or "master"
    if not (server and repo):
        return None
    return f"{server}/{repo}/blob/{branch}/{NOTES_DIR}/{urllib.parse.quote(filename)}"


def add_to_vault(vault, tags):
    """Dopisuje pojęcia świeżej notatki do słownika, żeby kolejne filmy z tego przebiegu używały tych samych nazw."""
    concepts = dict.fromkeys(_safe_filename(t) for t in tags if t.strip())
    vault['concepts'] += [c for c in concepts if c not in vault['concepts']]
