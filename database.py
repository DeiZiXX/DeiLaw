import sqlite3
from pathlib import Path


DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "laws.db"


class LawDatabase:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)

        self.connection = sqlite3.connect(DB_PATH, timeout=20)
        self.connection.row_factory = sqlite3.Row

        # WAL is friendlier to the UI connection while UpdateWorker writes from
        # its own thread/connection.
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error:
            pass

        self.create_tables()

    # =========================================================
    # TABLES
    # =========================================================

    def create_tables(self):
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS laws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_id INTEGER NOT NULL,
                article_number TEXT NOT NULL,
                title TEXT,
                content TEXT NOT NULL,

                FOREIGN KEY (law_id)
                    REFERENCES laws(id)
                    ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_number
            ON articles(article_number)
        """)

        # One row per synchronization attempt. Existing databases are migrated
        # automatically because CREATE TABLE IF NOT EXISTS is non-destructive.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS update_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                successful INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                total_articles INTEGER NOT NULL DEFAULT 0,
                total_changes INTEGER NOT NULL DEFAULT 0,
                added_count INTEGER NOT NULL DEFAULT 0,
                modified_count INTEGER NOT NULL DEFAULT 0,
                removed_count INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Snapshot of each changed article. This makes the history independent
        # from later updates and lets the UI show "before / after".
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS article_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                law_id INTEGER,
                law_title TEXT NOT NULL,
                article_number TEXT NOT NULL,
                change_type TEXT NOT NULL,
                old_title TEXT,
                new_title TEXT,
                old_content TEXT,
                new_content TEXT,
                changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (run_id)
                    REFERENCES update_runs(id)
                    ON DELETE SET NULL
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_article_changes_run
            ON article_changes(run_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_article_changes_article
            ON article_changes(law_title, article_number)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_article_changes_date
            ON article_changes(changed_at)
        """)

        self.connection.commit()

    # =========================================================
    # LAWS
    # =========================================================

    def save_law(self, title, url, content):
        cursor = self.connection.cursor()

        cursor.execute("""
            INSERT INTO laws (
                title,
                url,
                content
            )
            VALUES (?, ?, ?)

            ON CONFLICT(url)
            DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                updated_at = CURRENT_TIMESTAMP
        """, (
            title,
            url,
            content
        ))

        self.connection.commit()

    def get_law_id(self, url):
        cursor = self.connection.cursor()

        cursor.execute("""
            SELECT id
            FROM laws
            WHERE url = ?
        """, (url,))

        row = cursor.fetchone()

        if row:
            return row["id"]

        return None

    def get_laws(self):
        cursor = self.connection.cursor()

        cursor.execute("""
            SELECT *
            FROM laws
            ORDER BY title
        """)

        return cursor.fetchall()

    def search_laws(self, query):
        cursor = self.connection.cursor()

        search = "%" + str(query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

        cursor.execute("""
            SELECT *
            FROM laws
            WHERE title LIKE ? ESCAPE '\\'
               OR content LIKE ? ESCAPE '\\'
            ORDER BY title
        """, (
            search,
            search
        ))

        return cursor.fetchall()

    # =========================================================
    # ARTICLES
    # =========================================================

    @staticmethod
    def _article_key(number):
        return str(number or "").strip().rstrip(".")

    @staticmethod
    def _normalized_for_compare(value):
        # Ignore parser/HTML whitespace-only differences while preserving the
        # original snapshots shown in the history UI.
        return " ".join(str(value or "").split())

    def _replace_articles(self, cursor, law_id, articles):
        cursor.execute("""
            DELETE FROM articles
            WHERE law_id = ?
        """, (law_id,))

        for article in articles:
            cursor.execute("""
                INSERT INTO articles (
                    law_id,
                    article_number,
                    title,
                    content
                )
                VALUES (?, ?, ?, ?)
            """, (
                law_id,
                article["number"],
                article.get("title", ""),
                article.get("content", "")
            ))

    def save_articles(self, law_id, articles):
        cursor = self.connection.cursor()
        self._replace_articles(cursor, law_id, articles)
        self.connection.commit()

    def save_articles_with_history(
        self,
        law_id,
        law_title,
        articles,
        run_id=None,
        record_changes=True,
    ):
        """Replace one document's articles and store an article-level diff.

        Returns a dict with added/modified/removed counts. The comparison uses
        article_number as the stable key and stores full old/new text snapshots.
        """
        cursor = self.connection.cursor()

        cursor.execute("""
            SELECT article_number, title, content
            FROM articles
            WHERE law_id = ?
        """, (law_id,))
        old_rows = cursor.fetchall()

        old_map = {
            self._article_key(row["article_number"]): {
                "number": str(row["article_number"] or "").strip(),
                "title": row["title"] or "",
                "content": row["content"] or "",
            }
            for row in old_rows
        }
        new_map = {
            self._article_key(article.get("number")): {
                "number": str(article.get("number") or "").strip(),
                "title": article.get("title") or "",
                "content": article.get("content") or "",
            }
            for article in articles
        }

        added_keys = sorted(set(new_map) - set(old_map))
        removed_keys = sorted(set(old_map) - set(new_map))
        modified_keys = []

        for key in sorted(set(old_map) & set(new_map)):
            old_item = old_map[key]
            new_item = new_map[key]
            if (
                self._normalized_for_compare(old_item["title"])
                != self._normalized_for_compare(new_item["title"])
                or self._normalized_for_compare(old_item["content"])
                != self._normalized_for_compare(new_item["content"])
            ):
                modified_keys.append(key)

        counts = {
            "added": len(added_keys),
            "modified": len(modified_keys),
            "removed": len(removed_keys),
        }

        try:
            cursor.execute("BEGIN")

            if record_changes:
                def insert_change(change_type, old_item=None, new_item=None):
                    old_item = old_item or {}
                    new_item = new_item or {}
                    number = (
                        new_item.get("number")
                        or old_item.get("number")
                        or ""
                    )
                    cursor.execute("""
                        INSERT INTO article_changes (
                            run_id,
                            law_id,
                            law_title,
                            article_number,
                            change_type,
                            old_title,
                            new_title,
                            old_content,
                            new_content
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        run_id,
                        law_id,
                        law_title,
                        number,
                        change_type,
                        old_item.get("title", ""),
                        new_item.get("title", ""),
                        old_item.get("content", ""),
                        new_item.get("content", ""),
                    ))

                for key in added_keys:
                    insert_change("added", new_item=new_map[key])
                for key in modified_keys:
                    insert_change("modified", old_map[key], new_map[key])
                for key in removed_keys:
                    insert_change("removed", old_item=old_map[key])

            self._replace_articles(cursor, law_id, articles)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        return counts

    def get_articles_by_law(self, law_id):
        cursor = self.connection.cursor()

        cursor.execute("""
            SELECT
                id,
                article_number,
                title,
                content
            FROM articles
            WHERE law_id = ?
            ORDER BY
                CAST(article_number AS INTEGER),
                article_number
        """, (law_id,))

        return cursor.fetchall()

    def get_article_by_reference(self, law_title, article_number, law_url=""):
        """Return one article using a stable law/title + article-number reference."""
        cursor = self.connection.cursor()
        number = str(article_number or "").strip().rstrip(".")
        title = str(law_title or "").strip()
        url = str(law_url or "").strip()

        cursor.execute("""
            SELECT
                articles.id,
                articles.article_number,
                articles.title AS article_title,
                articles.content,
                laws.title AS law_title,
                laws.url
            FROM articles
            JOIN laws ON laws.id = articles.law_id
            WHERE RTRIM(TRIM(articles.article_number), '.') = ?
              AND (laws.url = ? OR laws.title = ?)
            LIMIT 1
        """, (number, url, title))
        row = cursor.fetchone()
        if row is not None:
            return row

        cursor.execute("""
            SELECT
                articles.id,
                articles.article_number,
                articles.title AS article_title,
                articles.content,
                laws.title AS law_title,
                laws.url
            FROM articles
            JOIN laws ON laws.id = articles.law_id
            WHERE RTRIM(TRIM(articles.article_number), '.') = ?
            ORDER BY CASE WHEN laws.title = ? THEN 0 ELSE 1 END, laws.title
            LIMIT 1
        """, (number, title))
        return cursor.fetchone()

    def search_articles(self, query, limit=50):
        cursor = self.connection.cursor()

        search = "%" + str(query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

        cursor.execute("""
            SELECT
                articles.id,
                articles.article_number,
                articles.title AS article_title,
                articles.content,
                laws.title AS law_title,
                laws.url
            FROM articles

            JOIN laws
                ON laws.id = articles.law_id

            WHERE
                articles.article_number LIKE ? ESCAPE '\\'
                OR articles.title LIKE ? ESCAPE '\\'
                OR articles.content LIKE ? ESCAPE '\\'

            ORDER BY
                laws.title,
                CAST(articles.article_number AS INTEGER),
                articles.article_number

            LIMIT ?
        """, (
            search,
            search,
            search,
            limit
        ))

        return cursor.fetchall()

    # =========================================================
    # UPDATE / CHANGE HISTORY
    # =========================================================

    def begin_update_run(self):
        cursor = self.connection.cursor()
        cursor.execute("INSERT INTO update_runs DEFAULT VALUES")
        self.connection.commit()
        return cursor.lastrowid

    def finish_update_run(self, run_id, successful, failed, total_articles):
        if not run_id:
            return

        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN change_type = 'added' THEN 1 ELSE 0 END) AS added,
                SUM(CASE WHEN change_type = 'modified' THEN 1 ELSE 0 END) AS modified,
                SUM(CASE WHEN change_type = 'removed' THEN 1 ELSE 0 END) AS removed
            FROM article_changes
            WHERE run_id = ?
        """, (run_id,))
        row = cursor.fetchone()

        total_changes = int(row["total"] or 0)
        added = int(row["added"] or 0)
        modified = int(row["modified"] or 0)
        removed = int(row["removed"] or 0)

        cursor.execute("""
            UPDATE update_runs
            SET completed_at = CURRENT_TIMESTAMP,
                successful = ?,
                failed = ?,
                total_articles = ?,
                total_changes = ?,
                added_count = ?,
                modified_count = ?,
                removed_count = ?
            WHERE id = ?
        """, (
            int(successful),
            int(failed),
            int(total_articles),
            total_changes,
            added,
            modified,
            removed,
            int(run_id),
        ))
        self.connection.commit()

    def get_latest_update_run(self):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT *
            FROM update_runs
            ORDER BY id DESC
            LIMIT 1
        """)
        return cursor.fetchone()

    def get_update_runs(self, limit=20):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT *
            FROM update_runs
            ORDER BY id DESC
            LIMIT ?
        """, (max(1, int(limit)),))
        return cursor.fetchall()

    def get_recent_changes(self, limit=200, run_id=None):
        cursor = self.connection.cursor()
        if run_id is None:
            cursor.execute("""
                SELECT *
                FROM article_changes
                ORDER BY id DESC
                LIMIT ?
            """, (max(1, int(limit)),))
        else:
            cursor.execute("""
                SELECT *
                FROM article_changes
                WHERE run_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (int(run_id), max(1, int(limit))))
        return cursor.fetchall()

    def get_change(self, change_id):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT *
            FROM article_changes
            WHERE id = ?
        """, (int(change_id),))
        return cursor.fetchone()

    def get_change_count(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM article_changes")
        return int(cursor.fetchone()["count"] or 0)

    # =========================================================
    # STATISTICS
    # =========================================================

    def get_stats(self):
        cursor = self.connection.cursor()

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM laws
        """)

        laws = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM articles
        """)

        articles = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT MAX(updated_at) AS updated_at
            FROM laws
        """)

        row = cursor.fetchone()

        updated_at = (
            row["updated_at"]
            if row
            else None
        )

        try:
            changes = self.get_change_count()
        except sqlite3.Error:
            changes = 0

        return {
            "laws": laws,
            "articles": articles,
            "updated_at": updated_at,
            "changes": changes,
        }

    # =========================================================
    # CONNECTION
    # =========================================================

    def close(self):
        self.connection.close()
