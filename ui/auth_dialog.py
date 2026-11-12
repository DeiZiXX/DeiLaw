"""First-run, expired-session and manual account choice for DeiLaw."""

import threading

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


class LoginWorker(QThread):
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, session, mode, parent=None, *, force_discord=False):
        super().__init__(parent)
        self.session = session
        self.mode = mode
        self.force_discord = force_discord
        self.cancel_event = threading.Event()

    def run(self):
        try:
            if self.mode == "discord":
                self.session.select_discord(
                    cancel_event=self.cancel_event, force=self.force_discord
                )
                label = "Discord"
            else:
                self.session.select_guest()
                label = "Гость"
            if not self.cancel_event.is_set():
                self.succeeded.emit(label)
        except Exception as exc:
            if not self.cancel_event.is_set():
                self.failed.emit(str(exc))


class AuthChoiceDialog(QDialog):
    def __init__(self, session, parent=None, *, discord_only=False):
        super().__init__(parent)
        self.session = session
        self.worker = None
        self.discord_only = discord_only
        self.setWindowTitle("DeiLaw — вход")
        self.setMinimumSize(520, 350)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 26)
        layout.setSpacing(15)

        heading = QLabel(
            "Смена аккаунта Discord" if discord_only
            else "Добро пожаловать в DeiLaw"
        )
        heading.setObjectName("loginHeading")
        layout.addWidget(heading)

        subtitle = QLabel(
            "В браузере выберите другой аккаунт Discord и подтвердите вход. "
            "Если браузер автоматически открывает старый профиль, "
            "сначала переключите аккаунт на сайте Discord."
            if discord_only else
            "Войдите через Discord, чтобы пользоваться постоянным аккаунтом, "
            "или продолжите как гость. Оба варианта используют защищённые "
            "сессии Supabase."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.discord_button = QPushButton("Войти через Discord")
        self.discord_button.setObjectName("discordLogin")
        self.discord_button.setMinimumHeight(50)
        self.discord_button.clicked.connect(lambda: self.start_login("discord"))
        layout.addWidget(self.discord_button)

        self.guest_button = QPushButton("Продолжить как гость")
        self.guest_button.setObjectName("guestLogin")
        self.guest_button.setMinimumHeight(46)
        self.guest_button.clicked.connect(lambda: self.start_login("guest"))
        layout.addWidget(self.guest_button)
        if discord_only:
            self.guest_button.hide()

        saved = self.session.saved_modes()
        if saved and not discord_only:
            labels = ["Discord" if mode == "discord" else "гостевой" for mode in saved]
            saved_hint = QLabel("Сохранённые сессии: " + ", ".join(labels))
            saved_hint.setObjectName("savedHint")
            layout.addWidget(saved_hint)

        self.status = QLabel("Выберите способ входа")
        self.status.setObjectName("loginStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.cancel_button = QPushButton("Выход")
        self.cancel_button.clicked.connect(self.cancel_login)
        bottom.addWidget(self.cancel_button)
        layout.addLayout(bottom)

        self.setStyleSheet("""
            QDialog { background: #11151d; color: #edf0f7; }
            QLabel { color: #c4cbd7; font: 13px 'Segoe UI'; }
            QLabel#loginHeading { color: white; font: bold 23px 'Segoe UI'; }
            QLabel#loginStatus { color: #a9c2ff; }
            QLabel#savedHint { color: #8b98a9; font-size: 12px; }
            QPushButton { background: #272f3e; color: white; padding: 10px;
                border: 1px solid #3d4860; border-radius: 8px; }
            QPushButton:hover { background: #364158; }
            QPushButton:disabled { background: #222631; color: #858a96; }
            QPushButton#discordLogin { background: #5865f2; border: 0;
                font-weight: bold; font-size: 15px; }
            QPushButton#discordLogin:hover { background: #6977fa; }
        """)
        if discord_only:
            QTimer.singleShot(0, lambda: self.start_login("discord"))

    def start_login(self, mode):
        if self.worker is not None and self.worker.isRunning():
            return
        self.discord_button.setEnabled(False)
        self.guest_button.setEnabled(False)
        self.cancel_button.setText("Отмена")
        self.status.setText(
            "Откройте браузер и подтвердите вход в Discord…"
            if mode == "discord" else "Создаю или восстанавливаю гостевую сессию…"
        )
        self.worker = LoginWorker(
            self.session, mode, self, force_discord=self.discord_only
        )
        self.worker.succeeded.connect(self._logged_in)
        self.worker.failed.connect(self._login_failed)
        self.worker.start()

    def _logged_in(self, name):
        self.status.setText(f"Вход выполнен: {name}")
        if self.worker is not None:
            self.worker.wait(1500)
        self.accept()

    def _login_failed(self, error):
        self.status.setText(error or "Не удалось выполнить вход.")
        self.discord_button.setEnabled(True)
        self.guest_button.setEnabled(True)
        self.cancel_button.setText("Выход")

    def cancel_login(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel_event.set()
            self.status.setText("Отменяю авторизацию…")
            self.worker.wait(1500)
            self.discord_button.setEnabled(True)
            self.guest_button.setEnabled(True)
            self.cancel_button.setText("Выход")
            return
        self.reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel_event.set()
            if not self.worker.wait(1500):
                self.status.setText("Ожидаю завершения сетевого запроса…")
                event.ignore()
                return
        super().closeEvent(event)
