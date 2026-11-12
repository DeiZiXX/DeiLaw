"""Optional local UГИБДД charter support for DeiLaw.

The module intentionally uses only the Python standard library so that the
optional DOCX can be read without adding python-docx to the application.
"""

from __future__ import annotations

import re
import sys
import socket
import ipaddress
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _WORD_NS}
MAX_CHARTER_DOWNLOAD = 8 * 1024 * 1024
MAX_CHARTER_XML = 3 * 1024 * 1024
MAX_CHARTER_UNPACKED = 24 * 1024 * 1024
MAX_CHARTER_ZIP_MEMBERS = 300


def _safe_docx_member(archive: zipfile.ZipFile, name: str) -> bytes:
    members = archive.infolist()
    if len(members) > MAX_CHARTER_ZIP_MEMBERS:
        raise ValueError("Слишком много файлов внутри DOCX.")
    if sum(item.file_size for item in members) > MAX_CHARTER_UNPACKED:
        raise ValueError("Слишком большой распакованный DOCX.")
    for item in members:
        if item.flag_bits & 0x1 or item.file_size > MAX_CHARTER_UNPACKED:
            raise ValueError("DOCX содержит запрещённый ZIP-элемент.")
        if item.filename.startswith("/") or ".." in item.filename.split("/"):
            raise ValueError("DOCX содержит небезопасный путь файла.")
        if item.file_size > 10240 and item.file_size > max(1, item.compress_size) * 150:
            raise ValueError("DOCX содержит подозрительное сжатие.")
    info = archive.getinfo(name)
    if info.file_size > MAX_CHARTER_XML or (
        info.file_size > 10000 and
        info.file_size > max(1, info.compress_size) * 150
    ):
        raise ValueError("DOCX содержит подозрительно большой или сжатый XML.")
    data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DOCX содержит небезопасные XML-сущности.")
    return data


def _q(name: str) -> str:
    return f"{{{_WORD_NS}}}{name}"


def application_directory() -> Path:
    """Directory that the user sees as 'next to the program'."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_gibdd_charter(base_dir: Optional[Path] = None) -> Optional[Path]:
    """Find an optional UГИБДД/GИБДД charter DOCX next to the application."""
    base = Path(base_dir) if base_dir is not None else application_directory()
    if not base.exists():
        return None

    preferred = [
        "gibdd_charter.docx",
        "ugibdd_charter.docx",
        "ustav_gibdd.docx",
        "ustav_ugibdd.docx",
        "УСТАВ УГИБДД.docx",
        "УСТАВ ГИБДД.docx",
    ]
    for name in preferred:
        candidate = base / name
        if candidate.is_file():
            return candidate

    try:
        candidates = sorted(base.glob("*.docx"))
    except OSError:
        return None

    for path in candidates:
        stem = path.stem.lower().replace("ё", "е")
        normalized = re.sub(r"[\s_\-]+", " ", stem)
        if "устав" in normalized and ("угибдд" in normalized or "гибдд" in normalized):
            return path

    return None


def normalize_charter_url(url: str) -> str:
    """Require HTTPS to a public DNS hostname; do not accept credentials or IP literals.

    Redirect targets are checked independently by _fetch_public_charter().
    """
    value = str(url or "").strip()
    if not value:
        raise ValueError("Введите ссылку на Устав.")
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Некорректная ссылка на Устав.") from exc
    if (parsed.scheme.lower() != "https" or not host or
            parsed.username is not None or parsed.password is not None or
            port not in (None, 443) or "\\" in value or
            host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
        raise ValueError("Разрешены только публичные HTTPS-ссылки без учётных данных.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Ссылки на IP-адреса запрещены.")
    return value


def _validate_public_dns(url: str) -> None:
    """Reject local/private DNS targets before performing HTTP requests.

    This is defense in depth, not DNS pinning: the host must still be
    treated as untrusted when resolving redirects and in proxy environments.
    """
    host = urlparse(url).hostname
    if not host:
        raise ValueError("У ссылки отсутствует доменное имя.")
    try:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Не удалось проверить адрес сервера.") from exc
    addresses = [item[4][0] for item in records]
    if not addresses or any(not ipaddress.ip_address(item).is_global for item in addresses):
        raise ValueError("Ссылка ведёт на локальный или служебный адрес.")


def _fetch_public_charter(url: str, headers: dict) -> tuple[bytes, str, str]:
    """Bound decoded download bytes and validate every HTTP redirect."""
    current = normalize_charter_url(url)
    for _ in range(5):
        _validate_public_dns(current)
        try:
            with requests.get(current, headers=headers, timeout=(10, 30),
                              stream=True, allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Переадресация без адреса назначения.")
                    current = normalize_charter_url(urljoin(current, location))
                    continue
                response.raise_for_status()
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > MAX_CHARTER_DOWNLOAD:
                    raise ValueError("Слишком большой файл Устава (максимум 8 МБ).")
                result = bytearray()
                for part in response.iter_content(chunk_size=64 * 1024):
                    if not part:
                        continue
                    if len(result) + len(part) > MAX_CHARTER_DOWNLOAD:
                        raise ValueError("Слишком большой файл Устава (максимум 8 МБ).")
                    result.extend(part)
                encoding = response.encoding or "utf-8"
                return bytes(result), response.headers.get("Content-Type", ""), encoding
        except requests.RequestException as exc:
            raise ValueError("Не удалось загрузить Устав по защищённому соединению.") from exc
    raise ValueError("Слишком много перенаправлений при загрузке Устава.")


def google_docs_export_url(url: str) -> Optional[str]:
    """Convert a normal Google Docs sharing URL to a DOCX export URL."""
    normalized = normalize_charter_url(url)
    parsed = urlparse(normalized)
    host = parsed.netloc.lower()
    if host != "docs.google.com":
        return None

    match = re.search(r"/document/(?:u/\d+/)?d/([A-Za-z0-9_-]+)", parsed.path)
    if not match:
        return None

    document_id = match.group(1)
    return (
        "https://docs.google.com/document/d/"
        f"{document_id}/export?format=docx"
    )


def _looks_like_docx(data: bytes, content_type: str = "") -> bool:
    if "wordprocessingml.document" in str(content_type or "").lower():
        return True
    if not data.startswith(b"PK"):
        return False
    try:
        from io import BytesIO
        with zipfile.ZipFile(BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except Exception:
        return False


def _html_charter_text(html: str) -> str:
    """Extract the most charter-like text block from a forum/web page."""
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    candidates = []
    selectors = (
        ".bbWrapper",
        ".message-body",
        ".message-content",
        ".article-body",
        "article",
        "main",
    )
    for selector in selectors:
        try:
            candidates.extend(soup.select(selector))
        except Exception:
            pass

    if soup.body is not None:
        candidates.append(soup.body)

    def score(node):
        text = node.get_text("\n", strip=True)
        lower = text.lower()
        return (
            lower.count("статья") * 500
            + lower.count("глава") * 800
            + min(len(text), 200000)
        )

    if not candidates:
        return soup.get_text("\n", strip=True)

    best = max(candidates, key=score)
    return best.get_text("\n", strip=True)


def download_gibdd_charter_url(
    url: str,
    cache_dir: Path,
) -> tuple["CharterDocument", Path, str]:
    """Download and parse a charter from Google Docs, DOCX URL or web/forum page.

    Returns:
        (parsed_document, local_cache_path, source_kind)
    """
    source_url = normalize_charter_url(url)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    google_export = google_docs_export_url(source_url)
    request_url = google_export or source_url
    headers = {
        "User-Agent": "DeiLaw/0.2.0c (+https://github.com/DeiZiXX/DeiLaw)",
        "Accept": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
        ),
    }

    data, content_type, content_encoding = _fetch_public_charter(request_url, headers)
    parser = GibddCharterParser()

    # Google Docs export and direct DOCX links.
    if _looks_like_docx(data, content_type):
        cache_path = cache_dir / "remote_charter.docx"
        temp_path = cache_dir / "remote_charter.docx.part"
        temp_path.write_bytes(data)

        try:
            document = parser.parse(temp_path)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            if google_export:
                raise ValueError(
                    "Google Документ загрузился, но DeiLaw не смог прочитать "
                    "его как Устав. Убедитесь, что доступ по ссылке открыт "
                    "и документ содержит главы и статьи."
                ) from exc
            raise ValueError(
                "Файл по ссылке похож на DOCX, но не содержит распознаваемый Устав."
            ) from exc

        if cache_path.exists():
            cache_path.unlink()
        temp_path.replace(cache_path)
        document.path = cache_path

        kind = "google_docs" if google_export else "docx_url"
        return document, cache_path, kind

    # Ordinary web/forum page.
    try:
        html = data.decode(content_encoding, errors="replace")
    except Exception as exc:
        raise ValueError(
            "Ссылка не является DOCX и страницу не удалось прочитать как текст."
        ) from exc

    page_text = _html_charter_text(html)
    if not page_text.strip():
        raise ValueError("На странице по ссылке не найден читаемый текст Устава.")

    cache_path = cache_dir / "remote_charter.txt"
    temp_path = cache_dir / "remote_charter.txt.part"
    temp_path.write_text(page_text, encoding="utf-8")

    try:
        document = parser.parse_text(page_text, path=temp_path)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise ValueError(
            "Страница открылась, но DeiLaw не нашёл на ней структуру "
            "«Глава N.» / «Статья N.». Для форума укажите ссылку прямо "
            "на страницу с текстом Устава."
        ) from exc

    if cache_path.exists():
        cache_path.unlink()
    temp_path.replace(cache_path)
    document.path = cache_path
    return document, cache_path, "web_page"


@dataclass
class CharterArticle:
    number: str
    title: str
    content: str
    chapter_number: str
    chapter_title: str


@dataclass
class CharterChapter:
    number: str
    title: str
    articles: list[CharterArticle] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        return f"Глава {self.number}. {self.title}".strip()


@dataclass
class CharterDocument:
    path: Path
    title: str
    subtitle: str
    approval: str
    amendment: str
    chapters: list[CharterChapter]

    @property
    def articles(self) -> list[CharterArticle]:
        result: list[CharterArticle] = []
        for chapter in self.chapters:
            result.extend(chapter.articles)
        return result


class GibddCharterParser:
    CHAPTER_RE = re.compile(r"^Глава\s+(?P<num>\d+(?:\.\d+)*)\.?\s*(?P<title>.*)$", re.I)
    ARTICLE_RE = re.compile(r"^Статья\s+(?P<num>\d+(?:\.\d+)*)\.?\s*(?P<title>.*)$", re.I)

    def parse(self, path: Path) -> CharterDocument:
        path = Path(path)
        paragraphs = self._read_paragraphs(path)
        return self._document_from_paragraphs(paragraphs, path)

    def parse_text(
        self,
        text: str,
        path: Optional[Path] = None,
    ) -> CharterDocument:
        """Parse a charter copied/extracted from a web page."""
        paragraphs: list[str] = []
        for raw_line in str(text or "").replace("\r", "\n").split("\n"):
            line = re.sub(r"[ \t]+", " ", raw_line).strip()
            line = re.sub(r"^[•●▪◦]+\s*", "", line)
            if not line:
                continue

            # Web editors sometimes keep several structural headings inside
            # one visual block. Split only before explicit capitalized charter
            # headings to preserve ordinary article references in body text.
            pieces = re.split(
                r"(?=\b(?:Глава|Статья)\s+\d+(?:\.\d+)*\.?\s*)",
                line,
            )
            for piece in pieces:
                piece = piece.strip()
                if piece:
                    paragraphs.append(piece)

        return self._document_from_paragraphs(
            paragraphs,
            Path(path) if path is not None else Path("remote_charter.txt"),
        )

    def _document_from_paragraphs(
        self,
        paragraphs: list[str],
        path: Path,
    ) -> CharterDocument:
        if not paragraphs:
            raise ValueError("Документ Устава пуст или не содержит читаемого текста.")

        title, subtitle, approval, amendment = self._document_metadata(paragraphs)
        chapters = self._build_outline(paragraphs)
        if not chapters:
            raise ValueError("В документе не найдены главы вида «Глава N.».")

        return CharterDocument(
            path=Path(path),
            title=title,
            subtitle=subtitle,
            approval=approval,
            amendment=amendment,
            chapters=chapters,
        )

    def _read_paragraphs(self, path: Path) -> list[str]:
        if Path(path).stat().st_size > MAX_CHARTER_DOWNLOAD:
            raise ValueError("Файл Устава слишком большой (максимум 8 МБ).")
        with zipfile.ZipFile(path) as archive:
            document_root = ET.fromstring(_safe_docx_member(archive, "word/document.xml"))
            numbering_root = None
            try:
                numbering_root = ET.fromstring(_safe_docx_member(archive, "word/numbering.xml"))
            except KeyError:
                pass

        numbering = self._read_numbering(numbering_root) if numbering_root is not None else {}
        counters: dict[tuple[str, int], int] = {}
        paragraphs: list[str] = []

        for paragraph in document_root.findall(".//w:body/w:p", _NS):
            text = self._paragraph_text(paragraph)
            if not text:
                continue

            prefix = self._number_prefix(paragraph, numbering, counters)
            if prefix:
                text = f"{prefix} {text}"

            text = re.sub(r"[ \t]+", " ", text).strip()
            if text:
                paragraphs.append(text)

        return paragraphs

    @staticmethod
    def _paragraph_text(paragraph: ET.Element) -> str:
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == _q("t"):
                parts.append(node.text or "")
            elif node.tag == _q("tab"):
                parts.append("\t")
            elif node.tag in (_q("br"), _q("cr")):
                parts.append("\n")
        return "".join(parts).strip()

    @staticmethod
    def _read_numbering(root: ET.Element) -> dict[str, dict[int, tuple[int, str, str]]]:
        abstract_by_id: dict[str, dict[int, tuple[int, str, str]]] = {}
        for abstract in root.findall("w:abstractNum", _NS):
            abstract_id = abstract.get(_q("abstractNumId"), "")
            levels: dict[int, tuple[int, str, str]] = {}
            for level in abstract.findall("w:lvl", _NS):
                ilvl = int(level.get(_q("ilvl"), "0"))
                start_el = level.find("w:start", _NS)
                fmt_el = level.find("w:numFmt", _NS)
                text_el = level.find("w:lvlText", _NS)
                start = int(start_el.get(_q("val"), "1")) if start_el is not None else 1
                fmt = fmt_el.get(_q("val"), "decimal") if fmt_el is not None else "decimal"
                pattern = text_el.get(_q("val"), f"%{ilvl + 1}.") if text_el is not None else f"%{ilvl + 1}."
                levels[ilvl] = (start, fmt, pattern)
            abstract_by_id[abstract_id] = levels

        result: dict[str, dict[int, tuple[int, str, str]]] = {}
        for num in root.findall("w:num", _NS):
            num_id = num.get(_q("numId"), "")
            abstract_el = num.find("w:abstractNumId", _NS)
            if abstract_el is None:
                continue
            abstract_id = abstract_el.get(_q("val"), "")
            result[num_id] = abstract_by_id.get(abstract_id, {})
        return result

    def _number_prefix(
        self,
        paragraph: ET.Element,
        numbering: dict[str, dict[int, tuple[int, str, str]]],
        counters: dict[tuple[str, int], int],
    ) -> str:
        num_pr = paragraph.find("./w:pPr/w:numPr", _NS)
        if num_pr is None:
            return ""

        num_id_el = num_pr.find("w:numId", _NS)
        level_el = num_pr.find("w:ilvl", _NS)
        if num_id_el is None:
            return ""

        num_id = num_id_el.get(_q("val"), "")
        level = int(level_el.get(_q("val"), "0")) if level_el is not None else 0
        definition = numbering.get(num_id, {}).get(level)
        if definition is None:
            definition = (1, "decimal", f"%{level + 1}.")

        start, fmt, pattern = definition
        key = (num_id, level)
        value = counters.get(key, start - 1) + 1
        counters[key] = value

        # Reset deeper levels when a parent item advances.
        for other_key in list(counters):
            if other_key[0] == num_id and other_key[1] > level:
                counters.pop(other_key, None)

        rendered = self._format_number(value, fmt)
        token = f"%{level + 1}"
        if token in pattern:
            return pattern.replace(token, rendered)
        return f"{rendered}."

    @staticmethod
    def _format_number(value: int, fmt: str) -> str:
        if fmt == "lowerLetter":
            return GibddCharterParser._alpha(value).lower()
        if fmt == "upperLetter":
            return GibddCharterParser._alpha(value).upper()
        if fmt == "lowerRoman":
            return GibddCharterParser._roman(value).lower()
        if fmt == "upperRoman":
            return GibddCharterParser._roman(value).upper()
        return str(value)

    @staticmethod
    def _alpha(value: int) -> str:
        result = ""
        value = max(1, value)
        while value:
            value, rem = divmod(value - 1, 26)
            result = chr(ord("A") + rem) + result
        return result

    @staticmethod
    def _roman(value: int) -> str:
        pairs = [
            (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
        ]
        result = ""
        for number, glyph in pairs:
            while value >= number:
                result += glyph
                value -= number
        return result or "I"

    @staticmethod
    def _document_metadata(paragraphs: list[str]) -> tuple[str, str, str, str]:
        chapter_index = next(
            (i for i, text in enumerate(paragraphs) if re.match(r"^Глава\s+\d+", text, re.I)),
            len(paragraphs),
        )
        front = paragraphs[:chapter_index]
        title = "Устав"
        subtitle = "Подключённый Устав"
        approval = ""
        amendment = ""

        if "ВНУТРЕННИЙ УСТАВ" in front:
            idx = front.index("ВНУТРЕННИЙ УСТАВ")
            title = "Устав"
            if idx + 1 < len(front):
                subtitle = front[idx + 1]

        joined = "\n".join(front)
        approval_match = re.search(
            r"Утвержден Постановлением\s*\n([^\n]+)\s*\n(от\s+[^\n]+)",
            joined,
            re.I,
        )
        if approval_match:
            approval = f"Утвержден: {approval_match.group(1)} {approval_match.group(2)}"

        amendment_match = re.search(
            r"С изменениями[^\n]*\s*\n([^\n]+)\s*\n(от\s+[^\n]+)",
            joined,
            re.I,
        )
        if amendment_match:
            amendment = f"Изменения: {amendment_match.group(1)} {amendment_match.group(2)}"

        return title, subtitle, approval, amendment

    def _build_outline(self, paragraphs: list[str]) -> list[CharterChapter]:
        chapters: list[CharterChapter] = []
        current_chapter: Optional[CharterChapter] = None
        current_article: Optional[CharterArticle] = None
        article_lines: list[str] = []

        def flush_article() -> None:
            nonlocal current_article, article_lines
            if current_article is None:
                return
            current_article.content = "\n\n".join(line for line in article_lines if line.strip()).strip()
            article_lines = []
            if current_chapter is not None:
                current_chapter.articles.append(current_article)
            current_article = None

        for text in paragraphs:
            chapter_match = self.CHAPTER_RE.match(text)
            if chapter_match:
                flush_article()
                current_chapter = CharterChapter(
                    number=chapter_match.group("num"),
                    title=chapter_match.group("title").strip(" ."),
                )
                chapters.append(current_chapter)
                continue

            article_match = self.ARTICLE_RE.match(text)
            if article_match:
                flush_article()
                if current_chapter is None:
                    # Ignore preamble articles if a malformed document places one
                    # before a chapter; the UI is intentionally chapter-based.
                    continue
                current_article = CharterArticle(
                    number=article_match.group("num"),
                    title=article_match.group("title").strip(" ."),
                    content="",
                    chapter_number=current_chapter.number,
                    chapter_title=current_chapter.title,
                )
                continue

            if current_article is not None:
                article_lines.append(text)

        flush_article()
        return [chapter for chapter in chapters if chapter.articles]
