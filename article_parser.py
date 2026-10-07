import re


class ArticleParser:
    # Standard article header:
    #   Статья 63.
    #   Статья 63.1. Название
    #   Статья 12-1. Название
    ARTICLE_PATTERN = re.compile(
        r"^\s*Статья\s+"
        r"(?P<number>\d+(?:[-.]\d+)*)"
        r"\.?\s*"
        r"(?P<title>.*)$",
        re.IGNORECASE,
    )

    # Some RMRP documents place subarticles inside the parent article without
    # repeating the word "Статья":
    #   63.1.
    #   Незаконное приобретение...
    #
    # Only dotted/hyphenated numbers are accepted here. A plain "1." is usually
    # a paragraph/part of an article and must NOT become a separate article.
    SUBARTICLE_PATTERN = re.compile(
        r"^\s*"
        r"(?P<number>\d+(?:[.-]\d+)+)"
        r"\.\s*"
        r"(?P<title>.*)$",
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_number(number: str) -> str:
        number = re.sub(r"\s+", "", number or "")
        return number.rstrip(".")

    def parse(self, content: str):
        """
        Разбивает текст закона на отдельные статьи.

        Поддерживает:
        - "Статья 63."
        - "Статья 63.1."
        - вложенные заголовки вида "63.1." без слова "Статья"
        - номера через дефис, например "12-1"

        Обычные пункты "1.", "2.", "3." отдельными статьями не считаются.
        """

        lines = [
            line.strip()
            for line in content.splitlines()
            if line.strip()
        ]

        candidates = []

        for index, line in enumerate(lines):
            match = self.ARTICLE_PATTERN.match(line)

            if match:
                candidates.append({
                    "index": index,
                    "number": self._normalize_number(match.group("number")),
                    "title": match.group("title").strip(),
                })
                continue

            # Important fix for documents where 63.1 / 63.2 etc. are written
            # inside article 63 without the "Статья" prefix.
            match = self.SUBARTICLE_PATTERN.match(line)

            if match:
                candidates.append({
                    "index": index,
                    "number": self._normalize_number(match.group("number")),
                    "title": match.group("title").strip(),
                })

        articles = []

        for position, candidate in enumerate(candidates):
            start = candidate["index"] + 1

            if position + 1 < len(candidates):
                end = candidates[position + 1]["index"]
            else:
                end = len(lines)

            body_lines = lines[start:end]
            body = "\n".join(body_lines).strip()

            # Entries from a table of contents generally have no meaningful body.
            if len(body) < 15:
                continue

            title = candidate["title"]

            # Often a bare "63.1." header is followed by the actual title on
            # the next line. Keep the body intact, but use that first line as
            # the display title when it looks like text rather than a numbered
            # paragraph.
            if not title and body_lines:
                first = body_lines[0].strip()
                if (
                    first
                    and len(first) <= 300
                    and not re.match(r"^\d+\.\s", first)
                ):
                    title = first

            articles.append({
                "number": candidate["number"],
                "title": title,
                "content": body,
            })

        # The same article may occur in a contents section and later in full.
        # Keep the most substantial version.
        unique = {}

        for article in articles:
            number = article["number"]
            existing = unique.get(number)

            if (
                existing is None
                or len(article["content"]) > len(existing["content"])
            ):
                unique[number] = article

        return list(unique.values())
