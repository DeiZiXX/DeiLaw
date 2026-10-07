import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class RMRPParser:
    """Loads legislation threads from the public RMRP laws forum.

    The public API used by the rest of DeiLaw is intentionally small:
      - get_laws() -> [{"title": ..., "url": ...}, ...]
      - get_law_content(url) -> {"title": ..., "url": ..., "content": ...}

    The parser targets XenForo markup, but includes fallback selectors so minor
    forum layout changes do not immediately break legislation updates.
    """

    BASE_URL = "https://forum.rmrp.ru"
    LAWS_URL = "https://forum.rmrp.ru/forums/laws/"

    def __init__(self, timeout=25):
        self.timeout = int(timeout)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36 DeiLaw/0.2.0c"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.6",
        })

    def _get_soup(self, url):
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    @staticmethod
    def _clean_text(value):
        value = (value or "").replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n[ \t]+", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()

    @staticmethod
    def _is_thread_url(href):
        if not href or "/threads/" not in href:
            return False
        href = href.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if href.endswith("/latest") or href.endswith("/unread"):
            return False
        return bool(re.search(r"/threads/[^/]+\.\d+$", href))

    def _extract_laws_from_page(self, soup):
        result = []
        seen = set()

        # Preferred XenForo structure: one structItem per thread.
        thread_items = soup.select(".structItem--thread")
        for item in thread_items:
            chosen = None
            for anchor in item.select(".structItem-title a[href]"):
                href = anchor.get("href", "")
                if self._is_thread_url(href):
                    chosen = anchor
                    break
            if chosen is None:
                continue

            title = self._clean_text(chosen.get_text(" ", strip=True))
            url = urljoin(self.BASE_URL, chosen.get("href", ""))
            if not title or not url or url in seen:
                continue
            seen.add(url)
            result.append({"title": title, "url": url})

        if result:
            return result

        # Fallback for minor theme/layout changes.
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if not self._is_thread_url(href):
                continue
            title = self._clean_text(anchor.get_text(" ", strip=True))
            if not title or re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", title):
                continue
            url = urljoin(self.BASE_URL, href)
            if url in seen:
                continue
            seen.add(url)
            result.append({"title": title, "url": url})

        return result

    def get_laws(self):
        """Return all legislation threads visible in the RMRP laws forum."""
        laws = []
        seen_urls = set()
        visited_pages = set()
        page_url = self.LAWS_URL

        # The section currently fits on one page, but following the XenForo
        # next-page link makes this safe if more laws are added later.
        for _ in range(20):
            if not page_url or page_url in visited_pages:
                break
            visited_pages.add(page_url)

            soup = self._get_soup(page_url)
            for law in self._extract_laws_from_page(soup):
                if law["url"] in seen_urls:
                    continue
                seen_urls.add(law["url"])
                laws.append(law)

            next_link = soup.select_one("a.pageNav-jump--next[href]")
            if next_link is None:
                break
            page_url = urljoin(self.BASE_URL, next_link.get("href", ""))

        return laws

    @staticmethod
    def _prepare_message_node(node):
        # Work on a detached mini-soup so we do not mutate the page used for
        # title extraction or fallback processing.
        fragment = BeautifulSoup(str(node), "html.parser")
        root = fragment.select_one(".bbWrapper") or fragment

        # Keep visual line breaks from the forum editor.
        for br in root.find_all("br"):
            br.replace_with("\n")

        # Remove non-legislation UI/embedded clutter if present.
        for unwanted in root.select(
            "script, style, .bbCodeBlock-expandLink, .js-unfurl-favicon, "
            ".contentRow-figure, .message-lastEdit, .bbCodeSpoiler-button"
        ):
            unwanted.decompose()

        return root

    def get_law_content(self, url):
        """Return the authoritative first post of a legislation thread."""
        soup = self._get_soup(url)

        title_node = soup.select_one("h1.p-title-value")
        if title_node is not None:
            # XenForo can place prefix labels inside the H1; remove them from a
            # copy before extracting the actual document title.
            title_copy = BeautifulSoup(str(title_node), "html.parser")
            for label in title_copy.select(".label, .labelLink"):
                label.decompose()
            title = self._clean_text(title_copy.get_text(" ", strip=True))
        else:
            title = ""

        # For RMRP legislation the first post is the maintained source text.
        # Using only the first post prevents later discussion/replies from being
        # indexed as part of the law.
        node = soup.select_one("article.message--post .message-body .bbWrapper")
        if node is None:
            node = soup.select_one(".message-body .bbWrapper")
        if node is None:
            node = soup.select_one(".bbWrapper")

        if node is None:
            raise RuntimeError("Не найден текст первого сообщения закона на форуме RMRP.")

        root = self._prepare_message_node(node)
        content = self._clean_text(root.get_text("\n", strip=True))

        if not content:
            raise RuntimeError("Форум RMRP вернул пустой текст закона.")

        return {
            "title": title,
            "url": url,
            "content": content,
        }
