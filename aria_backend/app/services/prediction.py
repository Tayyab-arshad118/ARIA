"""In-memory backoff trigram model. Prediction never acquires the synthesis lock."""
import asyncio
from collections import Counter, defaultdict
import re

from sqlalchemy import delete, select

from ..db import Phrase, SpokenHistory

WORDS = re.compile(r"[a-z]+(?:'[a-z]+)?|[0-9]+")


def build_index(corpus):
    counts = defaultdict(Counter)
    for text, weight in corpus:
        tokens = WORDS.findall(text.lower())[:128]
        for i, word in enumerate(tokens):
            if len(word) > 40:
                continue
            for length in range(min(i, 2) + 1):
                context = tuple(tokens[i - length:i]) if length else ()
                counts[context][word] += weight
    index = {}
    for context, counter in counts.items():
        # Visit highest-scoring candidates first; retain only five per character prefix.
        for word, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            for size in range(len(word) + 1):
                key = (context, word[:size])
                options = index.setdefault(key, [])
                if len(options) < 5:
                    options.append(word)
    return {key: tuple(values) for key, values in index.items()}


class Predictor:
    def __init__(self, settings, db, cipher):
        self.settings, self.db, self.cipher = settings, db, cipher
        self.index = {}

    async def rebuild(self):
        import json
        with self.db.session() as session:
            corpus = [(json.loads(self.cipher.decrypt(p.content))["roman"], 1)
                      for p in session.scalars(select(Phrase))]
            corpus.extend((self.cipher.decrypt(h.text).decode(), 2)
                          for h in session.scalars(select(SpokenHistory).order_by(SpokenHistory.id.desc())
                                                  .limit(self.settings.prediction_history_limit)))
        # Readers keep the previous immutable snapshot while a replacement is built off-thread.
        self.index = await asyncio.to_thread(build_index, corpus)

    def suggest(self, prefix):
        if any("\u0600" <= c <= "\u06ff" for c in prefix):
            return []  # Do not mix Roman suggestions into Urdu-script input.
        tokens = WORDS.findall(prefix.lower())
        continuing = bool(prefix and re.search(r"[a-z0-9']$", prefix, re.I))
        partial = tokens.pop() if tokens and continuing else ""
        result, snapshot = [], self.index
        for size in range(min(len(tokens), 2), -1, -1):
            context = tuple(tokens[-size:]) if size else ()
            for word in snapshot.get((context, partial), ()):
                if word not in result:
                    result.append(word)
                if len(result) == 5:
                    return result
        return result

    async def record(self, text, voice_id):
        with self.db.session.begin() as session:
            session.add(SpokenHistory(voice_id=voice_id, text=self.cipher.encrypt(text.encode())))
            session.flush()
            stale = list(session.scalars(select(SpokenHistory.id).order_by(SpokenHistory.id.desc())
                                        .offset(self.settings.prediction_history_limit)))
            if stale:
                session.execute(delete(SpokenHistory).where(SpokenHistory.id.in_(stale)))
        await self.rebuild()
