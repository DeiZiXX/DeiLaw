import logging

from PyQt6.QtCore import QThread, pyqtSignal

from ai_core.engine import DeiLawAIEngine


class AIWorker(QThread):
    completed = pyqtSignal(str, object)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, situation, articles, history=None, learned_examples=None, parent=None):
        super().__init__(parent)
        self.situation = situation
        self.articles = list(articles or [])
        self.history = list(history or [])[-8:]
        self.learned_examples = list(learned_examples or [])[:4]

    def run(self):
        try:
            engine = DeiLawAIEngine()
            answer, candidates = engine.analyze(
                self.situation,
                self.articles,
                history=self.history,
                progress=self.status.emit,
            )
            self.completed.emit(answer, candidates)
        except Exception as exc:
            logging.exception("DeiLaw Cloud AI worker failed")
            self.error.emit(str(exc))
