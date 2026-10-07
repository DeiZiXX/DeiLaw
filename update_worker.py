from PyQt6.QtCore import QThread, pyqtSignal

from parser import RMRPParser
from article_parser import ArticleParser
from database import LawDatabase


class UpdateWorker(QThread):
    progress = pyqtSignal(int, int, str)
    document_done = pyqtSignal(str, int)
    completed = pyqtSignal(int, int, int)
    error = pyqtSignal(str)

    def run(self):
        database = None
        run_id = None
        run_finished = False
        successful = 0
        failed = 0
        total_articles = 0

        try:
            parser = RMRPParser()
            article_parser = ArticleParser()
            database = LawDatabase()
            run_id = database.begin_update_run()

            laws = parser.get_laws()
            total = len(laws)

            for index, law in enumerate(laws, start=1):
                self.progress.emit(index, total, law["title"])

                try:
                    # Remember whether the document already existed before this
                    # synchronization. A brand-new database is treated as the
                    # baseline instead of logging every article as a "change".
                    existing_law_id = database.get_law_id(law["url"])

                    document = parser.get_law_content(law["url"])

                    if not document["content"]:
                        failed += 1
                        continue

                    database.save_law(
                        title=law["title"],
                        url=law["url"],
                        content=document["content"]
                    )

                    law_id = database.get_law_id(law["url"])
                    articles = article_parser.parse(document["content"])

                    if existing_law_id is None:
                        database.save_articles(law_id, articles)
                    else:
                        database.save_articles_with_history(
                            law_id=law_id,
                            law_title=law["title"],
                            articles=articles,
                            run_id=run_id,
                            record_changes=True,
                        )

                    total_articles += len(articles)
                    successful += 1

                    self.document_done.emit(law["title"], len(articles))

                except Exception as exc:
                    failed += 1
                    self.error.emit(f"{law['title']}: {exc}")

            database.finish_update_run(
                run_id,
                successful=successful,
                failed=failed,
                total_articles=total_articles,
            )
            run_finished = True


            self.completed.emit(successful, failed, total_articles)

        except Exception as exc:
            self.error.emit(str(exc))

        finally:
            if database is not None:
                if run_id is not None and not run_finished:
                    try:
                        database.finish_update_run(
                            run_id,
                            successful=successful,
                            failed=failed,
                            total_articles=total_articles,
                        )
                    except Exception:
                        pass
                database.close()
