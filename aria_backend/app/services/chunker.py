import re

from .errors import ServiceError


def chunk_text(text: str, max_chars: int = 180, language: str = "ur") -> list[str]:
    result = []
    for sentence in re.split(r"(?<=[۔؟!?。！？])|(?<=\.)\s+|\n+", text):
        current = ""
        for word in sentence.split():
            if len(word) > max_chars:
                if language in {"zh-cn", "zh", "ja"} and all(ord(c) > 255 for c in word):
                    if current:
                        result.append(current)
                        current = ""
                    result.extend(word[i:i + max_chars] for i in range(0, len(word), max_chars))
                    continue
                raise ServiceError(422, "A word exceeds the chunk limit; add spaces or shorten it")
            candidate = f"{current} {word}".strip()
            if len(candidate) > max_chars:
                result.append(current)
                current = word
            else:
                current = candidate
        if current:
            result.append(current)
    return result
