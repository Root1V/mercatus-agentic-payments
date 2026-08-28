"""Resumen extractivo por frecuencia de palabras -- sin dependencias externas,
determinista, para que el ejemplo de vendedor no necesite ninguna API key
propia (la única API que cobra aquí es la de pago del framework)."""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-záéíóúñü0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "y", "o",
    "en", "a", "al", "que", "por", "para", "con", "es", "se", "su", "sus", "lo",
    "the", "an", "of", "and", "or", "in", "to", "is", "it", "that", "for",
}


def summarize(text: str, max_sentences: int = 2) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    if len(sentences) <= max_sentences:
        return text.strip()

    frequencies: dict[str, int] = {}
    for word in _WORD_RE.findall(text.lower()):
        if word in _STOPWORDS:
            continue
        frequencies[word] = frequencies.get(word, 0) + 1

    def score(sentence: str) -> int:
        return sum(frequencies.get(word, 0) for word in _WORD_RE.findall(sentence.lower()))

    ranked = sorted(range(len(sentences)), key=lambda i: score(sentences[i]), reverse=True)
    top_indices = sorted(ranked[:max_sentences])
    return " ".join(sentences[i] for i in top_indices)
