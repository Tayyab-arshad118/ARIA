import json
import re
import unicodedata

from ..db import RuntimeSetting
from .errors import ServiceError

LABELS = {"ur": "Urdu", "en": "English", "hi": "Hindi", "ar": "Arabic", "es": "Spanish", "fr": "French",
          "de": "German", "it": "Italian", "pt": "Portuguese", "pl": "Polish", "tr": "Turkish", "ru": "Russian",
          "nl": "Dutch", "cs": "Czech", "zh-cn": "Chinese", "ja": "Japanese", "hu": "Hungarian", "ko": "Korean"}


class Languages:
    def __init__(self, settings, db, cipher):
        self.settings, self.db, self.cipher = settings, db, cipher
        self.tags, self.discovered = {settings.lang_tag}, False
        with db.session() as session:
            row = session.get(RuntimeSetting, "model_languages")
            if row:
                saved = json.loads(cipher.decrypt(row.value))
                if saved.get("model_version") == settings.model_version:
                    self.tags, self.discovered = set(saved["tags"]), saved["discovered"]

    def update(self, health):
        reported = health.get("languages")
        if reported is None:
            reported, discovered = [self.settings.lang_tag], False
        else:
            discovered = True
        if not isinstance(reported, list) or not reported:
            raise ServiceError(502, "Colab returned an invalid language list")
        if not all(isinstance(tag, str) and re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,3})?", tag) for tag in reported):
            raise ServiceError(502, "Colab returned an invalid language list")
        tags = set(reported)
        if tags == self.tags and self.discovered == discovered:
            return
        self.tags, self.discovered = tags, discovered
        data = {"tags": sorted(tags), "model_version": self.settings.model_version, "discovered": discovered}
        with self.db.session.begin() as session:
            session.merge(RuntimeSetting(key="model_languages", value=self.cipher.encrypt(json.dumps(data).encode())))

    def mapping(self):
        aliases = {key: value for key, value in self.settings.language_aliases.items() if value in self.tags}
        used = set(aliases.values())
        return {**{tag: tag for tag in self.tags if tag not in used}, **aliases}

    def catalog(self):
        mapping = self.mapping()
        codes = sorted(mapping, key=lambda code: (code != "ur", LABELS.get(code, code)))
        return {"default": "ur" if "ur" in mapping else codes[0], "discovered": self.discovered,
                "items": [{"code": code, "model_tag": mapping[code], "name": LABELS.get(code, code.upper())} for code in codes]}

    async def resolve(self, code, gpu):
        if code not in self.mapping():
            self.update(await gpu.health())
        if code not in self.mapping():
            raise ServiceError(422, "Language is not advertised by this model; update the notebook and check its configuration")
        return self.mapping()[code]


def preserve_text(text):
    normalized = unicodedata.normalize("NFC", text)
    return "".join(c for c in normalized if not unicodedata.category(c).startswith("C") or c in "\n\t").strip()
