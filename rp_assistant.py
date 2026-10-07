import re


class RPAssistant:
    """Локальный анализатор RP-ситуаций по статьям из laws.db."""

    STOP_WORDS = {
        "и", "а", "но", "или", "что", "это", "как", "так", "в", "во", "на",
        "по", "за", "из", "от", "до", "для", "при", "с", "со", "к", "ко",
        "у", "о", "об", "про", "не", "ни", "же", "бы", "был", "была", "были",
        "есть", "его", "ее", "её", "их", "он", "она", "они", "ему", "ей",
        "после", "перед", "потом", "когда", "человек", "гражданин", "лицо"
    }

    SYNONYMS = {
        "оружие": {"оружие", "пистолет", "автомат", "винтовка", "ствол", "вооружен", "вооружён"},
        "задержание": {"задержание", "задержал", "задержали", "задержан", "задержать"},
        "обыск": {"обыск", "обыскал", "обыскали", "досмотр", "досмотрел", "досмотрели"},
        "побег": {"побег", "убежал", "убегал", "скрылся", "скрываться", "скрыться", "уехал", "уезжать"},
        "документы": {"документ", "документы", "паспорт", "удостоверение"},
        "транспорт": {"автомобиль", "машина", "транспорт", "тс", "водитель"},
        "требование": {"требование", "требования", "приказ", "распоряжение", "потребовал"},
        "сопротивление": {"сопротивление", "сопротивлялся", "сопротивляться", "неповиновение"},
        "угроза": {"угроза", "угрожал", "угрожать", "запугивание"},
        "нападение": {"нападение", "напал", "атаковал", "ударил", "избил"},
        "взятка": {"взятка", "подкуп", "вознаграждение"},
        "кража": {"кража", "украл", "похитил", "хищение"},
        "угон": {"угон", "угнал"},
        "адвокат": {"адвокат", "защитник", "защита"},
        "полиция": {"полиция", "полицейский", "сотрудник полиции"},
        "проникновение": {"проникновение", "проник", "вторжение"},
    }

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _normalize(text):
        return re.findall(r"[а-яa-z0-9]+", text.lower().replace("ё", "е"))

    def _query_terms(self, situation):
        normalized = " ".join(self._normalize(situation))
        terms = {
            word for word in self._normalize(situation)
            if len(word) >= 3 and word not in self.STOP_WORDS
        }

        for canonical, variants in self.SYNONYMS.items():
            normalized_variants = {v.replace("ё", "е") for v in variants}
            if any(v in normalized for v in normalized_variants):
                terms.add(canonical)
                terms.update(normalized_variants)

        return terms

    def get_all_articles(self):
        """Return every indexed RMRP article in the format used by SemanticSearch."""
        articles = []

        for law in self.database.get_laws():
            law_id = law["id"]
            law_title = law["title"] or ""
            law_url = law["url"] or ""

            for article in self.database.get_articles_by_law(law_id):
                articles.append({
                    "id": article["id"],
                    "law_id": law_id,
                    "law_title": law_title,
                    "url": law_url,
                    "article_number": article["article_number"],
                    "article_title": article["title"] or "",
                    "content": article["content"] or "",
                })

        return articles

    def analyze(self, situation, limit=25):
        terms = self._query_terms(situation)
        if not terms:
            return []

        results = []

        for law in self.database.get_laws():
            for article in self.database.get_articles_by_law(law["id"]):
                title = article["title"] or ""
                content = article["content"] or ""

                title_words = set(self._normalize(title))
                content_words = set(self._normalize(content))
                law_words = set(self._normalize(law["title"]))

                matched = []
                score = 0

                for term in terms:
                    term_n = term.lower().replace("ё", "е")

                    if term_n in title_words:
                        score += 6
                        matched.append(term)
                    elif term_n in law_words:
                        score += 3
                        matched.append(term)
                    elif term_n in content_words:
                        score += 2
                        matched.append(term)
                    elif len(term_n) >= 5:
                        stem = term_n[:5]
                        if any(word.startswith(stem) for word in title_words):
                            score += 4
                            matched.append(term)
                        elif any(word.startswith(stem) for word in content_words):
                            score += 1
                            matched.append(term)

                matched = list(dict.fromkeys(matched))
                if score < 3 or not matched:
                    continue

                results.append({
                    "law_id": law["id"],
                    "law_title": law["title"],
                    "url": law["url"],
                    "article_number": article["article_number"],
                    "article_title": title,
                    "content": content,
                    "score": score,
                    "matched_terms": matched,
                })

        results.sort(
            key=lambda item: (item["score"], len(item["matched_terms"])),
            reverse=True
        )
        return results[:limit]
