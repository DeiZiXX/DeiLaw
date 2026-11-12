import sys
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QMessageBox,
)

from app_version import APP_VERSION
from user_state import BackupManager
from update_preferences import mode_from_settings, update_action
from updater import (
    UpdateCheckWorker,
    UpdateDownloadWorker,
    create_update_install_helper,
    launch_update_helper,
    load_update_config,
)


def _app_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _read_startup_update_channel():
    """Read only the tiny setting needed before the main UI is imported."""
    settings_path = _app_base_dir() / "data" / "settings.json"
    default_channel = str(
        load_update_config().get("channel") or "stable"
    ).strip().lower()
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        # Older installations do not have update_channel yet. In that case
        # preserve the automatic Beta default for a/b/c/RC builds instead of
        # silently forcing Stable during the pre-launch check.
        channel = str(
            payload.get("update_channel") or default_channel
        ).strip().lower()
        return channel if channel in ("stable", "beta") else default_channel
    except Exception:
        return default_channel


def _read_startup_update_mode():
    return mode_from_settings(_app_base_dir() / "data" / "settings.json")


def _startup_state_path():
    return _app_base_dir() / "data" / "startup_state.json"


def _begin_startup_attempt():
    """Track repeated crashes that happen before the main window is ready."""
    path = _startup_state_path()
    state = {"in_progress": False, "failures": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            state.update(payload)
    except Exception:
        pass

    failures = int(state.get("failures") or 0)
    if state.get("in_progress"):
        failures += 1

    state = {"in_progress": True, "failures": failures}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return failures


def _mark_startup_success():
    path = _startup_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"in_progress": False, "failures": 0}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _ask_safe_mode(parent, failures):
    if int(failures) < 2:
        return False
    answer = QMessageBox.question(
        parent,
        "Аварийное восстановление DeiLaw",
        "DeiLaw несколько раз подряд не завершил запуск.\n\n"
        "Запустить программу в безопасном режиме? В нём временно отключаются "
        "AI, быстрые оверлеи и глобальные бинды, а оформление переключается "
        "на стандартное. Пользовательские данные не удаляются.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return answer == QMessageBox.StandardButton.Yes


def _setup_logging():
    log_dir = _app_base_dir() / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "deilaw.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=700_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    return log_path


class StartupUpdateDialog(QDialog):
    """Check and install DeiLaw updates before the main window exists."""

    CONTINUE_STARTUP = 1
    UPDATE_STARTED = 2

    def __init__(self, update_channel="stable", update_install_mode="confirm", start_check=True):
        super().__init__(None)

        self.update_channel = (
            update_channel
            if update_channel in ("stable", "beta")
            else "stable"
        )
        self.update_install_mode = update_install_mode
        self.update_info = None
        self.check_worker = None
        self.download_worker = None
        self.update_started = False
        self.busy = True

        self.setWindowTitle("DeiLaw — проверка обновлений")
        self.setFixedSize(540, 220)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel(f"DeiLaw {APP_VERSION}")
        title.setObjectName("startupUpdateTitle")
        layout.addWidget(title)

        self.stage_label = QLabel("Этап 1/5 — Проверка обновлений")
        self.stage_label.setObjectName("startupUpdateStage")
        layout.addWidget(self.stage_label)

        self.status_label = QLabel("Проверяю наличие обновлений…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        hint = QLabel(
            "DeiLaw сначала проверяет новую версию и только потом запускает программу."
        )
        hint.setObjectName("startupUpdateHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.setStyleSheet(
            """
            QDialog {
                background: #101114;
                color: #f4f5f7;
            }
            QLabel {
                color: #f4f5f7;
                font-family: "Segoe UI";
                font-size: 14px;
            }
            QLabel#startupUpdateTitle {
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#startupUpdateHint {
                color: #8f96a3;
            }
            QLabel#startupUpdateStage {
                color: #7fa1ff;
                font-weight: 700;
            }
            QProgressBar {
                min-height: 22px;
                background: #1a1d22;
                color: #ffffff;
                border: 1px solid #343740;
                border-radius: 7px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #4f6bed;
                border-radius: 6px;
            }
            """
        )

        if start_check:
            QTimer.singleShot(120, self.start_check)

    def set_stage(self, number, title, detail=None, progress=None):
        number = max(1, min(5, int(number)))
        self.stage_label.setText(f"Этап {number}/5 — {title}")
        if detail is not None:
            self.status_label.setText(str(detail))
        if progress is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(max(0, min(100, int(progress))))
        logging.info("Startup stage %s/5: %s", number, title)
        QApplication.processEvents()

    def closeEvent(self, event):
        # Do not let Alt+F4 bypass a running update/check.
        if self.busy:
            event.ignore()
            return
        super().closeEvent(event)

    def start_check(self):
        self.busy = True
        channel_label = "Beta" if self.update_channel == "beta" else "Stable"
        self.set_stage(
            1,
            "Проверка обновлений",
            f"Проверяю канал {channel_label}…",
        )

        worker = UpdateCheckWorker(
            load_update_config(self.update_channel),
            self,
        )
        self.check_worker = worker
        worker.update_available.connect(self.on_update_available)
        worker.no_update.connect(self.on_no_update)
        worker.error.connect(self.on_check_error)
        worker.start()

    def on_no_update(self, _message):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.set_stage(
            1,
            "Проверка обновлений",
            "Версия актуальна. Подготавливаю запуск…",
            100,
        )
        self.busy = False
        QTimer.singleShot(
            300,
            lambda: self.done(self.CONTINUE_STARTUP),
        )

    def on_check_error(self, message):
        # Internet/GitHub failure must not lock the user out of the installed app.
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText(
            "Не удалось проверить обновления.\n"
            "Запускаю установленную версию DeiLaw…"
        )
        self.setToolTip(str(message))
        self.busy = False
        QTimer.singleShot(
            900,
            lambda: self.done(self.CONTINUE_STARTUP),
        )

    def on_update_available(self, info):
        version = str(info.get("version") or "")
        self.update_info = dict(info)
        action = update_action(self.update_install_mode)
        if action == "notify":
            self.status_label.setText(
                f"Доступна версия DeiLaw {version}. Установлена текущая версия."
            )
            self.busy = False
            QTimer.singleShot(800, lambda: self.done(self.CONTINUE_STARTUP))
            return
        if action == "ask":
            reply = QMessageBox.question(
                self, "Обновление DeiLaw",
                f"Доступна новая версия DeiLaw {version}.\n\n"
                "Скачать и установить проверенное обновление сейчас?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.busy = False
                self.done(self.CONTINUE_STARTUP)
                return
        self.status_label.setText(
            f"Найдена новая версия DeiLaw {version}.\n"
            "Скачиваю проверенное обновление…"
        )
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        worker = UpdateDownloadWorker(info, self)
        self.download_worker = worker
        worker.progress.connect(self.on_download_progress)
        worker.completed.connect(self.on_download_completed)
        worker.error.connect(self.on_download_error)
        worker.start()

    def on_download_progress(self, percent, downloaded, total):
        if total > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            done_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.status_label.setText(
                f"Скачиваю обновление… {done_mb:.1f} / {total_mb:.1f} MB"
            )
        else:
            self.progress.setRange(0, 0)
            done_mb = downloaded / (1024 * 1024)
            self.status_label.setText(
                f"Скачиваю обновление… {done_mb:.1f} MB"
            )

    def on_download_error(self, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText(
            "Не удалось скачать обновление.\n"
            "Запускаю текущую версию DeiLaw…"
        )
        self.setToolTip(str(message))
        self.busy = False
        QTimer.singleShot(
            1100,
            lambda: self.done(self.CONTINUE_STARTUP),
        )

    def on_download_completed(self, installer_path):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_label.setText(
            "Обновление скачано и проверено.\n"
            "Запускаю автоматическую установку…"
        )

        try:
            try:
                BackupManager(_app_base_dir() / "data").create_backup(
                    "before_program_update"
                )
            except Exception as backup_exc:
                logging.warning("Pre-update backup failed: %s", backup_exc)

            helper = create_update_install_helper(
                installer_path, self.update_info
            )
            launch_update_helper(helper)
        except Exception as exc:
            self.status_label.setText(
                "Не удалось запустить установку.\n"
                "Запускаю текущую версию DeiLaw…"
            )
            self.setToolTip(str(exc))
            self.busy = False
            QTimer.singleShot(
                1100,
                lambda: self.done(self.CONTINUE_STARTUP),
            )
            return

        self.update_started = True
        self.busy = False

        # The helper waits until this old process exits, silently installs the
        # new release and starts DeiLaw again.
        QTimer.singleShot(
            250,
            lambda: self.done(self.UPDATE_STARTED),
        )


def main():
    # Fix data/ being resolved against an arbitrary shortcut/console CWD.
    os.chdir(_app_base_dir())
    app = QApplication(sys.argv)
    app.setApplicationName("DeiLaw")
    log_path = _setup_logging()
    logging.info("DeiLaw %s starting", APP_VERSION)

    startup_failures = _begin_startup_attempt()
    update_channel = _read_startup_update_channel()
    update_install_mode = _read_startup_update_mode()

    # This happens before DeiLawWindow is constructed, therefore on the first
    # run the onboarding cannot start until the update check has finished.
    # Account transitions skip the pre-launch updater entirely.
    auth_choice_requested = "--auth-choice" in sys.argv
    discord_switch_requested = "--auth-discord" in sys.argv
    auth_restart = auth_choice_requested or discord_switch_requested
    startup_update = StartupUpdateDialog(
        update_channel, update_install_mode, start_check=not auth_restart
    )
    result = (StartupUpdateDialog.CONTINUE_STARTUP
              if auth_restart else startup_update.exec())

    if (
        result == StartupUpdateDialog.UPDATE_STARTED
        or startup_update.update_started
    ):
        # The updater will relaunch DeiLaw; this launch is intentionally ending.
        _mark_startup_success()
        return

    safe_mode = _ask_safe_mode(startup_update, startup_failures)
    if safe_mode:
        os.environ["DEILAW_SAFE_MODE"] = "1"
        startup_update.set_stage(
            2,
            "Безопасный режим",
            "Запускаю DeiLaw с минимальным набором функций…",
        )

    # Choose an authenticated Discord or guest identity before constructing
    # community clients, Cloud AI, hotkeys, or any of the main window.
    from cloud_auth import AnonymousSupabaseSession, WindowsTokenStore, CloudAuthError
    from community_client import SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY
    from ui.auth_dialog import AuthChoiceDialog

    auth = AnonymousSupabaseSession(
        SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY,
        store=WindowsTokenStore(_app_base_dir() / "data" / "cloud_auth.bin"),
    )
    if auth_choice_requested:
        for logged_out_mode in ("discord", "guest"):
            if f"--logout-mode={logged_out_mode}" in sys.argv:
                auth.discard_saved_mode(logged_out_mode)
    # Existing Discord/guest sessions survive app restarts. Only show the
    # account picker on first launch, after an invalid session, or when the
    # user explicitly requested another account in the sidebar.
    restored = False
    if auth.mode is not None and not auth_restart:
        startup_update.busy = True
        startup_update.show()
        startup_update.set_stage(2, "Авторизация", "Восстанавливаю сохранённый вход…")
        QApplication.processEvents()
        try:
            restored = auth.resume_active() is not None
        except (CloudAuthError, ValueError, TypeError) as exc:
            logging.warning("Saved DeiLaw login could not be restored: %s", exc)
        finally:
            startup_update.hide()
            startup_update.busy = False

    if not restored:
        login_dialog = AuthChoiceDialog(auth, discord_only=discord_switch_requested)
        if login_dialog.exec() != QDialog.DialogCode.Accepted:
            _mark_startup_success()
            return

    logging.info("DeiLaw user session accepted: %s", auth.mode)

    # Import and construct the large UI only after the update check.
    # This makes the startup/update window appear immediately instead of
    # waiting for database, AI and UI modules to import first.
    startup_update.busy = True
    startup_update.show()
    startup_update.set_stage(
        2,
        "Загрузка компонентов",
        "Подключаю модули DeiLaw…",
    )

    from ui.main_window import DeiLawWindow

    def startup_stage(number, title, detail=None):
        startup_update.set_stage(number, title, detail)

    window = DeiLawWindow(startup_callback=startup_stage)
    startup_update.set_stage(
        5,
        "Готово",
        "Запускаю основное окно DeiLaw…",
        100,
    )
    window.show()
    QApplication.processEvents()
    # Verify the saved installation secret and migrate old feedback only once
    # the Discord session and UI have been restored. Never block startup.
    QTimer.singleShot(350, window.start_legacy_feedback_import)
    _mark_startup_success()

    startup_update.busy = False
    QTimer.singleShot(180, startup_update.close)

    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
