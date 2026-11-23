"""Schemat odpowiedzi Gemini (kolejność pól wyznacza kolejność generowania)."""

from pydantic import BaseModel, Field

# Każda sekcja notatki to osobne pole: model nie może "zwinąć" notatki do jednego akapitu,
# a kolejność pól wyznacza kolejność generowania (pojęcia przed treścią - spójne nazewnictwo).
# Gemini API nie obsługuje wartości domyślnych w schemacie, więc wszystkie pola są wymagane.
class LabeledPoint(BaseModel):
    label: str = Field(description="Krótka etykieta: nazwa tezy, pojęcia, przykładu lub odniesienia.")
    text: str = Field(description="Treść: 2-4 pełne zdania oparte wyłącznie na materiale.")

class AnalysisSection(BaseModel):
    heading: str = Field(description="Nazwa wątku tematycznego.")
    paragraphs: list[str] = Field(description="2-4 akapity po 3-5 zdań rekonstruujące wywód.")

class Quote(BaseModel):
    text: str = Field(description="Dosłowny fragment wypowiedzi w języku materiału, bez zmian.")
    translation: str = Field(description="Tłumaczenie na polski albo pusty tekst, gdy cytat jest po polsku.")
    speaker: str = Field(description="Mówca, jeśli identyfikowalny; inaczej pusty tekst.")

class SummaryResult(BaseModel):
    title: str
    tags: list[str]
    abstract: str = Field(description="Streszczenie: jeden akapit, 5-8 zdań.")
    context: list[str] = Field(description="Kontekst i uczestnicy: 2-5 punktów.")
    theses: list[LabeledPoint] = Field(description="Tezy główne: 5-12 tez (więcej przy dłuższym lub gęstszym materiale).")
    concepts: list[LabeledPoint] = Field(description="Aparat pojęciowy: wszystkie kluczowe pojęcia.")
    analysis: list[AnalysisSection] = Field(description="Analiza problemu: 3-7 wątków do godziny materiału, przy dłuższym - jeden wątek na odrębny problem; najobszerniejsza część.")
    examples: list[LabeledPoint] = Field(description="Przykłady, przypadki i dane; pusta lista, gdy brak.")
    controversies: list[str] = Field(description="Kontrargumenty i spory z materiału; pusta lista, gdy brak.")
    references: list[LabeledPoint] = Field(description="Osoby, dzieła i szkoły przywołane w materiale; pusta lista, gdy brak.")
    quotes: list[Quote] = Field(description="Wybrane cytaty: 4-10 dosłownych fragmentów (do 15 przy bardzo długim materiale).")
    open_questions: list[str] = Field(description="Kwestie otwarte i ograniczenia: 2-6 punktów.")
    synthesis: list[str] = Field(description="Synteza: 2-3 akapity.")
