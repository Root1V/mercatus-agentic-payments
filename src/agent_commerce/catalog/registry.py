"""Catálogo de servicios pagos: puerto + implementación en memoria.

`InMemoryServiceRegistry` simula el marketplace de agents.circle.com (900+
servicios pagos por llamada) para poder desarrollar y probar sin red ni
credenciales. Un catálogo real (ver `circle_marketplace.py`, stub) solo
necesitaría implementar el mismo puerto `ServiceRegistry`.
"""

from __future__ import annotations

import abc
import json
import re
from pathlib import Path

from .models import ServiceListing

# Un agente puede pedir "resumen" cuando el catálogo dice "resume", o
# "summary" cuando el tag es "summarize" -- son la misma raíz, no la misma
# cadena. Exigir substring literal (como antes) los hacía indistinguibles de
# un "no existe". En vez de eso, se tokeniza en palabras y dos palabras
# matchean si son iguales, o si comparten un prefijo de al menos
# `_MIN_SHARED_PREFIX` caracteres -- alcanza para variantes de idioma/
# conjugación sin generar falsos positivos entre palabras cortas no
# relacionadas (donde el prefijo compartido nunca llega a ese mínimo).
_MIN_SHARED_PREFIX = 4
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _shared_prefix_len(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b, strict=False):
        if ca != cb:
            break
        n += 1
    return n


def _words_match(query_word: str, listing_word: str) -> bool:
    if query_word == listing_word:
        return True
    return _shared_prefix_len(query_word, listing_word) >= _MIN_SHARED_PREFIX


class ServiceRegistry(abc.ABC):
    @abc.abstractmethod
    async def search(self, query: str) -> list[ServiceListing]: ...

    @abc.abstractmethod
    async def get(self, service_id: str) -> ServiceListing: ...


class ServiceNotFoundError(KeyError):
    pass


class InMemoryServiceRegistry(ServiceRegistry):
    def __init__(self, listings: list[ServiceListing]) -> None:
        self._by_id = {listing.id: listing for listing in listings}
        self._searchable_words = {
            listing.id: _tokenize(
                " ".join([listing.name, listing.description, *listing.capability_tags])
            )
            for listing in listings
        }

    @classmethod
    def from_json_file(cls, path: str | Path) -> InMemoryServiceRegistry:
        data = json.loads(Path(path).read_text())
        return cls([ServiceListing.model_validate(entry) for entry in data])

    def all(self) -> list[ServiceListing]:
        return list(self._by_id.values())

    async def search(self, query: str) -> list[ServiceListing]:
        query_words = _tokenize(query)
        if not query_words:
            return []
        return [
            listing
            for listing in self._by_id.values()
            if any(
                _words_match(qw, lw)
                for qw in query_words
                for lw in self._searchable_words[listing.id]
            )
        ]

    async def get(self, service_id: str) -> ServiceListing:
        try:
            return self._by_id[service_id]
        except KeyError as exc:
            raise ServiceNotFoundError(service_id) from exc
