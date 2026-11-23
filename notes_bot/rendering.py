"""Treść notatki: weryfikacja odpowiedzi modelu i składanie Markdown z jej pól."""

import re

_TEXT_FIELDS = ('abstract', 'context', 'theses', 'concepts', 'analysis', 'examples',
                'controversies', 'references', 'quotes', 'open_questions', 'synthesis')

def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)

def note_word_count(ai_result):
    return sum(len(s.split()) for field in _TEXT_FIELDS for s in _iter_strings(ai_result.get(field)))


def _normalized_words(text):
    return re.findall(r'\w+', text.lower())

def _quote_in_transcript(quote, transcript_words, transcript_trigrams):
    # Napisy automatyczne nie mają interpunkcji i bywają przeredagowane przez model o pojedyncze słowa,
    # dlatego porównujemy trigramy słów zamiast dokładnego dopasowania.
    words = _normalized_words(quote)
    if len(words) < 3:
        return ' '.join(words) in ' '.join(transcript_words)
    trigrams = [tuple(words[i:i + 3]) for i in range(len(words) - 2)]
    return sum(t in transcript_trigrams for t in trigrams) / len(trigrams) >= 0.6

def drop_unverified_quotes(ai_result, transcript):
    """Usuwa cytaty, których nie ma w transkrypcji (model potrafi je parafrazować lub zmyślać)."""
    if not transcript:
        return
    words = _normalized_words(transcript)
    trigrams = {tuple(words[i:i + 3]) for i in range(len(words) - 2)}
    quotes = ai_result.get('quotes') or []
    verified = [q for q in quotes if _quote_in_transcript(q.get('text', ''), words, trigrams)]
    if len(verified) < len(quotes):
        print(f"Usunięto {len(quotes) - len(verified)} z {len(quotes)} cytatów nieobecnych w transkrypcji.")
    ai_result['quotes'] = verified


def _clean(text):
    return re.sub(r'\s+', ' ', (text or '')).strip()

def _labeled_list(points):
    return [f"- **{_clean(p.get('label')).strip('*')}** - {_clean(p.get('text'))}"
            for p in points or [] if _clean(p.get('text'))]

def _plain_list(items):
    return [f"- {_clean(item).removeprefix('- ')}" for item in items or [] if _clean(item)]

def _quote_list(quotes):
    lines = []
    for q in quotes or []:
        text = _clean(q.get('text')).strip('"„”')
        if not text:
            continue
        translation = _clean(q.get('translation')).strip('"„”')
        speaker = _clean(q.get('speaker'))
        line = f'- "{text}"'
        if translation and translation != text:
            line += f" ({translation})"
        if speaker:
            line += f" - {speaker}"
        lines.append(line)
    return lines

def _analysis_blocks(sections):
    blocks = []
    for section in sections or []:
        paragraphs = [_clean(p) for p in section.get('paragraphs') or [] if _clean(p)]
        if paragraphs:
            blocks.append(f"### {_clean(section.get('heading')).lstrip('# ')}")
            blocks.extend(paragraphs)
    return blocks

def render_note_body(ai_result):
    """Składa treść notatki; sekcje bez zawartości są pomijane."""
    sections = [
        ("Streszczenie", [_clean(ai_result.get('abstract'))] if _clean(ai_result.get('abstract')) else []),
        ("Kontekst i uczestnicy", _plain_list(ai_result.get('context'))),
        ("Tezy główne", _labeled_list(ai_result.get('theses'))),
        ("Aparat pojęciowy", _labeled_list(ai_result.get('concepts'))),
        ("Analiza problemu", _analysis_blocks(ai_result.get('analysis'))),
        ("Przykłady, przypadki i dane", _labeled_list(ai_result.get('examples'))),
        ("Kontrargumenty i spory", _plain_list(ai_result.get('controversies'))),
        ("Odniesienia", _labeled_list(ai_result.get('references'))),
        ("Wybrane cytaty", _quote_list(ai_result.get('quotes'))),
        ("Kwestie otwarte i ograniczenia", _plain_list(ai_result.get('open_questions'))),
        ("Synteza", [_clean(p) for p in ai_result.get('synthesis') or [] if _clean(p)]),
    ]
    parts = []
    for heading, blocks in sections:
        if not blocks:
            continue
        # Punkty listy jednej sekcji tworzą zwartą listę; akapity i podsekcje oddziela pusta linia.
        lines = [f"## {heading}"]
        for block in blocks:
            is_item = block.startswith('- ')
            lines.append(block if is_item and lines[-1].startswith('- ') else f"\n{block}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


_WIKILINK = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')

def strip_wikilinks(markdown):
    """Zamienia [[cel|alias]] na zwykły tekst - notatki powiązuje się ręcznie w Obsidianie."""
    return _WIKILINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), markdown)
