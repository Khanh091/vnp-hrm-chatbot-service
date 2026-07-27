import re

from app.routing.schemas import NormalizedQuery

_WHITESPACE = re.compile(r"\s+")


class QueryNormalizer:
    def normalize(self, text: str) -> NormalizedQuery:
        original = text
        normalized = _WHITESPACE.sub(" ", text.strip())
        return NormalizedQuery(
            original_text=original,
            normalized_text=normalized,
        )
