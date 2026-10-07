from __future__ import annotations

import re
from collections import Counter


class SemanticSearch:
    """Fast local lexical retrieval with no model and no external service.

    The class name is intentionally kept for backward compatibility with older
    DeiLaw code. It no longer uses embeddings or Ollama.
    """

    QUALIFICATION_MARKERS = (
        "кодекс об административных правонарушениях",
        "уголовный кодекс",
    )

    STOP_WORDS = {
        "и", "а", "но", "или", "что", "это", "как", "так", "в", "во", "на",
        "по", "за", "из", "от", "до", "для", "при", "с", "со", "к", "ко",
        "у", "о", "об", "про", "не", "ни", "же", "бы", "был", "была", "были",
        "есть", "его", "ее", "её", "их", "он", "она", "они", "ему", "ей",
        "после", "перед", "потом", "когда", "человек", "гражданин", "лицо",
        "можно", "нужно", "если", "ли", "то", "там", "тут", "меня", "мне",
    }

    SYNONYMS = {
        "оружие": {"оружие", "пистолет", "автомат", "винтовка", "ствол", "вооружен", "вооружён"},
        "побег": {"побег", "убежал", "убегал", "скрылся", "скрыться", "уехал"},
        "задержание": {"задержание", "задержал", "задержали", "задержан", "задержать"},
        "обыск": {"обыск", "обыскал", "досмотр", "досмотрел"},
        "неповиновение": {"неповиновение", "сопротивление", "сопротивлялся", "приказ"},
        "угроза": {"угроза", "угрожал", "угрожать", "запугивание"},
        "нападение": {"нападение", "напал", "атаковал", "ударил", "избил"},
        "взятка": {"взятка", "подкуп", "вознаграждение"},
        "кража": {"кража", "украл", "похитил", "хищение"},
        "угон": {"угон", "угнал"},
        "транспорт": {"машина", "автомобиль", "авто", "транспорт", "тс", "водитель"},
        "документы": {"документ", "документы", "паспорт", "удостоверение"},
        "дпс": {"дпс", "гибдд", "инспектор", "сотрудник"},
        # Critical for authority/basis questions around traffic stops.  Expanding
        # both directions lets "покинуть машину" match the formal wording
        # "выйти из транспортного средства" and vice versa.
        "выход": {
            "выйти", "выход", "выходить", "покинуть", "покидать", "покидании",
            "оставить", "высадиться", "транспортного", "средства", "машину",
            "автомобиль", "тс",
        },
        "требование": {
            "требование", "требовать", "потребовать", "потребовал", "требует",
            "распоряжение", "законное",
        },
        "обязанность": {"обязан", "обязана", "обязаны", "обязанность", "должен", "должна"},
        "основание": {"основание", "основании", "основания", "право", "вправе", "полномочие"},
    }

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join(
            re.findall(r"[а-яa-z0-9]+", str(text or "").lower().replace("ё", "е"))
        )

    @staticmethod
    def _words(text: str) -> list[str]:
        return re.findall(r"[а-яa-z0-9]+", str(text or "").lower().replace("ё", "е"))

    @classmethod
    def _query_terms(cls, text: str) -> list[str]:
        words = [w for w in cls._words(text) if len(w) >= 3 and w not in cls.STOP_WORDS]
        joined = " ".join(words)
        expanded = list(words)
        for canonical, variants in cls.SYNONYMS.items():
            normalized = {v.lower().replace("ё", "е") for v in variants}
            if any(v in joined for v in normalized):
                expanded.append(canonical)
                expanded.extend(normalized)
        return list(dict.fromkeys(expanded))

    @classmethod
    def _result_type(cls, law_title: str) -> str:
        title = str(law_title or "").lower().replace("ё", "е")
        return "qualification" if any(x in title for x in cls.QUALIFICATION_MARKERS) else "support"

    @classmethod
    def _authority_intent(cls, query: str) -> bool:
        q = cls._norm(query)
        signals = (
            "на каком основании", "какое основание", "по какому основанию",
            "имеет право", "вправе", "обязан", "обязана", "должен",
            "законное требование", "требование сотрудника", "может потребовать",
            "может требовать", "покинуть машину", "покинуть автомобиль",
            "покинуть транспортное средство", "выйти из машины",
            "выйти из автомобиля", "выйти из транспортного средства",
        )
        return any(x in q for x in signals)

    @classmethod
    def _exit_vehicle_intent(cls, query: str) -> bool:
        q = cls._norm(query)
        exit_words = ("выйти", "выход", "покинуть", "покидать", "высадиться")
        vehicle_words = ("машин", "автомоб", "транспорт", " тс ", "водител")
        padded = f" {q} "
        return any(x in q for x in exit_words) and any(x in padded for x in vehicle_words)


    @classmethod
    def _intent_priority(cls, query: str, article: dict) -> int:
        if not cls._exit_vehicle_intent(query):
            return 0
        law = cls._norm(article.get("law_title") or "")
        content = cls._norm(article.get("content") or "")
        title = cls._norm(article.get("article_title") or "")
        haystack = f"{title} {content}"
        has_exit = any(x in haystack for x in ("выйти", "покинуть", "покидании"))
        has_vehicle = any(x in haystack for x in ("транспортного средства", "транспортное средство", "водитель", " тс "))
        if not (has_exit and has_vehicle):
            return 0
        if "процессуальн" in law:
            return 3
        if "правила дорожного движения" in law or "пдд" in law:
            return 2
        return 1

    @classmethod
    def _intent_boost(cls, query: str, article: dict) -> tuple[float, list[str]]:
        """Domain-specific boost for direct legal-basis norms.

        This does not hard-code a result solely by article number.  It boosts an
        article only when the query expresses the matching intent AND the article
        itself contains the required legal wording.  This keeps the logic useful
        after document edits/re-numbering while still preferring the direct norm.
        """
        if not cls._exit_vehicle_intent(query):
            return 0.0, []

        law = cls._norm(article.get("law_title") or "")
        title = cls._norm(article.get("article_title") or "")
        content = cls._norm(article.get("content") or "")
        haystack = f"{title} {content}"

        boost = 0.0
        reasons: list[str] = []

        direct_patterns = (
            "выйти из транспортного средства",
            "покинуть транспортное средство",
            "покинуть тс",
            "водитель обязан выйти",
            "требование выйти",
            "требование о выходе",
            "выхода из транспортного средства",
        )
        if any(p in haystack for p in direct_patterns):
            boost += 46.0
            reasons.append("прямое требование о выходе из ТС")

        # Formal wording may be split by punctuation / subparagraph formatting.
        has_exit = any(x in haystack for x in ("выйти", "покинуть", "покидании"))
        has_vehicle = any(x in haystack for x in ("транспортного средства", "транспортное средство", "водитель", " тс "))
        has_duty = any(x in haystack for x in ("обязан", "требован", "вправе"))
        if has_exit and has_vehicle:
            boost += 24.0
            reasons.append("выход + транспортное средство")
        if has_exit and has_vehicle and has_duty:
            boost += 18.0
            reasons.append("прямая обязанность/полномочие")

        # For this question the Processual Code is the direct authority source;
        # PDD remains highly relevant as a driver's corresponding duty.
        if "процессуальн" in law and has_exit and has_vehicle:
            boost += 24.0
            reasons.append("процессуальная норма")
        elif ("правила дорожного движения" in law or "пдд" in law) and has_exit and has_vehicle:
            boost += 16.0
            reasons.append("обязанность водителя по ПДД")

        # A general stop-authority article mentioning only stopping a vehicle is
        # useful context but must not outrank a direct exit requirement.
        stop_only = (
            ("останов" in haystack or "остановки транспорт" in haystack)
            and not has_exit
        )
        if stop_only:
            boost -= 18.0

        return boost, reasons

    @classmethod
    def _score(cls, query: str, query_terms: list[str], article: dict) -> tuple[float, list[str]]:
        title_words = cls._words(article.get("article_title") or "")
        law_words = cls._words(article.get("law_title") or "")
        content_words = cls._words(article.get("content") or "")
        title_counts = Counter(title_words)
        law_counts = Counter(law_words)
        content_counts = Counter(content_words)

        score = 0.0
        matched: list[str] = []
        for term in query_terms:
            t = term.lower().replace("ё", "е")
            local = 0.0
            if title_counts[t]:
                local = 16.0
            elif law_counts[t]:
                local = 7.0
            elif content_counts[t]:
                local = min(8.0, 3.0 + content_counts[t] * 0.7)
            elif len(t) >= 5:
                stem = t[:5]
                if any(w.startswith(stem) for w in title_words):
                    local = 11.0
                elif any(w.startswith(stem) for w in content_words):
                    local = 3.5
            if local:
                score += local
                matched.append(term)

        intent_boost, intent_reasons = cls._intent_boost(query, article)
        score += intent_boost
        if intent_reasons:
            matched.extend(intent_reasons)

        if not matched or score <= 0:
            return 0.0, []

        # Prefer norms that match several independent facts in the situation.
        lexical_matches = [m for m in matched if m not in intent_reasons]
        unique = len(set(lexical_matches))
        score += min(22.0, unique * 3.2)

        # Qualification codes are generally useful, but for a pure authority /
        # legal-basis question they should not automatically outrank direct
        # procedural or traffic-rule authority.
        if cls._result_type(article.get("law_title", "")) == "qualification":
            score += 1.0 if cls._authority_intent(query) else 5.0

        return round(min(100.0, max(0.0, score)), 2), list(dict.fromkeys(matched))

    def search(self, query, articles, limit=14, progress=None):
        terms = self._query_terms(query)
        if not terms:
            return []
        if progress:
            progress("DeiLaw: локально подбираем нормы RMRP…")

        results = []
        for article in list(articles or []):
            score, matched = self._score(query, terms, article)
            if score < 7.0:
                continue
            row = dict(article)
            row["score"] = score
            row["matched_terms"] = matched
            row["result_type"] = self._result_type(row.get("law_title", ""))
            row["_intent_priority"] = self._intent_priority(query, row)
            results.append(row)

        results.sort(
            key=lambda x: (
                int(x.get("_intent_priority") or 0),
                float(x.get("score") or 0),
                len(x.get("matched_terms") or []),
            ),
            reverse=True,
        )
        return results[: max(1, int(limit))]
