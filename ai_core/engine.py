from __future__ import annotations

import re

from .cloud import CloudAIClient
from .grounding import GroundingValidator


class DeiLawAIEngine:
    """Cloud AI engine with server-side access to the complete RMRP law corpus."""

    MODE_ARTICLE = "article_lookup"
    MODE_QUALIFICATION = "qualification"
    MODE_AUTHORITY = "authority"
    MODE_GENERAL = "general"

    ARTICLE_REF_RE = re.compile(
        r"(?:ст(?:атья)?\.?\s*)?(\d+(?:[.,]\d+)*)\s*(ук|коап)(?:\s*рф)?\b",
        re.I,
    )
    ARTICLE_REF_RE_REVERSED = re.compile(
        r"\b(ук|коап)(?:\s*рф)?\s*(?:ст(?:атья)?\.?\s*)?(\d+(?:[.,]\d+)*)",
        re.I,
    )

    def __init__(self, *args, **kwargs):
        self.assistant = CloudAIClient()

    @classmethod
    def _exact_article_refs(cls, query: str) -> list[dict]:
        text = str(query or "").lower().replace("ё", "е")
        refs: list[dict] = []
        for match in cls.ARTICLE_REF_RE.finditer(text):
            article = match.group(1).replace(",", ".")
            code = match.group(2).lower()
            item = {"code": code, "article": article}
            if item not in refs:
                refs.append(item)
        for match in cls.ARTICLE_REF_RE_REVERSED.finditer(text):
            code = match.group(1).lower()
            article = match.group(2).replace(",", ".")
            item = {"code": code, "article": article}
            if item not in refs:
                refs.append(item)
        return refs[:8]

    @staticmethod
    def _authority_question(query: str) -> bool:
        q = " ".join(str(query or "").lower().replace("ё", "е").split())
        markers = (
            "на каком основании", "по какому основанию", "какое основание",
            "имеет право", "вправе", "обязан", "обязана", "должен",
            "законное требование", "может потребовать", "может требовать",
            "почему должен", "почему обязан", "основание для",
            "предъявить документы", "передать документы", "показать документы",
            "остановить машину", "останавливать машину", "остановить автомобиль",
            "покинуть машину", "покинуть автомобиль", "выйти из машины",
            "выйти из автомобиля", "выйти из транспортного средства",
            "провести досмотр", "провести обыск", "задержать гражданина",
        )
        return any(x in q for x in markers)

    @staticmethod
    def _qualification_question(query: str) -> bool:
        q = " ".join(str(query or "").lower().replace("ё", "е").split())
        markers = (
            "что нарушил", "что человек нарушил", "что он нарушил",
            "какие нарушения", "какие статьи", "что ему вменить",
            "что вменить", "квалифиц", "привлечь", "ответственност",
            "какие статьи нарушил", "по каким статьям", "что нарушает",
        )
        return any(x in q for x in markers)

    @classmethod
    def _query_mode(cls, query: str) -> str:
        if cls._exact_article_refs(query):
            return cls.MODE_ARTICLE
        if cls._authority_question(query):
            return cls.MODE_AUTHORITY
        if cls._qualification_question(query):
            return cls.MODE_QUALIFICATION
        return cls.MODE_GENERAL

    def analyze(self, situation, articles=None, history=None, progress=None):
        # `articles` remains in the method signature so the existing AIWorker/UI
        # needs no invasive changes. Local articles are intentionally ignored.
        mode = self._query_mode(situation)
        exact_refs = self._exact_article_refs(situation)

        if progress:
            if mode == self.MODE_ARTICLE and exact_refs:
                refs = ", ".join(
                    f"{x['article']} {x['code'].upper()}" for x in exact_refs
                )
                progress(f"Cloud AI: ищем {refs} в серверной законке…")
            else:
                progress("Cloud AI: анализируем вопрос и ищем нормы во всей серверной законке RMRP…")

        raw, sources = self.assistant.analyze(
            situation,
            history=history,
            query_mode=mode,
            exact_refs=exact_refs,
        )

        if progress:
            progress(f"Cloud AI: найдено источников — {len(sources)}; формируем юридический ответ…")

        validator = GroundingValidator(sources, mode=mode)
        payload = validator.parse_json(raw)
        payload = validator.validate(payload)
        return validator.render(payload), sources
