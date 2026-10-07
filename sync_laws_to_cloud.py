from __future__ import annotations

import getpass
import sqlite3
import sys
import uuid
from pathlib import Path

import requests

from community_client import SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL


def find_root() -> Path:
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    if len(sys.argv) > 1:
        candidates.insert(0, Path(sys.argv[1]).expanduser())
    for root in candidates:
        root = root.resolve()
        if (root / "data" / "laws.db").exists() and (root / "community_client.py").exists():
            return root
    raise RuntimeError(
        "Не найден data/laws.db. Запустите скрипт из корня DeiLaw или перетащите папку DeiLaw на sync_laws_to_cloud.bat."
    )


def read_masked_password(prompt: str) -> str:
    """Read a password on Windows while showing * for each typed character."""
    if sys.platform != "win32":
        return getpass.getpass(prompt)

    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars = []

    while True:
        ch = msvcrt.getwch()

        # Enter
        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(chars)

        # Ctrl+C
        if ch == "\x03":
            raise KeyboardInterrupt

        # Backspace
        if ch == "\x08":
            if chars:
                chars.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue

        # Ignore special-key prefix and its scan code.
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue

        chars.append(ch)
        sys.stdout.write("*")
        sys.stdout.flush()

def auth(email: str, password: str) -> str:
    response = requests.post(
        f"{SUPABASE_URL.rstrip('/')}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": SUPABASE_PUBLISHABLE_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=25,
    )
    if not response.ok:
        raise RuntimeError("Не удалось войти в Supabase. Проверьте email/пароль администратора.")
    token = str((response.json() or {}).get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Supabase не вернул access_token.")
    return token


def post_sync(token: str, payload: dict) -> dict:
    response = requests.post(
        f"{SUPABASE_URL.rstrip('/')}/functions/v1/deilaw-law-sync",
        headers={
            "apikey": SUPABASE_PUBLISHABLE_KEY,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=90,
    )
    try:
        data = response.json()
    except Exception:
        data = {}
    if not response.ok:
        raise RuntimeError(str(data.get("error") or response.text or f"HTTP {response.status_code}"))
    return data if isinstance(data, dict) else {}


def read_database(db_path: Path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        laws = con.execute(
            "SELECT id, title, url, content, updated_at FROM laws ORDER BY title"
        ).fetchall()
        result = []
        for law in laws:
            articles = con.execute(
                """
                SELECT article_number, title, content
                FROM articles
                WHERE law_id = ?
                ORDER BY article_number
                """,
                (law["id"],),
            ).fetchall()
            result.append(
                {
                    "title": law["title"],
                    "url": law["url"],
                    "content": law["content"],
                    "updated_at": law["updated_at"],
                    "articles": [
                        {
                            "article_number": row["article_number"],
                            "article_title": row["title"],
                            "content": row["content"],
                        }
                        for row in articles
                    ],
                }
            )
        return result
    finally:
        con.close()


def main() -> int:
    root = find_root()
    laws = read_database(root / "data" / "laws.db")
    article_count = sum(len(x["articles"]) for x in laws)
    if not laws or not article_count:
        raise RuntimeError(
            "Локальная база законов пустая. Сначала обновите законодательство в DeiLaw."
        )

    print(f"Найдено законов: {len(laws)}; статей: {article_count}")
    email = input("Email администратора Supabase: ").strip()
    password = read_masked_password("Пароль администратора Supabase: ")
    token = auth(email, password)

    sync_token = str(uuid.uuid4())
    uploaded_articles = 0
    for index, law in enumerate(laws, 1):
        data = post_sync(
            token,
            {"action": "upsert_law", "sync_token": sync_token, "law": law},
        )
        count = int(data.get("articles") or 0)
        uploaded_articles += count
        print(f"[{index}/{len(laws)}] {law['title']} — {count} статей")

    finish = post_sync(token, {"action": "finish", "sync_token": sync_token})
    stats = finish.get("stats") or {}
    print()
    print("Синхронизация завершена.")
    print(f"На сервере законов: {stats.get('laws', len(laws))}")
    print(f"На сервере статей: {stats.get('articles', uploaded_articles)}")
    print("Теперь Cloud AI имеет прямой доступ к серверной законке.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print()
        print(f"ОШИБКА: {exc}")
        raise SystemExit(1)
