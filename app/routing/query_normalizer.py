import re
import unicodedata

from app.routing.schemas import NormalizedQuery

_WHITESPACE = re.compile(r"\s+")


class QueryNormalizer:
    @staticmethod
    def fold(text: str) -> str:
        decomposed = unicodedata.normalize("NFD", text.casefold())
        ascii_text = "".join(
            character
            for character in decomposed
            if unicodedata.category(character) != "Mn"
        ).replace("đ", "d")
        return _WHITESPACE.sub(" ", ascii_text.strip())

    def normalize(self, text: str) -> NormalizedQuery:
        original = text
        normalized = _WHITESPACE.sub(" ", text.strip())
        return NormalizedQuery(
            original_text=original,
            normalized_text=normalized,
            folded_text=self.fold(normalized),
        )
