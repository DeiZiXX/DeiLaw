import webbrowser
import re
import json
import sys
import os
import ctypes
import ctypes.wintypes
import subprocess
import platform
import logging
import threading
import time

try:
    import winsound
except ImportError:
    winsound = None
from pathlib import Path
from datetime import datetime, timezone, timedelta

from PyQt6.QtCore import Qt, QEvent, QAbstractNativeEventFilter, QByteArray, QElapsedTimer, QTimer, QPropertyAnimation, QEasingCurve, QSize, QStringListModel, QFileSystemWatcher, QThread, pyqtSignal, QKeyCombination
from PyQt6.QtGui import QKeySequence, QShortcut, QPainter, QPen, QIntValidator, QColor, QIcon, QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QProgressBar,  # ← добавить
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMenu,
    QCheckBox,
    QSpinBox,
    QComboBox,
    QKeySequenceEdit,
    QAbstractScrollArea,
    QAbstractItemView,
    QToolButton,
    QCompleter,
    QToolTip,
    QSystemTrayIcon,
)

from database import LawDatabase
from update_worker import UpdateWorker
from rp_assistant import RPAssistant
from ai_worker import AIWorker
from ai_core.cloud import CloudAIClient
from app_version import APP_VERSION
from user_state import ProfileStore, BackupManager
from ahk_bindings import AHKBindStore
from community_client import CommunityIdentity, SupabaseCommunityClient, CommunityError
from updater import (
    UpdateCheckWorker,
    UpdateDownloadWorker,
    ProgramReleaseHistoryWorker,
    create_update_install_helper,
    launch_update_helper,
    load_update_config,
    update_is_configured,
)
try:
    from gibdd_charter import (
        find_gibdd_charter,
        GibddCharterParser,
        download_gibdd_charter_url,
        normalize_charter_url,
    )
except ModuleNotFoundError:
    try:
        from .gibdd_charter import (
            find_gibdd_charter,
            GibddCharterParser,
            download_gibdd_charter_url,
            normalize_charter_url,
        )
    except ImportError:
        from ui.gibdd_charter import (
            find_gibdd_charter,
            GibddCharterParser,
            download_gibdd_charter_url,
            normalize_charter_url,
        )
# Smart Search dictionary can be stored either in the project root
# (next to main.py) or inside the ui package (next to main_window.py).
try:
    from search_lexicon import SmartLawSearch
except ModuleNotFoundError:
    try:
        from .search_lexicon import SmartLawSearch
    except ImportError:
        from ui.search_lexicon import SmartLawSearch



class CharterUrlWorker(QThread):
    """Load a remote charter without freezing the DeiLaw UI."""

    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, url, cache_dir, manual=False, parent=None):
        super().__init__(parent)
        self.url = str(url or "")
        self.cache_dir = Path(cache_dir)
        self.manual = bool(manual)

    def run(self):
        try:
            document, cache_path, source_kind = (
                download_gibdd_charter_url(
                    self.url,
                    self.cache_dir,
                )
            )
            self.loaded.emit(
                {
                    "url": normalize_charter_url(self.url),
                    "document": document,
                    "cache_path": str(cache_path),
                    "source_kind": source_kind,
                    "manual": self.manual,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class CommunityTaskWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, callback, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.callback = callback
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.callback(*self.args, **self.kwargs)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))




class StatusCheckBox(QCheckBox):
    """Checkbox with red OFF state and green ON state with a white tick."""

    def paintEvent(self, event):
        super().paintEvent(event)

        if not self.isChecked():
            return

        # Draw the white checkmark over the standard 18x18 indicator.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(Qt.GlobalColor.white)
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        # Indicator is at the left; account for widget contents margins.
        x = 4
        y = max(0, (self.height() - 18) // 2)
        painter.drawLine(x + 3, y + 9, x + 7, y + 13)
        painter.drawLine(x + 7, y + 13, x + 15, y + 5)
        painter.end()


class SingleHotkeyEdit(QKeySequenceEdit):
    """One primary key plus optional modifiers, with true NumPad support."""

    _NUMPAD_SCAN_TO_KEY = {
        0x52: Qt.Key.Key_0,
        0x4F: Qt.Key.Key_1,
        0x50: Qt.Key.Key_2,
        0x51: Qt.Key.Key_3,
        0x4B: Qt.Key.Key_4,
        0x4C: Qt.Key.Key_5,
        0x4D: Qt.Key.Key_6,
        0x47: Qt.Key.Key_7,
        0x48: Qt.Key.Key_8,
        0x49: Qt.Key.Key_9,
        0x53: Qt.Key.Key_Period,
        0x4A: Qt.Key.Key_Minus,
        0x4E: Qt.Key.Key_Plus,
    }

    _NUMPAD_VK_TO_KEY = {
        0x60: Qt.Key.Key_0,
        0x61: Qt.Key.Key_1,
        0x62: Qt.Key.Key_2,
        0x63: Qt.Key.Key_3,
        0x64: Qt.Key.Key_4,
        0x65: Qt.Key.Key_5,
        0x66: Qt.Key.Key_6,
        0x67: Qt.Key.Key_7,
        0x68: Qt.Key.Key_8,
        0x69: Qt.Key.Key_9,
        0x6A: Qt.Key.Key_Asterisk,
        0x6B: Qt.Key.Key_Plus,
        0x6D: Qt.Key.Key_Minus,
        0x6E: Qt.Key.Key_Period,
        0x6F: Qt.Key.Key_Slash,
    }

    def __init__(self, sequence=QKeySequence(), parent=None):
        super().__init__(parent)
        self._hotkey_spec = ''
        if hasattr(self, 'setMaximumSequenceLength'):
            self.setMaximumSequenceLength(1)
        self.keySequenceChanged.connect(self._sync_hotkey_spec)
        self.setToolTip(
            'Одна клавиша или Ctrl/Alt/Shift/Win + одна клавиша. '
            'NumPad определяется отдельно от обычного ряда цифр.'
        )
        self.setKeySequence(sequence)

    @staticmethod
    def normalize_spec(value):
        if isinstance(value, QKeySequence):
            value = value.toString(QKeySequence.SequenceFormat.PortableText)
        value = str(value or '').strip()
        # Older QKeySequenceEdit allowed sequential chords: "Л, Л".
        if ',' in value:
            value = value.split(',',1)[0].strip()
        return value

    def _sync_hotkey_spec(self, sequence):
        self._hotkey_spec = self.normalize_spec(sequence)

    def hotkey_text(self):
        return self._hotkey_spec or self.normalize_spec(self.keySequence())

    @classmethod
    def sequence_from_spec(cls, value):
        spec = cls.normalize_spec(value)
        if not spec:
            return QKeySequence()

        parts = [p.strip() for p in spec.split('+') if p.strip()]
        lowered = [p.casefold() for p in parts]
        if 'num' not in lowered and 'numpad' not in lowered and 'keypad' not in lowered:
            return QKeySequence(spec)

        modifiers = Qt.KeyboardModifier.KeypadModifier
        base = None
        for part in parts:
            token = part.casefold()
            if token in ('ctrl','control'):
                modifiers |= Qt.KeyboardModifier.ControlModifier
            elif token == 'alt':
                modifiers |= Qt.KeyboardModifier.AltModifier
            elif token == 'shift':
                modifiers |= Qt.KeyboardModifier.ShiftModifier
            elif token in ('win','windows','meta'):
                modifiers |= Qt.KeyboardModifier.MetaModifier
            elif token in ('num','numpad','keypad'):
                continue
            else:
                base = part

        if base is None:
            return QKeySequence(spec)

        upper = base.upper()
        if len(base) == 1 and base.isdigit():
            qt_key = getattr(Qt.Key, f'Key_{base}')
        else:
            qt_key = {
                'PLUS': Qt.Key.Key_Plus,
                'ADD': Qt.Key.Key_Plus,
                'MINUS': Qt.Key.Key_Minus,
                'SUBTRACT': Qt.Key.Key_Minus,
                'ASTERISK': Qt.Key.Key_Asterisk,
                'MULTIPLY': Qt.Key.Key_Asterisk,
                'SLASH': Qt.Key.Key_Slash,
                'DIVIDE': Qt.Key.Key_Slash,
                'DECIMAL': Qt.Key.Key_Period,
                'PERIOD': Qt.Key.Key_Period,
                'ENTER': Qt.Key.Key_Enter,
            }.get(upper)
        if qt_key is None:
            return QKeySequence(spec)
        try:
            return QKeySequence(QKeyCombination(modifiers, qt_key))
        except Exception:
            return QKeySequence(spec)

    def keyPressEvent(self, event):
        # Modifier-only press is not a complete bind.
        if event.key() in (
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Meta,
            Qt.Key.Key_AltGr,
        ):
            event.accept()
            return

        try:
            vk = int(event.nativeVirtualKey())
        except Exception:
            vk = 0
        qt_key = self._NUMPAD_VK_TO_KEY.get(vk)

        is_keypad = bool(event.modifiers() & Qt.KeyboardModifier.KeypadModifier)
        if qt_key is None and is_keypad:
            try:
                scan = int(event.nativeScanCode()) & 0xFF
            except Exception:
                scan = 0
            qt_key = self._NUMPAD_SCAN_TO_KEY.get(scan)
            if qt_key is None:
                # NumPad Enter has the same VK as Return; KeypadModifier keeps it distinct.
                if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
                    qt_key = Qt.Key.Key_Enter
                elif event.key() in (
                    Qt.Key.Key_Asterisk, Qt.Key.Key_Plus, Qt.Key.Key_Minus,
                    Qt.Key.Key_Period, Qt.Key.Key_Comma, Qt.Key.Key_Slash,
                ):
                    qt_key = event.key()

        if qt_key is not None:
            modifiers = Qt.KeyboardModifier.KeypadModifier
            original = event.modifiers()
            if original & Qt.KeyboardModifier.ControlModifier:
                modifiers |= Qt.KeyboardModifier.ControlModifier
            if original & Qt.KeyboardModifier.AltModifier:
                modifiers |= Qt.KeyboardModifier.AltModifier
            if original & Qt.KeyboardModifier.ShiftModifier:
                modifiers |= Qt.KeyboardModifier.ShiftModifier
            if original & Qt.KeyboardModifier.MetaModifier:
                modifiers |= Qt.KeyboardModifier.MetaModifier

            combo = QKeyCombination(modifiers, qt_key)
            super().setKeySequence(QKeySequence(combo))
            event.accept()
            return

        # For ordinary keys let Qt handle Cyrillic/Latin/special keys, but the
        # one-sequence limit guarantees that "Л, Л" can never be created.
        super().keyPressEvent(event)


class ThemeSwitch(QCheckBox):
    """Compact slider used to switch between dark and light themes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Переключить светлую / тёмную тему")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        if self.isChecked():
            track = QColor("#4f6bed")
            knob = QColor("#ffffff")
            knob_x = 29
        else:
            track = QColor("#5b616b")
            knob = QColor("#f8f9fb")
            knob_x = 5

        painter.setBrush(track)
        painter.drawRoundedRect(1, 4, 52, 20, 10, 10)
        painter.setBrush(knob)
        painter.drawEllipse(knob_x, 4, 20, 20)
        painter.end()

    def mousePressEvent(self, event):
        """Toggle from any point inside the visible slider, not only the checkbox indicator."""
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().keyPressEvent(event)


class TutorialTargetRing(QWidget):
    """Top-level transparent ring used by the guided tutorial.

    It never modifies the highlighted widget's stylesheet, so the tour cannot
    break complex Qt style sheets. The window is mouse-transparent and can
    highlight widgets that live in the main window as well as F7/F8 overlays.
    """

    def __init__(self):
        super().__init__(None)
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._margin = 18

    def highlight(self, widget):
        if widget is None or not widget.isVisible():
            self.hide()
            return False

        try:
            if widget.visibleRegion().isEmpty():
                self.hide()
                return False
            top_left = widget.mapToGlobal(widget.rect().topLeft())
            width = max(1, widget.width())
            height = max(1, widget.height())
            margin = self._margin
            self.setGeometry(
                top_left.x() - margin,
                top_left.y() - margin,
                width + margin * 2,
                height + margin * 2,
            )
            self.show()
            self.raise_()
            self.update()
            return True
        except Exception:
            self.hide()
            return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Soft outer glow.
        glow = QPen(QColor(245, 185, 66, 85))
        glow.setWidth(10)
        painter.setPen(glow)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outer = self.rect().adjusted(8, 8, -8, -8)
        painter.drawRoundedRect(outer, 12, 12)

        # Crisp gold focus frame.
        pen = QPen(QColor('#f5b942'))
        pen.setWidth(3)
        painter.setPen(pen)
        inner = self.rect().adjusted(12, 12, -12, -12)
        painter.drawRoundedRect(inner, 10, 10)

        # Small arrow on the left that points into the selected control.
        cy = self.height() // 2
        painter.setPen(QPen(QColor('#f5b942'), 3))
        painter.drawLine(1, cy, 12, cy)
        painter.drawLine(12, cy, 7, cy - 5)
        painter.drawLine(12, cy, 7, cy + 5)
        painter.end()


class WindowsHotkeyFilter(QAbstractNativeEventFilter):
    """Receives WM_HOTKEY even while another Windows application has focus."""

    WM_HOTKEY = 0x0312

    def __init__(self, callback, hotkey_id=0xD311):
        super().__init__()
        self.callback = callback
        self.hotkey_id = hotkey_id

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0

        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and msg.wParam == self.hotkey_id:
                self.callback()
                return True, 0
        except Exception:
            pass

        return False, 0


class DeiLawWindow(QMainWindow):

    def __init__(self, startup_callback=None):
        super().__init__()
        self._startup_callback = startup_callback

        def startup_stage(number, title, detail=None):
            if self._startup_callback is not None:
                try:
                    self._startup_callback(number, title, detail)
                except Exception:
                    pass

        startup_stage(3, "База и настройки", "Открываю локальную базу DeiLaw…")

        # Application/window icon (title bar, Alt+Tab and Windows taskbar).
        self.setup_application_icon()

        self.database = LawDatabase()
        self.smart_text_search = SmartLawSearch(self.database)

        self.search_results = []
        self.laws = []
        self.current_articles = []
        self.current_article_sections = {}
        self.law_section_rows = {}
        self.law_section_buttons = {}
        self.update_worker = None
        self.rp_assistant = RPAssistant(self.database)
        self.rp_results = []
        self.ai_worker = None
        self.ai_runtime_check_worker = None
        self.ai_repair_worker = None
        self.ai_repair_dialog = None
        self.ai_runtime_last_status = None
        self.program_update_check_worker = None
        self.program_update_download_worker = None
        self.program_release_history_worker = None
        self.program_update_info = None
        self.program_update_dialog = None
        self.program_update_progress_dialog = None
        self.program_update_automatic_install = False
        self.program_update_status_text = "Не проверялось"
        self.program_update_poll_timer = None
        self.program_update_poll_interval_ms = 3 * 60 * 1000
        self.program_update_prompt_timer = QElapsedTimer()
        self.program_update_prompt_timer.start()
        self.last_program_update_prompt_version = ""
        self.last_program_update_prompt_ms = -60 * 60 * 1000
        # Internal operations such as installing an update must be able to
        # bypass the user's "minimize on X" preference and really terminate.
        self._force_full_exit = False
        self.system_tray_icon = None
        self.system_tray_menu = None
        self._tray_hint_shown = False
        self.ai_chat_messages = []
        self.current_ai_situation = ""
        self.current_ai_candidates = []
        self.ai_session_path = Path("data/last_ai_session.json")
        self.ai_session_draft = ""
        self.ai_session_save_timer = QTimer(self)
        self.ai_session_save_timer.setSingleShot(True)
        self.ai_session_save_timer.setInterval(600)
        self.ai_session_save_timer.timeout.connect(self.save_last_ai_session)
        self._auto_law_update_in_progress = False
        # RP assistant warning is intentionally session-only: the user sees it
        # again after restarting DeiLaw, but can suppress repeats while working.
        self.rp_beta_warning_suppressed = False
        # First-launch database setup flow. If the new installation has no
        # articles yet, DeiLaw directs the user to the Update page before
        # starting the normal onboarding tour.
        self.memo_path = Path("data/memo.json")
        self.memo_columns = self.load_memo_config()
        self.memo_overlay = None
        self.settings_path = Path("data/settings.json")
        self.search_history_path = Path("data/search_history.json")
        self.search_history = self.load_search_history()
        self.app_settings = self.load_app_settings()
        self.load_last_ai_session()
        self.safe_mode = os.environ.get("DEILAW_SAFE_MODE") == "1"
        self.profile_store = ProfileStore("data/profiles.json")
        self.active_profile = self.profile_store.active_name()
        self.memo_columns = self.profile_store.memo_columns(
            self.memo_columns,
            self.active_profile,
        )
        self.backup_manager = BackupManager("data")
        self.ahk_bind_store = AHKBindStore("data/ahk_binds.json")
        self.current_ahk_bind_id = None
        self.ahk_runtime_hotkeys = []
        self.ahk_runtime_busy = False
        self.ahk_runtime_lock = threading.Lock()
        self.ahk_runtime_last_summary = ""
        self.community_identity = CommunityIdentity(
            "data/community_identity.json"
        )
        self.community_client = SupabaseCommunityClient(
            identity=self.community_identity
        )
        self.community_workers = []
        self.community_reviews = []
        self.community_bug_reports = []
        self.community_reply_monitor_timer = None
        self.community_reply_monitor_loading = False
        self.community_reply_monitor_initialized = False
        startup_stage(3, "База и настройки", "Настройки загружены. Подготавливаю данные…")
        self.memo_shortcut = None
        self.search_shortcut = None
        self.calculator_shortcut = None

        self.global_hotkey_id = 0xD311
        self.search_global_hotkey_id = 0xD312
        self.calculator_global_hotkey_id = 0xD313

        self.global_hotkey_filter = None
        self.search_global_hotkey_filter = None
        self.calculator_global_hotkey_filter = None

        self.global_hotkey_registered = False
        self.search_global_hotkey_registered = False
        self.calculator_global_hotkey_registered = False

        self.memo_hotkey_timer = QElapsedTimer()
        self.memo_hotkey_timer.start()
        self.search_hotkey_timer = QElapsedTimer()
        self.search_hotkey_timer.start()
        self.calculator_hotkey_timer = QElapsedTimer()
        self.calculator_hotkey_timer.start()

        self.last_memo_hotkey_ms = -1000
        self.last_search_hotkey_ms = -1000
        self.last_calculator_hotkey_ms = -1000
        self.memo_drag_position = None
        self.search_overlay_drag_position = None
        self.search_overlay = None
        self.search_overlay_results = []

        # F9 opens a standalone Quick Calculator overlay, just like F7/F8.
        self.calculator_overlay_drag_position = None
        self.calculator_overlay = None
        self.calculator_overlay_choice_menu = None
        self.save_toast = None
        self.save_toast_animation = None
        self.settings_dirty = False
        self.settings_snapshot = None
        self.settings_original_font_size = None
        self.settings_original_overlay_opacity = None
        self.settings_original_overlay_opacities = None
        self.settings_original_theme = None
        self.settings_original_visual_theme = None

        # Optional charter selected in Settings. It can be a local DOCX or a
        # remote Google Docs / direct DOCX / forum-web source cached locally.
        self.gibdd_charter_source_type = str(
            self.app_settings.get("gibdd_charter_source_type", "file")
            or "file"
        ).strip().lower()
        if self.gibdd_charter_source_type not in ("file", "url"):
            self.gibdd_charter_source_type = "file"

        configured_charter = str(
            (
                self.app_settings.get("gibdd_charter_cache_path", "")
                if self.gibdd_charter_source_type == "url"
                else self.app_settings.get("gibdd_charter_path", "")
            )
            or ""
        ).strip()

        self.gibdd_charter_path = (
            Path(configured_charter).expanduser()
            if configured_charter
            else None
        )
        self.gibdd_charter_source_url = str(
            self.app_settings.get("gibdd_charter_url", "") or ""
        ).strip()
        self.gibdd_charter_url_worker = None
        self.gibdd_charter_remote_timer = None
        self.gibdd_charter_remote_interval_ms = 5 * 60 * 1000
        self.gibdd_charter_document = None
        self.gibdd_charter_error = ""
        self.gibdd_charter_articles = []
        self.gibdd_charter_chapter_rows = {}
        self.gibdd_charter_chapter_buttons = {}
        self.gibdd_charter_signature = None
        self.gibdd_charter_watcher = None
        self.gibdd_charter_sync_timer = None
        self.gibdd_charter_poll_timer = None

        startup_stage(4, "Устав и быстрые функции", "Проверяю подключённый Устав…")

        # Do not parse a potentially large DOCX before the first frame is
        # painted. The live charter synchronizer loads it shortly after startup.
        if (
            self.gibdd_charter_path is not None
            and not self.gibdd_charter_path.is_file()
        ):
            self.gibdd_charter_error = (
                "Локальная копия выбранного источника Устава не найдена."
                if self.gibdd_charter_source_type == "url"
                else "Выбранный файл Устава не найден."
            )

        # Page indexes are assigned in setup_ui because the charter page is
        # conditional and therefore changes the stacked-widget layout.
        self.search_page_index = None
        self.laws_page_index = None
        self.favorites_page_index = None
        self.gibdd_charter_page_index = None
        self.assistant_page_index = None
        self.memo_page_index = None
        self.update_page_index = None
        self.ahk_page_index = None
        self.status_page_index = None
        self.settings_page_index = None

        self.setWindowTitle(
            "DeiLaw — RMRP Law Assistant"
        )

        self.resize(1450, 850)
        self.setMinimumSize(1100, 650)

        startup_stage(5, "Интерфейс", "Создаю интерфейс и регистрирую горячие клавиши…")
        self.setup_ui()
        self.setup_system_tray()
        if not self.safe_mode:
            self.start_gibdd_charter_watcher()
        self.install_button_sounds()
        self.apply_style()
        startup_stage(5, "Интерфейс", "Интерфейс готов. Завершаю запуск…")

        # Let the first frame paint before database-heavy refreshes. This makes
        # startup feel responsive even with a large law database.
        QTimer.singleShot(40, self.load_stats)
        QTimer.singleShot(90, self.load_laws)
        QTimer.singleShot(160, self.refresh_update_history)
        QTimer.singleShot(220, self.refresh_status_page)

        # Load/parse the configured charter after the main window is visible.
        if not self.safe_mode:
            QTimer.singleShot(320, self.sync_gibdd_charter_tab)

        # First-launch walkthrough starts after the initial data population.
        QTimer.singleShot(900, self.run_first_launch_flow)


        # Notify once when a newer legislation sync contains changes.
        QTimer.singleShot(2600, self.notify_unseen_legislation_changes)

        # Start a persistent background monitor after the initial UI settles.
        # It checks at startup and then every 3 minutes while DeiLaw is running.
        QTimer.singleShot(5500, self.start_program_update_monitor)

        # Developer replies are checked in the background even when DeiLaw is
        # minimized to the system tray. The first successful check only seeds
        # the seen-message cache, so old replies are never announced as new.
        QTimer.singleShot(7000, self.start_report_reply_monitor)

        # Law database update is intentionally delayed until the main window,
        # onboarding and normal startup tasks have settled.
        QTimer.singleShot(9000, self.maybe_auto_update_laws_at_startup)

    # =========================================================
    # REPORT REPLY VOICE NOTIFICATIONS
    # =========================================================

    def start_report_reply_monitor(self):
        """Watch developer replies while DeiLaw is running/minimized."""
        if self.safe_mode:
            return

        if self.community_reply_monitor_timer is None:
            timer = QTimer(self)
            timer.setInterval(10000)
            timer.timeout.connect(self.check_report_reply_notifications)
            self.community_reply_monitor_timer = timer

        self.check_report_reply_notifications()
        self.community_reply_monitor_timer.start()

    def check_report_reply_notifications(self):
        if self.community_reply_monitor_loading:
            return

        self.community_reply_monitor_loading = True

        def loaded(rows):
            self.community_reply_monitor_loading = False
            self._process_developer_reply_rows(rows, announce=True)

        def failed(_message):
            # Community notifications must never disturb the main app when the
            # network is temporarily unavailable. A later poll retries.
            self.community_reply_monitor_loading = False

        self._run_community_task(
            self.community_client.fetch_developer_report_messages,
            on_success=loaded,
            on_error=failed,
        )

    def _process_developer_reply_rows(self, rows, announce=True):
        """Remember reply IDs and announce only genuinely new developer posts."""
        rows = [
            row for row in list(rows or [])
            if str(row.get("sender") or "") == "developer"
            and str(row.get("id") or "").strip()
        ]
        current_ids = [str(row.get("id")) for row in rows]

        raw_seen = self.app_settings.get("report_reply_seen_ids", [])
        seen = {
            str(value) for value in raw_seen
            if str(value or "").strip()
        }

        # First run of this feature: establish a baseline silently. This keeps
        # all historical developer messages from being read aloud after update.
        if not self.community_reply_monitor_initialized and not seen:
            self.community_reply_monitor_initialized = True
            self.app_settings["report_reply_seen_ids"] = current_ids[:200]
            try:
                self.save_app_settings()
            except Exception:
                pass
            return False

        self.community_reply_monitor_initialized = True
        new_rows = [
            row for row in rows
            if str(row.get("id")) not in seen
        ]

        if current_ids:
            merged = current_ids + [
                value for value in seen if value not in current_ids
            ]
            self.app_settings["report_reply_seen_ids"] = merged[:200]
            try:
                self.save_app_settings()
            except Exception:
                pass

        if new_rows and announce:
            self.play_report_reply_voice()
            try:
                if self.system_tray_icon is not None:
                    self.system_tray_icon.showMessage(
                        "DeiLaw — ответ на репорт",
                        "Разработчик ответил на ваш репорт",
                        QSystemTrayIcon.MessageIcon.Information,
                        5000,
                    )
            except Exception:
                pass
            return True

        return False

    def play_report_reply_voice(self):
        """Play the bundled developer-reply voice notification."""
        if not self.app_settings.get("ui_sounds", True):
            return
        if not self.app_settings.get("report_reply_voice", True):
            return

        try:
            sound_path = self.get_ui_sound_path("report_reply.wav")
            if sound_path and winsound is not None:
                winsound.PlaySound(
                    sound_path,
                    winsound.SND_FILENAME
                    | winsound.SND_ASYNC
                    | winsound.SND_NODEFAULT,
                )
                return
        except Exception:
            pass

        # Fallback if the bundled voice file cannot be played.
        self.play_ui_sound("success")

    # =========================================================
    # SYSTEM TRAY
    # =========================================================

    def setup_system_tray(self):
        """Create the persistent Windows system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.system_tray_icon = None
            self.system_tray_menu = None
            return

        tray = QSystemTrayIcon(self)
        if not self.windowIcon().isNull():
            tray.setIcon(self.windowIcon())
        tray.setToolTip(
            f"DeiLaw v{APP_VERSION} — RMRP Law Assistant"
        )

        menu = QMenu(self)

        open_action = menu.addAction("Открыть DeiLaw")
        open_action.triggered.connect(self.restore_from_tray)

        menu.addSeparator()

        search_action = menu.addAction("🔎 Quick Search — F7")
        search_action.triggered.connect(self.toggle_search_overlay)

        memo_action = menu.addAction("📌 Quick Memo — F8")
        memo_action.triggered.connect(self.toggle_memo_overlay)

        calculator_action = menu.addAction("🧮 Quick Calculator — F9")
        calculator_action.triggered.connect(
            self.toggle_calculator_hotkey
        )

        menu.addSeparator()

        exit_action = menu.addAction("Закрыть DeiLaw полностью")
        exit_action.triggered.connect(self.exit_from_tray)

        tray.setContextMenu(menu)
        tray.activated.connect(self.on_system_tray_activated)
        tray.show()

        self.system_tray_icon = tray
        self.system_tray_menu = menu

    def on_system_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def restore_from_tray(self):
        """Restore DeiLaw and return the main window to the taskbar."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def exit_from_tray(self):
        """Fully terminate DeiLaw from the tray menu."""
        self._force_full_exit = True
        self.show()
        self.close()

    # =========================================================
    # PROGRAM AUTO-UPDATE
    # =========================================================

    def set_program_update_status(self, text):
        self.program_update_status_text = str(text or "")
        if hasattr(self, "settings_program_update_status"):
            self.settings_program_update_status.setText(
                self.program_update_status_text
            )
        if hasattr(self, "status_app_label"):
            self.refresh_status_page()

    def start_program_update_monitor(self):
        """Start the always-on update monitor for the current session."""
        if self.program_update_poll_timer is None:
            self.program_update_poll_timer = QTimer(self)
            self.program_update_poll_timer.setInterval(
                self.program_update_poll_interval_ms
            )
            self.program_update_poll_timer.timeout.connect(
                self.auto_check_program_update
            )

        # main.py has already checked before creating this window.
        # The next automatic check is therefore the regular 3-minute poll.
        self.update_program_update_monitor_state()

    def update_program_update_monitor_state(self):
        """Program auto-update is an always-on DeiLaw system function."""
        self.app_settings["auto_check_program_updates"] = True

        if hasattr(self, "settings_auto_program_updates"):
            self.settings_auto_program_updates.blockSignals(True)
            self.settings_auto_program_updates.setChecked(True)
            self.settings_auto_program_updates.setEnabled(False)
            self.settings_auto_program_updates.blockSignals(False)

        if self.program_update_poll_timer is None:
            return

        if not self.program_update_poll_timer.isActive():
            self.program_update_poll_timer.start()

    def auto_check_program_update(self):
        config = load_update_config(
            self.app_settings.get("update_channel", "stable")
        )
        if not update_is_configured(config):
            self.set_program_update_status(
                "Канал автообновления недоступен."
            )
            return

        # Do not wait for onboarding/settings dialogs. The update can download
        # in the background and will restart DeiLaw when it is ready.
        self.check_program_update(manual=False)

    def check_program_update(self, manual=True):
        if (
            self.program_update_check_worker is not None
            and self.program_update_check_worker.isRunning()
        ):
            if manual:
                self.set_program_update_status(
                    "Проверка обновлений уже выполняется…"
                )
            return

        config = load_update_config(
            self.app_settings.get("update_channel", "stable")
        )
        if not update_is_configured(config):
            message = (
                "Канал автоматических обновлений DeiLaw сейчас недоступен."
            )
            self.set_program_update_status(
                "Автообновление не привязано к GitHub."
            )
            if manual:
                QMessageBox.information(
                    self,
                    "Обновления DeiLaw",
                    message,
                )
            return

        self.set_program_update_status("Проверяю обновления…")
        if hasattr(self, "settings_check_program_update_button"):
            self.settings_check_program_update_button.setEnabled(False)

        worker = UpdateCheckWorker(config, self)
        self.program_update_check_worker = worker
        worker.update_available.connect(
            lambda info, manual=manual:
            self.on_program_update_available(info, manual)
        )
        worker.no_update.connect(
            lambda message, manual=manual:
            self.on_program_update_not_found(message, manual)
        )
        worker.error.connect(
            lambda message, manual=manual:
            self.on_program_update_error(message, manual)
        )
        worker.finished.connect(
            self.on_program_update_check_finished
        )
        worker.start()

    def on_program_update_check_finished(self):
        if hasattr(self, "settings_check_program_update_button"):
            self.settings_check_program_update_button.setEnabled(True)

    def on_program_update_not_found(self, message, manual=False):
        self.set_program_update_status(message)
        if manual:
            QMessageBox.information(
                self,
                "Обновления DeiLaw",
                message,
            )

    def on_program_update_error(self, message, manual=False):
        self.set_program_update_status(
            f"Ошибка проверки: {message}"
        )
        if manual:
            QMessageBox.warning(
                self,
                "Обновления DeiLaw",
                message,
            )

    def on_program_update_available(self, info, manual=False):
        self.program_update_info = dict(info)
        version = str(info.get("version", "?"))
        mandatory = bool(info.get("mandatory", False))
        notes = info.get("notes") or []

        self.set_program_update_status(
            f"Доступна новая версия DeiLaw {version}."
        )

        if not manual:
            # New release found during normal work: update without asking.
            if (
                self.program_update_download_worker is not None
                and self.program_update_download_worker.isRunning()
            ):
                return
            self.download_program_update(
                info,
                automatic=True,
            )
            return

        # An automatic poll runs every three minutes. If the user already chose
        # "Позже", do not hammer them with the same dialog on every poll.
        # A different/newer version is still shown immediately.
        if not manual and not mandatory:
            now = self.program_update_prompt_timer.elapsed()
            same_version = (
                version == self.last_program_update_prompt_version
            )
            too_soon = (
                now - self.last_program_update_prompt_ms
                < 30 * 60 * 1000
            )
            if same_version and too_soon:
                return

        # Avoid opening a second update dialog over another modal window.
        if (
            not manual
            and QApplication.activeModalWidget() is not None
        ):
            QTimer.singleShot(
                5000,
                lambda info=dict(info):
                self.on_program_update_available(
                    info,
                    manual=False,
                ),
            )
            return

        if self.program_update_dialog is not None:
            return

        if not manual:
            self.last_program_update_prompt_version = version
            self.last_program_update_prompt_ms = (
                self.program_update_prompt_timer.elapsed()
            )

            # The user asked for newly published updates to be surfaced while
            # DeiLaw is already running, even when the main window is minimized.
            if self.isMinimized():
                self.showNormal()
            else:
                self.show()
            self.raise_()
            self.activateWindow()

        dialog = QDialog(self)
        dialog.setWindowTitle("Обновление DeiLaw")
        dialog.setModal(True)
        dialog.resize(610, 430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        title = QLabel(f"Доступна версия DeiLaw {version}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        current = QLabel(
            f"Установлена: {APP_VERSION}\n"
            f"Доступна: {version}"
        )
        current.setObjectName("muted")
        layout.addWidget(current)

        notes_title = QLabel("Что нового")
        notes_title.setObjectName("sectionTitle")
        layout.addWidget(notes_title)

        notes_box = QTextBrowser()
        if notes:
            notes_box.setPlainText(
                "\n".join(f"• {item}" for item in notes)
            )
        else:
            notes_box.setPlainText(
                "Описание изменений для этой версии не добавлено."
            )
        layout.addWidget(notes_box, stretch=1)

        if mandatory:
            warning = QLabel(
                "⚠ Это обязательное обновление."
            )
            warning.setObjectName("muted")
            layout.addWidget(warning)

        buttons = QHBoxLayout()
        if not mandatory:
            later = QPushButton("Позже")
            later.clicked.connect(dialog.reject)
            buttons.addWidget(later)
        buttons.addStretch()
        update_now = QPushButton("Обновить сейчас")
        update_now.setObjectName("primary")
        update_now.clicked.connect(dialog.accept)
        buttons.addWidget(update_now)
        layout.addLayout(buttons)

        self.program_update_dialog = dialog
        result = dialog.exec()
        self.program_update_dialog = None

        if result == QDialog.DialogCode.Accepted:
            self.download_program_update(info)
        elif mandatory:
            # Keep mandatory update visible without killing the process.
            QTimer.singleShot(
                1800,
                lambda: self.on_program_update_available(info),
            )

    def download_program_update(self, info, automatic=False):
        if (
            self.program_update_download_worker is not None
            and self.program_update_download_worker.isRunning()
        ):
            return

        self.program_update_automatic_install = bool(automatic)

        dialog = QDialog(self)
        dialog.setWindowTitle(
            "Автоматическое обновление DeiLaw"
            if automatic
            else "Скачивание обновления"
        )
        dialog.setModal(True)
        dialog.setFixedWidth(560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        title = QLabel(
            (
                f"Автоматическое обновление DeiLaw "
                f"{info.get('version', '')}"
            )
            if automatic
            else f"Скачивание DeiLaw {info.get('version', '')}"
        )
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.program_update_progress_label = QLabel(
            "Подготовка к загрузке…"
        )
        self.program_update_progress_label.setObjectName("muted")
        layout.addWidget(self.program_update_progress_label)

        self.program_update_progress_bar = QProgressBar()
        self.program_update_progress_bar.setRange(0, 100)
        self.program_update_progress_bar.setValue(0)
        layout.addWidget(self.program_update_progress_bar)

        self.program_update_progress_dialog = dialog

        worker = UpdateDownloadWorker(info, self)
        self.program_update_download_worker = worker
        worker.progress.connect(
            self.on_program_update_download_progress
        )
        worker.completed.connect(
            self.on_program_update_downloaded
        )
        worker.error.connect(
            self.on_program_update_download_error
        )
        worker.start()

        dialog.show()

    def on_program_update_download_progress(
        self,
        percent,
        downloaded,
        total,
    ):
        if hasattr(self, "program_update_progress_bar"):
            if total > 0:
                self.program_update_progress_bar.setRange(0, 100)
                self.program_update_progress_bar.setValue(percent)
            else:
                self.program_update_progress_bar.setRange(0, 0)

        if hasattr(self, "program_update_progress_label"):
            mb_done = downloaded / (1024 * 1024)
            if total > 0:
                mb_total = total / (1024 * 1024)
                self.program_update_progress_label.setText(
                    f"{mb_done:.1f} MB / {mb_total:.1f} MB"
                )
            else:
                self.program_update_progress_label.setText(
                    f"{mb_done:.1f} MB"
                )

    def on_program_update_download_error(self, message):
        automatic = bool(self.program_update_automatic_install)
        self.program_update_automatic_install = False

        if self.program_update_progress_dialog is not None:
            self.program_update_progress_dialog.close()
            self.program_update_progress_dialog = None

        self.set_program_update_status(
            f"Ошибка загрузки: {message}"
        )
        QMessageBox.warning(
            self,
            (
                "Автоматическое обновление DeiLaw"
                if automatic
                else "Обновление DeiLaw"
            ),
            (
                f"Автоматическое обновление не удалось:\n{message}"
                if automatic
                else message
            ),
        )

    def on_program_update_downloaded(self, installer_path):
        automatic = bool(self.program_update_automatic_install)
        self.program_update_automatic_install = False

        if self.program_update_progress_dialog is not None:
            self.program_update_progress_dialog.close()
            self.program_update_progress_dialog = None

        self.set_program_update_status(
            "Обновление скачано и проверено по SHA-256."
        )

        if not automatic:
            answer = QMessageBox.question(
                self,
                "Установить обновление",
                "Обновление успешно скачано и проверено.\n\n"
                "DeiLaw сейчас закроется, установит новую версию и "
                "запустится снова.\n\n"
                "Установить обновление сейчас?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            try:
                self.save_current_profile_runtime()
                self.save_app_settings()
                self.backup_manager.create_backup(
                    "before_program_update"
                )
            except Exception as backup_exc:
                logging.warning(
                    "Pre-update backup failed: %s",
                    backup_exc,
                )

            helper = create_update_install_helper(
                installer_path
            )
            launch_update_helper(helper)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Обновление DeiLaw",
                f"Не удалось запустить установку:\n{exc}",
            )
            return

        self._force_full_exit = True
        QApplication.quit()

    # =========================================================
    # APPLICATION ICON
    # =========================================================

    def setup_application_icon(self):
        """Load the DeiLaw icon set and apply it to every top-level window.

        Preferred Windows format is ICO. Supported files inside assets/icons/:
          icon16.ico, icon32.ico, icon48.ico, icon64.ico,
          icon128.ico, icon256.ico
        Also accepts names with a space or underscore, e.g.
          "icon 32.ico" or "icon_32.ico".

        PNG variants with the same names are supported too. A single
        multi-size icon.ico is preferred when present.
        """
        # Give Windows a stable application identity so the taskbar does not
        # group DeiLaw under python.exe when running from source.
        if sys.platform == "win32":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "DeiLaw.RMRP.LawAssistant"
                )
            except Exception:
                pass

        script_dir = Path(__file__).resolve().parent
        candidates = [
            script_dir / "assets" / "icons",
            script_dir.parent / "assets" / "icons",
            Path.cwd() / "assets" / "icons",
        ]

        # Keep order while removing duplicate paths.
        icon_dirs = []
        for folder in candidates:
            folder = folder.resolve()
            if folder not in icon_dirs:
                icon_dirs.append(folder)

        icon = QIcon()
        loaded = False

        # Prefer one ICO when present; it may already contain several sizes.
        for folder in icon_dirs:
            ico = folder / "icon.ico"
            if ico.exists():
                icon.addFile(str(ico))
                loaded = True
                break

        # Add individual size files too. ICO is checked first because these
        # are the files Windows normally uses for desktop applications. PNG
        # remains supported as an optional fallback. QIcon chooses the best
        # available size for the title bar, Alt+Tab, taskbar and high-DPI UI.
        for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 192, 256):
            names = (
                f"icon{size}.ico",
                f"icon_{size}.ico",
                f"icon {size}.ico",
                f"icon{size}.png",
                f"icon_{size}.png",
                f"icon {size}.png",
            )
            found = None
            for folder in icon_dirs:
                for name in names:
                    path = folder / name
                    if path.exists():
                        found = path
                        break
                if found is not None:
                    break
            if found is not None:
                icon.addFile(str(found))
                loaded = True

        if not loaded or icon.isNull():
            return

        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)

    # =========================================================
    # UI
    # =========================================================

    def setup_ui(self):

        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # SIDEBAR
        # The sidebar is scrollable and responsive: on compact windows it
        # reduces spacing/button height and keeps every navigation item
        # accessible instead of pushing support/version controls off-screen.
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(188)
        sidebar.setMaximumWidth(250)
        self.sidebar = sidebar

        sidebar_shell_layout = QVBoxLayout(sidebar)
        sidebar_shell_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_shell_layout.setSpacing(0)

        self.sidebar_scroll = QScrollArea(sidebar)
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.sidebar_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.sidebar_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self.sidebar_scroll.viewport().setAutoFillBackground(False)

        sidebar_content = QWidget()
        sidebar_content.setObjectName("sidebarContent")
        self.sidebar_content = sidebar_content

        sidebar_layout = QVBoxLayout(sidebar_content)
        self.sidebar_layout = sidebar_layout
        sidebar_layout.setContentsMargins(18, 24, 18, 20)
        sidebar_layout.setSpacing(14)

        logo = QLabel("DeiLaw")
        logo.setObjectName("logo")

        description = QLabel(
            "RMRP Law Assistant"
        )
        description.setObjectName("muted")

        sidebar_layout.addWidget(logo)
        sidebar_layout.addWidget(description)
        sidebar_layout.addSpacing(25)

        self.search_nav = self.nav_button("🔎  Поиск")
        self.laws_nav = self.nav_button("📚  Законы")
        self.favorites_nav = self.nav_button("⭐  Избранное")

        # This optional button is created only when the DOCX is present and
        # parsed successfully. A live folder watcher adds/removes it at runtime.
        self.gibdd_charter_nav = None
        if self.gibdd_charter_document is not None:
            self.gibdd_charter_nav = self.nav_button("🚓  Устав")
            self.gibdd_charter_nav.setToolTip(
                f"Локальный документ: {self.gibdd_charter_path.name}"
            )

        self.assistant_nav = self.nav_button("✨  RP-помощник (БЕТА)")
        self.memo_nav = self.nav_button("📌  Памятка")
        self.calculator_nav = self.nav_button("🧮  Калькулятор")
        self.update_nav = self.nav_button("🔄  Обновления Базы")
        self.update_history_nav = self.nav_button("🕘  Прошлые обновления")
        self.ahk_nav = self.nav_button("⌨  AHK бинды")
        self.community_nav = self.nav_button("⭐  Отзывы")
        self.settings_nav = self.nav_button("⚙  Настройки")

        sidebar_layout.addWidget(self.search_nav)
        sidebar_layout.addWidget(self.laws_nav)
        sidebar_layout.addWidget(self.favorites_nav)
        if self.gibdd_charter_nav is not None:
            sidebar_layout.addWidget(self.gibdd_charter_nav)
        sidebar_layout.addWidget(self.assistant_nav)
        sidebar_layout.addWidget(self.memo_nav)
        sidebar_layout.addWidget(self.calculator_nav)
        sidebar_layout.addWidget(self.update_nav)
        sidebar_layout.addWidget(self.update_history_nav)
        sidebar_layout.addWidget(self.ahk_nav)
        sidebar_layout.addWidget(self.community_nav)
        sidebar_layout.addWidget(self.settings_nav)
        sidebar_layout.addStretch()

        self.stats_label = QLabel()
        self.stats_label.setObjectName("muted")
        self.stats_label.setWordWrap(True)
        sidebar_layout.addWidget(self.stats_label)

        # Compact always-visible support button.
        self.donate_button = QPushButton("❤  Поддержать автора")
        self.donate_button.setObjectName("primary")
        self.donate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.donate_button.setToolTip(
            "Добровольно поддержать развитие DeiLaw"
        )
        self.donate_button.setMinimumHeight(36)
        self.donate_button.clicked.connect(
            lambda checked=False: self.open_developer_link(
                "https://new.donatepay.ru/donate/944732"
            )
        )
        sidebar_layout.addWidget(self.donate_button)


        self.support_hint_label = QLabel("Поддержка, связь и репорты")
        self.support_hint_label.setObjectName("muted")
        self.support_hint_label.setWordWrap(True)
        sidebar_layout.addWidget(self.support_hint_label)

        self.support_button = QPushButton("💬  Поддержка")
        self.support_button.setObjectName("contactButton")
        self.support_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.support_button.setToolTip("Связь с разработчиком и репорты")

        self.support_menu = QMenu(self.support_button)
        self.support_menu.setObjectName("supportMenu")
        self.support_action_contacts = self.support_menu.addAction("👤  Связь с разработчиком")
        self.support_action_contacts.triggered.connect(self.show_developer_contacts)
        self.support_action_reports = self.support_menu.addAction("🐞  Репорты")
        self.support_action_reports.triggered.connect(self.show_my_bug_reports)
        self.support_button.setMenu(self.support_menu)
        sidebar_layout.addWidget(self.support_button)

        version = QLabel(f"DeiLaw v{APP_VERSION}")
        version.setObjectName("muted")
        self.sidebar_version_label = version
        sidebar_layout.addWidget(version)

        self.sidebar_scroll.setWidget(sidebar_content)
        sidebar_shell_layout.addWidget(self.sidebar_scroll)
        root.addWidget(sidebar)

        # PAGES. The optional charter page can also be inserted/removed live;
        # page indexes are refreshed from widget identities after each change.
        self.pages = QStackedWidget()

        self.search_page = self.create_search_page()
        self.search_page_index = self.pages.addWidget(self.search_page)

        self.laws_page = self.create_laws_page()
        self.laws_page_index = self.pages.addWidget(self.laws_page)

        self.favorites_page = self.create_favorites_page()
        self.favorites_page_index = self.pages.addWidget(self.favorites_page)

        self.gibdd_charter_page = None
        if self.gibdd_charter_document is not None:
            self.gibdd_charter_page = self.create_gibdd_charter_page()
            self.gibdd_charter_page_index = self.pages.addWidget(
                self.gibdd_charter_page
            )

        self.assistant_page = self.create_assistant_page()
        self.assistant_page_index = self.pages.addWidget(self.assistant_page)

        self.memo_page = self.create_memo_page()
        self.memo_page_index = self.pages.addWidget(self.memo_page)

        self.calculator_page = self.create_penalty_calculator_page()
        self.calculator_page_index = self.pages.addWidget(self.calculator_page)

        self.update_page = self.create_update_page()
        self.update_page_index = self.pages.addWidget(self.update_page)

        self.update_history_page = self.create_update_history_page()
        self.update_history_page_index = self.pages.addWidget(
            self.update_history_page
        )

        self.status_page = None
        self.status_page_index = None

        self.ahk_page = self.create_ahk_bindings_page()
        self.ahk_page_index = self.pages.addWidget(self.ahk_page)

        self.community_page = self.create_community_page()
        self.community_page_index = self.pages.addWidget(
            self.community_page
        )

        self.settings_page = self.create_settings_page()
        self.settings_page_index = self.pages.addWidget(self.settings_page)

        root.addWidget(self.pages, stretch=1)

        # NAVIGATION
        self.nav_buttons = [
            self.search_nav,
            self.laws_nav,
            self.favorites_nav,
        ]
        if self.gibdd_charter_nav is not None:
            self.nav_buttons.append(self.gibdd_charter_nav)
        self.nav_buttons.extend([
            self.assistant_nav,
            self.memo_nav,
            self.calculator_nav,
            self.update_nav,
            self.update_history_nav,
            self.ahk_nav,
            self.community_nav,
            self.settings_nav,
        ])

        for nav_button in self.nav_buttons:
            nav_button.setCheckable(True)
            nav_button.setAutoExclusive(True)
            nav_button.setObjectName("navButton")

        self.search_nav.setChecked(True)
        self.search_nav.clicked.connect(
            lambda: self.switch_page(self.search_page_index)
        )
        self.laws_nav.clicked.connect(
            lambda: self.switch_page(self.laws_page_index)
        )
        self.favorites_nav.clicked.connect(
            lambda: self.switch_page(self.favorites_page_index)
        )
        if self.gibdd_charter_nav is not None:
            self.gibdd_charter_nav.clicked.connect(
                lambda: self.switch_page(self.gibdd_charter_page_index)
            )
        self.assistant_nav.clicked.connect(
            lambda: self.switch_page(self.assistant_page_index)
        )
        self.memo_nav.clicked.connect(
            lambda: self.switch_page(self.memo_page_index)
        )
        self.calculator_nav.clicked.connect(
            lambda: self.switch_page(self.calculator_page_index)
        )
        self.update_nav.clicked.connect(
            lambda: self.switch_page(self.update_page_index)
        )
        self.update_history_nav.clicked.connect(
            lambda: self.switch_page(self.update_history_page_index)
        )
        self.ahk_nav.clicked.connect(
            lambda: self.switch_page(self.ahk_page_index)
        )
        self.community_nav.clicked.connect(
            lambda: self.switch_page(self.community_page_index)
        )
        self.settings_nav.clicked.connect(
            lambda: self.switch_page(self.settings_page_index)
        )

        self.command_palette_shortcut = QShortcut(
            QKeySequence("Ctrl+K"),
            self,
        )
        self.command_palette_shortcut.setContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self.command_palette_shortcut.activated.connect(
            self.show_command_palette
        )

        self.restore_active_profile_calculator()
        self.refresh_favorites_page()
        self._refresh_page_indexes()
        self._update_sidebar_responsiveness()

    # =========================================================
    # SEARCH HISTORY
    # =========================================================

    def load_search_history(self):
        try:
            if self.search_history_path.exists():
                data = json.loads(self.search_history_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [str(item).strip() for item in data if str(item).strip()][:50]
        except Exception:
            pass
        return []

    def save_search_history(self):
        try:
            self.search_history_path.parent.mkdir(parents=True, exist_ok=True)
            self.search_history_path.write_text(
                json.dumps(self.search_history[:50], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def add_search_history(self, query):
        query = re.sub(r"\s+", " ", str(query or "")).strip()
        if not query:
            return
        normalized = query.lower().replace("ё", "е")
        self.search_history = [
            item for item in self.search_history
            if item.lower().replace("ё", "е") != normalized
        ]
        self.search_history.insert(0, query)
        self.search_history = self.search_history[:50]
        self.save_search_history()
        self.refresh_search_history_menu()

    def clear_search_history(self):
        self.search_history = []
        self.save_search_history()
        self.refresh_search_history_menu()
        if hasattr(self, "search_count"):
            self.search_count.setText("История поиска очищена")

    def refresh_search_history_menu(self):
        menu = getattr(self, "search_history_menu", None)
        if menu is None:
            return
        menu.clear()
        if not self.search_history:
            action = menu.addAction("История пока пуста")
            action.setEnabled(False)
            return

        for query in self.search_history[:15]:
            action = menu.addAction(query)
            action.setToolTip(query)
            action.triggered.connect(
                lambda checked=False, q=query: self.run_history_search(q)
            )

        menu.addSeparator()
        clear_action = menu.addAction("Очистить историю")
        clear_action.triggered.connect(self.clear_search_history)

    def run_history_search(self, query):
        if not hasattr(self, "search_input"):
            return
        self.search_input.setText(query)
        self.search_input.setCursorPosition(len(query))
        self.perform_search()

    # =========================================================
    # SEARCH PAGE
    # =========================================================

    def create_search_page(self):

        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            30, 25, 30, 25
        )
        layout.setSpacing(15)

        title = QLabel(
            "Поиск по законодательству"
        )
        title.setObjectName("pageTitle")

        description = QLabel(
            "Умные подсказки: DeiLaw предлагает формулировки, прошлые запросы, статьи и связанные темы прямо во время ввода"
        )
        description.setObjectName("muted")

        layout.addWidget(title)
        layout.addWidget(description)

        search_row = QHBoxLayout()

        self.search_input = QLineEdit()

        self.search_input.setPlaceholderText(
            "Например: 9.8 КоАП, не остановился по требованию, уехал с места ДТП..."
        )

        self.search_input.setClearButtonEnabled(
            True
        )

        search_button = QPushButton(
            "Найти"
        )
        search_button.setObjectName(
            "primary"
        )

        search_row.addWidget(
            self.search_input,
            stretch=1
        )

        self.search_history_button = QToolButton()
        self.search_history_button.setText("🕘  История")
        self.search_history_button.setToolTip("Последние поисковые запросы")
        self.search_history_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.search_history_menu = QMenu(self.search_history_button)
        self.search_history_button.setMenu(self.search_history_menu)
        self.refresh_search_history_menu()
        search_row.addWidget(self.search_history_button)

        search_row.addWidget(
            search_button
        )

        layout.addLayout(search_row)

        self.search_count = QLabel(
            "Введите запрос"
        )
        self.search_count.setObjectName(
            "muted"
        )

        layout.addWidget(
            self.search_count
        )

        splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        self.search_list = QListWidget()

        self.search_content = QTextBrowser()

        splitter.addWidget(
            self.search_list
        )

        splitter.addWidget(
            self.search_content
        )

        splitter.setSizes(
            [400, 800]
        )

        layout.addWidget(
            splitter,
            stretch=1
        )

        search_actions = QHBoxLayout()
        self.search_favorite_button = QPushButton("☆  В избранное")
        self.search_favorite_button.setEnabled(False)
        self.search_favorite_button.clicked.connect(
            self.toggle_current_search_favorite
        )
        search_actions.addWidget(self.search_favorite_button)
        search_actions.addStretch()
        layout.addLayout(search_actions)

        # Живые подсказки: во время ввода показываем варианты, но сам поиск
        # запускаем только после выбора подсказки, Enter или кнопки «Найти».
        self.search_suggestion_model = QStringListModel(self)
        self.search_completer = QCompleter(self.search_suggestion_model, self.search_input)
        self.search_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.search_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.search_completer.setMaxVisibleItems(10)
        self.search_input.setCompleter(self.search_completer)
        self.search_completer.activated[str].connect(self.on_search_suggestion_activated)

        self.search_input.textChanged.connect(
            self.update_search_suggestions
        )

        search_button.clicked.connect(
            self.run_search_now
        )

        self.search_input.returnPressed.connect(
            self.handle_search_enter
        )

        self.search_list.currentRowChanged.connect(
            self.show_search_result
        )

        return page

    # =========================================================
    # LAWS PAGE
    # =========================================================

    def create_laws_page(self):

        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            30, 25, 30, 25
        )

        title = QLabel(
            "Законодательство"
        )
        title.setObjectName("pageTitle")

        # SECTION NAVIGATION IN THE PAGE HEADER
        # The buttons appear to the right of the "Законодательство" title
        # after a document with sections/chapters has been selected.
        self.law_sections_scroll = QScrollArea()
        self.law_sections_scroll.setObjectName("lawSectionsScroll")
        self.law_sections_scroll.setWidgetResizable(True)
        self.law_sections_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.law_sections_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.law_sections_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.law_sections_scroll.setFixedHeight(48)
        self.law_sections_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )

        self.law_sections_container = QWidget()
        self.law_sections_container.setObjectName("lawSectionsContainer")
        self.law_sections_layout = QHBoxLayout(self.law_sections_container)
        self.law_sections_layout.setContentsMargins(0, 2, 0, 2)
        self.law_sections_layout.setSpacing(6)
        self.law_sections_layout.addStretch()
        self.law_sections_scroll.setWidget(self.law_sections_container)
        self.law_sections_scroll.hide()

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(18)
        header_layout.addWidget(
            title,
            0,
            Qt.AlignmentFlag.AlignVCenter
        )
        header_layout.addWidget(
            self.law_sections_scroll,
            1,
            Qt.AlignmentFlag.AlignVCenter
        )

        description = QLabel(
            "Все документы локальной базы RMRP"
        )
        description.setObjectName("muted")

        layout.addLayout(header_layout)
        layout.addWidget(description)

        splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        # DOCUMENTS

        self.laws_list = QListWidget()

        # ARTICLES

        articles_panel = QWidget()
        articles_panel.setObjectName("lawArticlesPanel")
        articles_layout = QVBoxLayout(articles_panel)
        articles_layout.setContentsMargins(0, 0, 0, 0)
        articles_layout.setSpacing(7)

        self.articles_list = QListWidget()
        self.articles_list.setObjectName("lawArticlesList")

        articles_layout.addWidget(self.articles_list, stretch=1)

        # CONTENT

        content_panel = QWidget()

        content_layout = QVBoxLayout(
            content_panel
        )

        self.document_title = QLabel(
            "Выберите документ"
        )

        self.document_title.setObjectName(
            "articleHeading"
        )

        self.document_title.setWordWrap(
            True
        )

        self.article_content = QTextBrowser()

        self.source_button = QPushButton(
            "Открыть на форуме"
        )

        self.copy_button = QPushButton(
            "Копировать статью"
        )
        self.law_favorite_button = QPushButton("☆  В избранное")
        self.law_favorite_button.setEnabled(False)

        buttons = QHBoxLayout()

        buttons.addWidget(
            self.copy_button
        )
        buttons.addWidget(self.law_favorite_button)

        buttons.addWidget(
            self.source_button
        )

        buttons.addStretch()

        content_layout.addWidget(
            self.document_title
        )

        content_layout.addWidget(
            self.article_content,
            stretch=1
        )

        content_layout.addLayout(
            buttons
        )

        splitter.addWidget(
            self.laws_list
        )

        splitter.addWidget(
            articles_panel
        )

        splitter.addWidget(
            content_panel
        )

        splitter.setSizes(
            [330, 250, 650]
        )

        layout.addWidget(
            splitter,
            stretch=1
        )

        self.laws_list.currentRowChanged.connect(
            self.load_articles
        )

        self.articles_list.currentRowChanged.connect(
            self.show_article
        )

        self.copy_button.clicked.connect(
            self.copy_current_article
        )
        self.law_favorite_button.clicked.connect(
            self.toggle_current_law_favorite
        )

        self.source_button.clicked.connect(
            self.open_current_law
        )

        return page

    # =========================================================
    # FAVORITES / PROFILES
    # =========================================================

    def create_favorites_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("Избранное и профили")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(QLabel("Профиль:"))

        self.profile_combo = QComboBox()
        for name in self.profile_store.profile_names():
            self.profile_combo.addItem(name, name)
        active_index = self.profile_combo.findData(self.active_profile)
        self.profile_combo.setCurrentIndex(active_index if active_index >= 0 else 0)
        self.profile_combo.currentIndexChanged.connect(
            self.on_profile_combo_changed
        )
        title_row.addWidget(self.profile_combo)

        self.add_profile_button = QPushButton("+ Профиль")
        self.add_profile_button.clicked.connect(self.add_user_profile)
        title_row.addWidget(self.add_profile_button)

        self.rename_profile_button = QPushButton("✎ Переименовать")
        self.rename_profile_button.clicked.connect(self.rename_user_profile)
        title_row.addWidget(self.rename_profile_button)

        self.delete_profile_button = QPushButton("− Удалить")
        self.delete_profile_button.setToolTip(
            "Удалить выбранный профиль и его данные"
        )
        self.delete_profile_button.clicked.connect(
            self.delete_user_profile
        )
        title_row.addWidget(self.delete_profile_button)
        layout.addLayout(title_row)

        hint = QLabel(
            "У каждого профиля свои избранные статьи, памятка и набор статей "
            "калькулятора. Первые избранные статьи становятся быстрыми кнопками."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        quick_card = QFrame()
        quick_card.setObjectName("card")
        quick_layout = QVBoxLayout(quick_card)
        quick_title = QLabel("Быстрые кнопки профиля")
        quick_title.setObjectName("sectionTitle")
        quick_layout.addWidget(quick_title)
        self.profile_quick_buttons_layout = QHBoxLayout()
        quick_layout.addLayout(self.profile_quick_buttons_layout)
        self.profile_quick_hint = QLabel()
        self.profile_quick_hint.setObjectName("muted")
        self.profile_quick_hint.setWordWrap(True)
        quick_layout.addWidget(self.profile_quick_hint)
        layout.addWidget(quick_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        favorites_panel = QWidget()
        favorites_layout = QVBoxLayout(favorites_panel)
        favorites_layout.setContentsMargins(0, 0, 8, 0)
        favorites_title = QLabel("⭐ Избранные статьи")
        favorites_title.setObjectName("sectionTitle")
        self.favorites_list = QListWidget()
        self.favorites_list.setWordWrap(True)
        self.favorites_open_button = QPushButton("Открыть статью")
        self.favorites_remove_button = QPushButton("Удалить из избранного")
        favorites_buttons = QHBoxLayout()
        favorites_buttons.addWidget(self.favorites_open_button)
        favorites_buttons.addWidget(self.favorites_remove_button)
        favorites_buttons.addStretch()
        favorites_layout.addWidget(favorites_title)
        favorites_layout.addWidget(self.favorites_list, stretch=1)
        favorites_layout.addLayout(favorites_buttons)

        recent_panel = QWidget()
        recent_layout = QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(8, 0, 0, 0)
        recent_title = QLabel("🕘 Недавно просмотренные")
        recent_title.setObjectName("sectionTitle")
        self.recent_articles_list = QListWidget()
        self.recent_articles_list.setWordWrap(True)
        self.recent_open_button = QPushButton("Открыть статью")
        recent_layout.addWidget(recent_title)
        recent_layout.addWidget(self.recent_articles_list, stretch=1)
        recent_layout.addWidget(self.recent_open_button)

        splitter.addWidget(favorites_panel)
        splitter.addWidget(recent_panel)
        splitter.setSizes([600, 600])
        layout.addWidget(splitter, stretch=1)

        self.favorites_open_button.clicked.connect(
            self.open_selected_favorite
        )
        self.favorites_remove_button.clicked.connect(
            self.remove_selected_favorite
        )
        self.recent_open_button.clicked.connect(
            self.open_selected_recent
        )
        self.favorites_list.itemDoubleClicked.connect(
            lambda _item: self.open_selected_favorite()
        )
        self.recent_articles_list.itemDoubleClicked.connect(
            lambda _item: self.open_selected_recent()
        )
        self.favorites_list.currentItemChanged.connect(
            lambda *_args: self.refresh_profile_controls()
        )
        self.recent_articles_list.currentItemChanged.connect(
            lambda *_args: self.refresh_profile_controls()
        )
        self.refresh_profile_controls()
        return page

    @staticmethod
    def _favorite_item_text(item):
        text = f"Статья {item.get('article_number', '')} • {item.get('law_title', '')}"
        title = str(item.get("article_title") or "").strip()
        if title:
            text += "\n" + title
        return text

    def refresh_favorites_page(self):
        if not hasattr(self, "favorites_list"):
            return

        self.favorites_list.clear()
        favorites = self.profile_store.favorites(self.active_profile)
        if favorites:
            for article in favorites:
                item = QListWidgetItem(self._favorite_item_text(article))
                item.setData(Qt.ItemDataRole.UserRole, article)
                self.favorites_list.addItem(item)
        else:
            placeholder = QListWidgetItem("Пока нет избранных статей. Откройте закон или результат поиска и нажмите «В избранное»." )
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.favorites_list.addItem(placeholder)

        self.recent_articles_list.clear()
        recent_articles = self.profile_store.recent()
        if recent_articles:
            for article in recent_articles:
                item = QListWidgetItem(self._favorite_item_text(article))
                item.setData(Qt.ItemDataRole.UserRole, article)
                self.recent_articles_list.addItem(item)
        else:
            placeholder = QListWidgetItem("Недавно просмотренных статей пока нет.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent_articles_list.addItem(placeholder)

        while self.profile_quick_buttons_layout.count():
            item = self.profile_quick_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if favorites:
            self.profile_quick_hint.setText(
                "Первые 6 избранных статей становятся быстрыми кнопками профиля."
            )
            for article in favorites[:6]:
                label = f"{article.get('article_number', '')}"
                button = QPushButton(label)
                button.setToolTip(self._favorite_item_text(article))
                button.clicked.connect(
                    lambda checked=False, ref=dict(article): self.open_article_reference(ref)
                )
                self.profile_quick_buttons_layout.addWidget(button)
        else:
            self.profile_quick_hint.setText(
                "Когда вы добавите статьи в избранное, здесь появятся быстрые кнопки для профиля."
            )

        self.profile_quick_buttons_layout.addStretch()
        self.refresh_profile_controls()

    def refresh_profile_controls(self):
        if hasattr(self, "profile_combo"):
            profile_count = self.profile_combo.count()
            has_profiles = profile_count > 0
            current_profile_name = str(self.profile_combo.currentData() or "").strip()
            if hasattr(self, "rename_profile_button"):
                self.rename_profile_button.setEnabled(has_profiles and bool(current_profile_name))
            if hasattr(self, "delete_profile_button"):
                self.delete_profile_button.setEnabled(profile_count > 1 and bool(current_profile_name))
                self.delete_profile_button.setToolTip(
                    "Удалить выбранный профиль и его данные"
                    if profile_count > 1
                    else "Последний профиль удалить нельзя"
                )

        if hasattr(self, "favorites_open_button"):
            current_item = self.favorites_list.currentItem()
            has_article = bool(current_item and current_item.data(Qt.ItemDataRole.UserRole))
            self.favorites_open_button.setEnabled(has_article)
            self.favorites_remove_button.setEnabled(has_article)

        if hasattr(self, "recent_open_button"):
            recent_item = self.recent_articles_list.currentItem()
            has_recent = bool(recent_item and recent_item.data(Qt.ItemDataRole.UserRole))
            self.recent_open_button.setEnabled(has_recent)

    def _reload_profile_combo(self, selected_name=None):
        if not hasattr(self, "profile_combo"):
            return
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile_name in self.profile_store.profile_names():
            self.profile_combo.addItem(profile_name, profile_name)
        target = str(selected_name or self.active_profile or "").strip()
        index = self.profile_combo.findData(target)
        self.profile_combo.setCurrentIndex(index if index >= 0 else 0)
        self.profile_combo.blockSignals(False)
        self.refresh_profile_controls()

    def _current_search_article_ref(self):
        row = getattr(self, "search_list", None)
        if row is None:
            return None
        index = self.search_list.currentRow()
        if index < 0 or index >= len(self.search_results):
            return None
        return dict(self.search_results[index])

    def _current_law_article_ref(self):
        if not hasattr(self, "articles_list"):
            return None
        row = self.articles_list.currentRow()
        article_index = self._article_index_from_law_list_row(row)
        if article_index is None:
            return None
        law_row = self.laws_list.currentRow()
        if law_row < 0 or law_row >= len(self.laws):
            return None
        article = self.current_articles[article_index]
        law = self.laws[law_row]
        return {
            "id": article["id"],
            "article_number": article["article_number"],
            "article_title": article["title"] or "",
            "content": article["content"] or "",
            "law_title": law["title"],
            "url": law["url"],
        }

    def _update_favorite_buttons(self):
        search_ref = self._current_search_article_ref()
        if hasattr(self, "search_favorite_button"):
            self.search_favorite_button.setEnabled(search_ref is not None)
            self.search_favorite_button.setText(
                "★  В избранном"
                if search_ref is not None
                and self.profile_store.is_favorite(search_ref, self.active_profile)
                else "☆  В избранное"
            )

        law_ref = self._current_law_article_ref()
        if hasattr(self, "law_favorite_button"):
            self.law_favorite_button.setEnabled(law_ref is not None)
            self.law_favorite_button.setText(
                "★  В избранном"
                if law_ref is not None
                and self.profile_store.is_favorite(law_ref, self.active_profile)
                else "☆  В избранное"
            )

    def toggle_current_search_favorite(self):
        article = self._current_search_article_ref()
        if article is None:
            return
        self.profile_store.toggle_favorite(article, self.active_profile)
        self.refresh_favorites_page()
        self._update_favorite_buttons()
        self.refresh_profile_controls()

    def toggle_current_law_favorite(self):
        article = self._current_law_article_ref()
        if article is None:
            return
        self.profile_store.toggle_favorite(article, self.active_profile)
        self.refresh_favorites_page()
        self._update_favorite_buttons()

    def _record_article_view(self, article):
        if not article:
            return
        self.profile_store.add_recent(article)
        self.refresh_favorites_page()

    def open_article_reference(self, reference):
        if not isinstance(reference, dict):
            return
        row = self.database.get_article_by_reference(
            reference.get("law_title", ""),
            reference.get("article_number", ""),
            reference.get("url", ""),
        )
        if row is None:
            QMessageBox.information(
                self,
                "Статья не найдена",
                "Эта статья отсутствует в текущей локальной базе. Обновите законодательство.",
            )
            return

        result = dict(row)
        self.search_results = [result]
        self.search_input.setText(
            f"{result['article_number']} {result['law_title']}"
        )
        self.search_list.clear()
        self.search_list.addItem(self._favorite_item_text(result))
        self.search_list.setCurrentRow(0)
        self.search_count.setText("Открыто из избранного / истории")
        self.switch_page(self.search_page_index)
        self.show_search_result(0)

    def open_selected_favorite(self):
        item = self.favorites_list.currentItem()
        if item is not None:
            self.open_article_reference(item.data(Qt.ItemDataRole.UserRole))

    def remove_selected_favorite(self):
        item = self.favorites_list.currentItem()
        if item is None:
            return
        reference = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(reference, dict):
            self.profile_store.remove_favorite(reference, self.active_profile)
        self.refresh_favorites_page()
        self._update_favorite_buttons()

    def open_selected_recent(self):
        item = self.recent_articles_list.currentItem()
        if item is not None:
            self.open_article_reference(item.data(Qt.ItemDataRole.UserRole))

    def save_current_profile_runtime(self):
        entries = getattr(self, "penalty_calc_entries", None)
        self.profile_store.save_runtime(
            memo_columns=self.memo_columns,
            calculator_entries=entries,
            name=self.active_profile,
        )

    def restore_active_profile_calculator(self):
        if not hasattr(self, "penalty_calc_entries"):
            return
        self.penalty_calc_entries = self.profile_store.calculator_entries(
            self.active_profile
        )
        self.refresh_penalty_calculator()

    def on_profile_combo_changed(self, _index):
        if not hasattr(self, "profile_combo"):
            return
        name = str(self.profile_combo.currentData() or "").strip()
        if not name or name == self.active_profile:
            return

        self.save_current_profile_runtime()
        self.profile_store.set_active(name)
        self.active_profile = name
        self.memo_columns = self.profile_store.memo_columns(
            self.default_memo_columns(),
            name,
        )
        self.penalty_calc_entries = self.profile_store.calculator_entries(name)
        self.refresh_memo_board()
        self.refresh_memo_overlay_if_open()
        self.refresh_penalty_calculator()
        self.refresh_favorites_page()
        self._update_favorite_buttons()

    def add_user_profile(self):
        default_name = f"Профиль {self.profile_combo.count() + 1}"
        name, ok = QInputDialog.getText(
            self,
            "Новый профиль",
            "Название профиля:",
            text=default_name,
        )
        if not ok:
            return
        try:
            name = self.profile_store.add_profile(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Профили", str(exc))
            return

        self._reload_profile_combo(name)
        self.profile_combo.setCurrentIndex(
            self.profile_combo.findData(name)
        )

    def rename_user_profile(self):
        if not hasattr(self, "profile_combo"):
            return

        old_name = str(self.profile_combo.currentData() or "").strip()
        if not old_name:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать профиль",
            "Новое название профиля:",
            text=old_name,
        )
        if not ok:
            return

        try:
            new_name = self.profile_store.rename_profile(old_name, new_name)
        except ValueError as exc:
            QMessageBox.warning(self, "Профили", str(exc))
            return
        except KeyError:
            QMessageBox.warning(self, "Профили", "Выбранный профиль не найден.")
            return

        self.active_profile = self.profile_store.active_name()
        self._reload_profile_combo(new_name)
        self.refresh_favorites_page()
        self.refresh_memo_board()
        self.refresh_memo_overlay_if_open()
        self.refresh_penalty_calculator()
        self._update_favorite_buttons()
        self.show_save_toast("Профиль переименован")

    def delete_user_profile(self):
        if not hasattr(self, "profile_combo"):
            return

        name = str(self.profile_combo.currentData() or "").strip()
        if not name:
            return

        answer = QMessageBox.question(
            self,
            "Удалить профиль",
            f"Удалить профиль «{name}»?\n\n"
            "Будут удалены его избранные статьи, памятка и сохранённый "
            "набор калькулятора.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.save_current_profile_runtime()

        try:
            new_active = self.profile_store.delete_profile(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Профили", str(exc))
            return
        except KeyError:
            QMessageBox.warning(
                self,
                "Профили",
                "Выбранный профиль уже отсутствует.",
            )
            return

        self.active_profile = new_active

        self._reload_profile_combo(new_active)

        self.memo_columns = self.profile_store.memo_columns(
            self.default_memo_columns(),
            self.active_profile,
        )
        self.penalty_calc_entries = (
            self.profile_store.calculator_entries(
                self.active_profile
            )
        )

        self.refresh_memo_board()
        self.refresh_memo_overlay_if_open()
        self.refresh_penalty_calculator()
        self.refresh_favorites_page()
        self._update_favorite_buttons()
        self.refresh_profile_controls()
        self.show_save_toast("Профиль удалён")

    # =========================================================
    # OPTIONAL UГИБДД CHARTER
    # =========================================================

    def _gibdd_charter_source_type(self):
        value = str(
            self.app_settings.get(
                "gibdd_charter_source_type",
                "file",
            )
            or "file"
        ).strip().lower()
        return value if value in ("file", "url") else "file"

    def _configured_gibdd_charter_path(self):
        source_type = self._gibdd_charter_source_type()
        key = (
            "gibdd_charter_cache_path"
            if source_type == "url"
            else "gibdd_charter_path"
        )
        value = str(self.app_settings.get(key, "") or "").strip()
        if not value:
            return None
        try:
            return Path(value).expanduser()
        except Exception:
            return None

    def _configured_gibdd_charter_url(self):
        if self._gibdd_charter_source_type() != "url":
            return ""
        return str(
            self.app_settings.get("gibdd_charter_url", "") or ""
        ).strip()

    @staticmethod
    def _gibdd_charter_file_signature(path):
        if path is None:
            return None
        try:
            stat = Path(path).stat()
            return (
                str(Path(path).resolve()),
                int(stat.st_mtime_ns),
                int(stat.st_size),
            )
        except (OSError, FileNotFoundError):
            return None

    def _gibdd_charter_source_description(self):
        if self._gibdd_charter_source_type() == "url":
            url = self._configured_gibdd_charter_url()
            if "docs.google.com" in url.lower():
                return "Google Документ"
            return "Ссылка / веб-страница"
        return "Локальный DOCX"

    def _refresh_page_indexes(self):
        pairs = (
            ("search_page_index", "search_page"),
            ("laws_page_index", "laws_page"),
            ("favorites_page_index", "favorites_page"),
            ("gibdd_charter_page_index", "gibdd_charter_page"),
            ("assistant_page_index", "assistant_page"),
            ("memo_page_index", "memo_page"),
            ("calculator_page_index", "calculator_page"),
            ("update_page_index", "update_page"),
            ("update_history_page_index", "update_history_page"),
            ("ahk_page_index", "ahk_page"),
            ("community_page_index", "community_page"),
            ("settings_page_index", "settings_page"),
        )
        for index_name, page_name in pairs:
            page = getattr(self, page_name, None)
            setattr(
                self,
                index_name,
                self.pages.indexOf(page) if page is not None else None,
            )

    def start_gibdd_charter_watcher(self):
        """Watch local/cache files and periodically refresh URL sources."""
        self.gibdd_charter_watcher = QFileSystemWatcher(self)
        self.gibdd_charter_watcher.directoryChanged.connect(
            lambda _path: self._schedule_gibdd_charter_sync(180)
        )
        self.gibdd_charter_watcher.fileChanged.connect(
            lambda _path: self._schedule_gibdd_charter_sync(220)
        )

        self.gibdd_charter_sync_timer = QTimer(self)
        self.gibdd_charter_sync_timer.setSingleShot(True)
        self.gibdd_charter_sync_timer.timeout.connect(
            self.sync_gibdd_charter_tab
        )

        self.gibdd_charter_poll_timer = QTimer(self)
        self.gibdd_charter_poll_timer.setInterval(2000)
        self.gibdd_charter_poll_timer.timeout.connect(
            self.sync_gibdd_charter_tab
        )
        self.gibdd_charter_poll_timer.start()

        self.gibdd_charter_remote_timer = QTimer(self)
        self.gibdd_charter_remote_timer.setInterval(
            self.gibdd_charter_remote_interval_ms
        )
        self.gibdd_charter_remote_timer.timeout.connect(
            lambda: self.refresh_gibdd_charter_url(manual=False)
        )

        self._refresh_gibdd_charter_file_watch()
        self._update_gibdd_charter_remote_timer()

        if self._gibdd_charter_source_type() == "url":
            QTimer.singleShot(
                7500,
                lambda: self.refresh_gibdd_charter_url(manual=False),
            )

    def _update_gibdd_charter_remote_timer(self):
        timer = getattr(self, "gibdd_charter_remote_timer", None)
        if timer is None:
            return
        if (
            self._gibdd_charter_source_type() == "url"
            and self._configured_gibdd_charter_url()
        ):
            if not timer.isActive():
                timer.start()
        else:
            timer.stop()

    def _schedule_gibdd_charter_sync(self, delay_ms=180):
        timer = getattr(self, "gibdd_charter_sync_timer", None)
        if timer is None:
            return
        timer.start(max(50, int(delay_ms)))

    def _refresh_gibdd_charter_file_watch(self):
        watcher = getattr(self, "gibdd_charter_watcher", None)
        if watcher is None:
            return

        candidate = self._configured_gibdd_charter_path()
        desired_file = None
        desired_dir = None

        if candidate is not None:
            try:
                parent = candidate.parent
                if parent.exists():
                    desired_dir = str(parent.resolve())
                if candidate.is_file():
                    desired_file = str(candidate.resolve())
            except OSError:
                pass

        for watched in list(watcher.files()):
            if watched != desired_file:
                try:
                    watcher.removePath(watched)
                except Exception:
                    pass

        for watched in list(watcher.directories()):
            if watched != desired_dir:
                try:
                    watcher.removePath(watched)
                except Exception:
                    pass

        if desired_dir and desired_dir not in watcher.directories():
            try:
                watcher.addPath(desired_dir)
            except Exception:
                pass

        if desired_file and desired_file not in watcher.files():
            try:
                watcher.addPath(desired_file)
            except Exception:
                pass

    def refresh_gibdd_charter_settings_ui(self):
        source_type = self._gibdd_charter_source_type()
        configured = self._configured_gibdd_charter_path()
        source_url = self._configured_gibdd_charter_url()

        if hasattr(self, "settings_charter_path"):
            local_value = str(
                self.app_settings.get("gibdd_charter_path", "") or ""
            )
            self.settings_charter_path.setText(
                local_value if source_type == "file" else ""
            )

        if hasattr(self, "settings_charter_url"):
            self.settings_charter_url.blockSignals(True)
            if source_type == "url" and not self.settings_charter_url.hasFocus():
                self.settings_charter_url.setText(source_url)
            elif source_type != "url" and not self.settings_charter_url.hasFocus():
                self.settings_charter_url.clear()
            self.settings_charter_url.blockSignals(False)

        exists = bool(configured is not None and configured.is_file())
        loaded = bool(
            self.gibdd_charter_document is not None
            and (
                exists
                or source_type == "url"
            )
        )

        if source_type == "url" and source_url:
            if loaded:
                count = len(
                    getattr(
                        self.gibdd_charter_document,
                        "articles",
                        [],
                    )
                )
                status = (
                    f"Подключено по ссылке • {self._gibdd_charter_source_description()} "
                    f"• статей: {count}. Источник проверяется каждые 5 минут."
                )
            elif self.gibdd_charter_error:
                status = (
                    "Ссылка сохранена, но сейчас источник недоступен: "
                    f"{self.gibdd_charter_error}"
                )
            else:
                status = "Ссылка сохранена. Загружаю Устав…"
        elif source_type == "file":
            if configured is None:
                status = (
                    "Устав не подключён. Выберите DOCX или вставьте ссылку "
                    "на Google Документ, прямой DOCX либо страницу форума."
                )
            elif loaded:
                count = len(
                    getattr(
                        self.gibdd_charter_document,
                        "articles",
                        [],
                    )
                )
                status = (
                    f"Подключён файл: {configured.name} • статей: {count}"
                )
            elif not exists:
                status = (
                    "Выбранный файл сейчас не найден. Если вернуть его "
                    "по сохранённому пути, вкладка появится снова."
                )
            elif self.gibdd_charter_error:
                status = (
                    "Не удалось прочитать выбранный DOCX: "
                    f"{self.gibdd_charter_error}"
                )
            else:
                status = "DOCX выбран, выполняется загрузка…"
        else:
            status = "Устав не подключён."

        if hasattr(self, "settings_charter_status"):
            self.settings_charter_status.setText(status)

        if hasattr(self, "settings_charter_open_button"):
            can_open = bool(
                (source_type == "url" and source_url)
                or (source_type == "file" and exists)
            )
            self.settings_charter_open_button.setEnabled(can_open)
            self.settings_charter_open_button.setText(
                "Открыть источник"
                if source_type == "url"
                else "Открыть выбранный файл"
            )

        if hasattr(self, "settings_charter_refresh_url_button"):
            self.settings_charter_refresh_url_button.setEnabled(
                bool(source_type == "url" and source_url)
            )

        if hasattr(self, "settings_charter_clear_button"):
            self.settings_charter_clear_button.setEnabled(
                bool(
                    configured is not None
                    or source_url
                )
            )

    def select_gibdd_charter_file(self):
        configured = (
            self._configured_gibdd_charter_path()
            if self._gibdd_charter_source_type() == "file"
            else None
        )
        if configured is not None:
            start_dir = configured.parent
        else:
            start_dir = Path.home() / "Downloads"
            if not start_dir.exists():
                start_dir = Path.home()

        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Выберите Устав",
            str(start_dir),
            "Документы Word (*.docx);;Все файлы (*.*)",
        )
        if not file_name:
            return

        candidate = Path(file_name)
        if candidate.suffix.lower() != ".docx":
            QMessageBox.warning(
                self,
                "Устав",
                "Выберите файл Устава в формате DOCX.",
            )
            return

        try:
            document = GibddCharterParser().parse(candidate)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Устав",
                "Не удалось подключить выбранный DOCX.\n\n"
                f"{exc}",
            )
            return

        try:
            saved_path = str(candidate.resolve())
        except OSError:
            saved_path = str(candidate.absolute())

        self.app_settings.update(
            {
                "gibdd_charter_source_type": "file",
                "gibdd_charter_path": saved_path,
                "gibdd_charter_url": "",
                "gibdd_charter_cache_path": "",
            }
        )
        self.save_app_settings()

        self.gibdd_charter_source_type = "file"
        self.gibdd_charter_source_url = ""
        self.gibdd_charter_path = Path(saved_path)
        self.gibdd_charter_document = document
        self.gibdd_charter_signature = (
            self._gibdd_charter_file_signature(
                self.gibdd_charter_path
            )
        )
        self.gibdd_charter_error = ""

        if (
            self.gibdd_charter_page is None
            or self.gibdd_charter_nav is None
        ):
            self._install_gibdd_charter_tab()
        else:
            self._reload_gibdd_charter_page()

        self._refresh_gibdd_charter_file_watch()
        self._update_gibdd_charter_remote_timer()
        self.refresh_gibdd_charter_settings_ui()

        if hasattr(self, "settings_status"):
            self.settings_status.setText(
                "Устав подключён из DOCX. Вкладка «Устав» добавлена."
            )
        self.play_ui_sound("success")
        self.show_save_toast("Устав подключён")

    def connect_gibdd_charter_url(self):
        if not hasattr(self, "settings_charter_url"):
            return
        url = self.settings_charter_url.text().strip()
        if not url:
            QMessageBox.information(
                self,
                "Устав",
                "Вставьте ссылку на Google Документ, DOCX или страницу форума.",
            )
            return

        try:
            normalized = normalize_charter_url(url)
        except Exception as exc:
            QMessageBox.warning(self, "Устав", str(exc))
            return

        self.settings_charter_url.setText(normalized)
        self._start_gibdd_charter_url_worker(
            normalized,
            manual=True,
        )

    def refresh_gibdd_charter_url(self, manual=False):
        url = self._configured_gibdd_charter_url()
        if not url:
            if manual:
                QMessageBox.information(
                    self,
                    "Устав",
                    "Сначала подключите Устав по ссылке.",
                )
            return
        self._start_gibdd_charter_url_worker(url, manual=manual)

    def _start_gibdd_charter_url_worker(self, url, manual=False):
        if (
            self.gibdd_charter_url_worker is not None
            and self.gibdd_charter_url_worker.isRunning()
        ):
            if manual and hasattr(self, "settings_charter_status"):
                self.settings_charter_status.setText(
                    "Устав по ссылке уже загружается…"
                )
            return

        cache_dir = Path("data") / "charter_cache"
        worker = CharterUrlWorker(
            url,
            cache_dir,
            manual=manual,
            parent=self,
        )
        self.gibdd_charter_url_worker = worker
        worker.loaded.connect(self._on_gibdd_charter_url_loaded)
        worker.failed.connect(
            lambda message, manual=manual:
            self._on_gibdd_charter_url_failed(message, manual)
        )
        worker.finished.connect(
            self._on_gibdd_charter_url_worker_finished
        )

        if hasattr(self, "settings_charter_status"):
            self.settings_charter_status.setText(
                "Загружаю и проверяю Устав по ссылке…"
            )
        if hasattr(self, "settings_charter_connect_url_button"):
            self.settings_charter_connect_url_button.setEnabled(False)

        worker.start()

    def _on_gibdd_charter_url_worker_finished(self):
        if hasattr(self, "settings_charter_connect_url_button"):
            self.settings_charter_connect_url_button.setEnabled(True)

    def _on_gibdd_charter_url_loaded(self, result):
        url = str(result.get("url") or "").strip()
        document = result.get("document")
        cache_path = Path(str(result.get("cache_path") or ""))
        source_kind = str(result.get("source_kind") or "web_page")
        manual = bool(result.get("manual", False))

        # Ignore a late background response after the user switched back to a
        # local DOCX or entered a different URL.
        current_url = ""
        if hasattr(self, "settings_charter_url"):
            current_url = self.settings_charter_url.text().strip()
        saved_url = self._configured_gibdd_charter_url()
        if saved_url and saved_url != url and current_url != url:
            return

        self.app_settings.update(
            {
                "gibdd_charter_source_type": "url",
                "gibdd_charter_url": url,
                "gibdd_charter_cache_path": str(cache_path),
                "gibdd_charter_path": "",
            }
        )
        self.save_app_settings()

        self.gibdd_charter_source_type = "url"
        self.gibdd_charter_source_url = url
        self.gibdd_charter_path = cache_path
        self.gibdd_charter_document = document
        self.gibdd_charter_signature = (
            self._gibdd_charter_file_signature(cache_path)
        )
        self.gibdd_charter_error = ""

        if (
            self.gibdd_charter_page is None
            or self.gibdd_charter_nav is None
        ):
            self._install_gibdd_charter_tab()
        else:
            self._reload_gibdd_charter_page()

        self._refresh_gibdd_charter_file_watch()
        self._update_gibdd_charter_remote_timer()
        self.refresh_gibdd_charter_settings_ui()

        if hasattr(self, "settings_status"):
            kind_label = {
                "google_docs": "Google Документа",
                "docx_url": "DOCX-ссылки",
                "web_page": "веб-страницы / форума",
            }.get(source_kind, "ссылки")
            self.settings_status.setText(
                (
                    f"Устав подключён из {kind_label}."
                    if manual
                    else f"Устав автоматически обновлён из {kind_label}."
                )
            )

        # Background checks run every five minutes. They must stay completely
        # silent: no "Сохранено" popup and no success sound when the user did
        # not perform an action.
        if manual:
            self.play_ui_sound("success")
            self.show_save_toast("Устав обновлён")

    def _on_gibdd_charter_url_failed(self, message, manual=False):
        self.gibdd_charter_error = str(message)
        self.refresh_gibdd_charter_settings_ui()
        if manual:
            QMessageBox.warning(
                self,
                "Не удалось подключить Устав",
                str(message),
            )

    def clear_gibdd_charter_selection(self):
        self.app_settings.update(
            {
                "gibdd_charter_source_type": "file",
                "gibdd_charter_path": "",
                "gibdd_charter_url": "",
                "gibdd_charter_cache_path": "",
            }
        )
        self.save_app_settings()

        if (
            self.gibdd_charter_page is not None
            or self.gibdd_charter_nav is not None
        ):
            self._remove_gibdd_charter_tab()

        self.gibdd_charter_source_type = "file"
        self.gibdd_charter_source_url = ""
        self.gibdd_charter_path = None
        self.gibdd_charter_document = None
        self.gibdd_charter_signature = None
        self.gibdd_charter_error = ""

        self._refresh_gibdd_charter_file_watch()
        self._update_gibdd_charter_remote_timer()
        self.refresh_gibdd_charter_settings_ui()

        if hasattr(self, "settings_status"):
            self.settings_status.setText(
                "Устав отключён. Исходный файл или ссылка не изменены."
            )
        self.play_ui_sound("toggle")

    def open_selected_gibdd_charter_from_settings(self):
        if self._gibdd_charter_source_type() == "url":
            url = self._configured_gibdd_charter_url()
            if not url:
                QMessageBox.warning(
                    self,
                    "Устав",
                    "Ссылка на источник Устава не сохранена.",
                )
                return
            webbrowser.open(url)
            return

        path = self._configured_gibdd_charter_path()
        if path is None or not path.is_file():
            QMessageBox.warning(
                self,
                "Устав",
                "Выбранный файл Устава сейчас недоступен.",
            )
            return
        try:
            webbrowser.open(path.resolve().as_uri())
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Устав",
                f"Не удалось открыть DOCX:\n{exc}",
            )

    def sync_gibdd_charter_tab(self):
        candidate = self._configured_gibdd_charter_path()
        source_type = self._gibdd_charter_source_type()

        if candidate is None:
            # For a URL source without a cache yet, keep waiting for the worker.
            if source_type == "url" and self._configured_gibdd_charter_url():
                self.refresh_gibdd_charter_settings_ui()
                return

            if (
                self.gibdd_charter_page is not None
                or self.gibdd_charter_nav is not None
            ):
                self._remove_gibdd_charter_tab()

            self.gibdd_charter_path = None
            self.gibdd_charter_document = None
            self.gibdd_charter_signature = None
            self.gibdd_charter_error = ""
            self._refresh_gibdd_charter_file_watch()
            self.refresh_gibdd_charter_settings_ui()
            return

        self.gibdd_charter_path = candidate

        if not candidate.is_file():
            # Remote source: don't throw away a previously loaded good document
            # merely because its cache disappeared temporarily.
            if source_type != "url":
                if (
                    self.gibdd_charter_page is not None
                    or self.gibdd_charter_nav is not None
                ):
                    self._remove_gibdd_charter_tab()
                self.gibdd_charter_document = None

            self.gibdd_charter_signature = None
            self.gibdd_charter_error = (
                "Локальная копия Устава недоступна."
                if source_type == "url"
                else "Выбранный файл Устава не найден."
            )
            self._refresh_gibdd_charter_file_watch()
            self.refresh_gibdd_charter_settings_ui()
            return

        signature = self._gibdd_charter_file_signature(candidate)
        if (
            self.gibdd_charter_document is not None
            and signature is not None
            and signature == self.gibdd_charter_signature
        ):
            self._refresh_gibdd_charter_file_watch()
            self.refresh_gibdd_charter_settings_ui()
            return

        try:
            if candidate.suffix.lower() == ".txt":
                document = GibddCharterParser().parse_text(
                    candidate.read_text(encoding="utf-8"),
                    path=candidate,
                )
            else:
                document = GibddCharterParser().parse(candidate)
        except Exception as exc:
            self.gibdd_charter_error = str(exc)
            self._refresh_gibdd_charter_file_watch()
            self.refresh_gibdd_charter_settings_ui()
            if source_type == "file":
                self._schedule_gibdd_charter_sync(900)
            return

        self.gibdd_charter_document = document
        self.gibdd_charter_signature = signature
        self.gibdd_charter_error = ""

        if (
            self.gibdd_charter_page is None
            or self.gibdd_charter_nav is None
        ):
            self._install_gibdd_charter_tab()
        else:
            self._reload_gibdd_charter_page()

        self._refresh_gibdd_charter_file_watch()
        self.refresh_gibdd_charter_settings_ui()

    def _install_gibdd_charter_tab(self):
        if self.gibdd_charter_document is None:
            return
        if self.gibdd_charter_nav is not None or self.gibdd_charter_page is not None:
            return

        nav = self.nav_button("🚓  Устав")
        if self._gibdd_charter_source_type() == "url":
            nav.setToolTip(
                f"Источник: {self._gibdd_charter_source_description()}"
            )
        else:
            nav.setToolTip(
                f"Локальный документ: {self.gibdd_charter_path.name}"
            )
        nav.setCheckable(True)
        nav.setAutoExclusive(True)
        nav.setObjectName("navButton")
        nav.clicked.connect(self._open_gibdd_charter_page)
        self.gibdd_charter_nav = nav

        # Place the button after Favorites and before RP-помощником.
        insert_at = self.sidebar_layout.indexOf(self.assistant_nav)
        if insert_at < 0:
            self.sidebar_layout.addWidget(nav)
        else:
            self.sidebar_layout.insertWidget(insert_at, nav)

        page = self.create_gibdd_charter_page()
        self.gibdd_charter_page = page

        # Keep stacked-widget order aligned with the visible navigation.
        insert_page_at = self.pages.indexOf(self.favorites_page) + 1
        self.pages.insertWidget(insert_page_at, page)
        self._refresh_page_indexes()

        try:
            favorites_nav_pos = self.nav_buttons.index(self.favorites_nav)
            self.nav_buttons.insert(favorites_nav_pos + 1, nav)
        except (ValueError, AttributeError):
            self.nav_buttons.append(nav)

        self.refresh_button_sounds()
        self.update_active_nav(self.pages.currentIndex())

    def _open_gibdd_charter_page(self):
        page = getattr(self, "gibdd_charter_page", None)
        if page is None:
            return
        index = self.pages.indexOf(page)
        if index >= 0:
            self.switch_page(index)

    def _remove_gibdd_charter_tab(self):
        page = getattr(self, "gibdd_charter_page", None)
        nav = getattr(self, "gibdd_charter_nav", None)

        if page is not None and self.pages.currentWidget() is page:
            self.switch_page(self.pages.indexOf(self.laws_page))

        if nav is not None:
            try:
                self.nav_buttons.remove(nav)
            except (ValueError, AttributeError):
                pass
            self.sidebar_layout.removeWidget(nav)
            nav.setParent(None)
            nav.deleteLater()

        if page is not None:
            self.pages.removeWidget(page)
            page.setParent(None)
            page.deleteLater()

        self.gibdd_charter_nav = None
        self.gibdd_charter_page = None
        self.gibdd_charter_page_index = None
        self.gibdd_charter_articles = []
        self.gibdd_charter_chapter_rows = {}
        self.gibdd_charter_chapter_buttons = {}
        self._refresh_page_indexes()
        self.update_active_nav(self.pages.currentIndex())

    def _reload_gibdd_charter_page(self):
        if self.gibdd_charter_document is None or self.gibdd_charter_page is None:
            return

        if self.gibdd_charter_nav is not None:
            if self._gibdd_charter_source_type() == "url":
                self.gibdd_charter_nav.setToolTip(
                    f"Источник: {self._gibdd_charter_source_description()}"
                )
            else:
                self.gibdd_charter_nav.setToolTip(
                    f"Локальный документ: {self.gibdd_charter_path.name}"
                )

        doc = self.gibdd_charter_document
        if self._gibdd_charter_source_type() == "url":
            metadata_lines = [
                f"Источник: {self._gibdd_charter_source_description()} — "
                "проверяется автоматически каждые 5 минут."
            ]
        else:
            metadata_lines = [
                "Выбранный DOCX — изменения файла отслеживаются автоматически."
            ]
        if doc.approval:
            metadata_lines.append(doc.approval)
        if doc.amendment:
            metadata_lines.append(doc.amendment)
        if hasattr(self, "gibdd_charter_meta"):
            self.gibdd_charter_meta.setText("\n".join(metadata_lines))
            self.gibdd_charter_meta.setToolTip(
                self._configured_gibdd_charter_url()
                if self._gibdd_charter_source_type() == "url"
                else str(doc.path)
            )

        if hasattr(self, "gibdd_charter_article_title"):
            self.gibdd_charter_article_title.setText("Выберите статью")
        if hasattr(self, "gibdd_charter_content"):
            self.gibdd_charter_content.clear()

        self._populate_gibdd_charter()
        for row in range(self.gibdd_charter_list.count()):
            if self._gibdd_article_from_row(row) is not None:
                self.gibdd_charter_list.setCurrentRow(row)
                break

    def create_gibdd_charter_page(self):
        """Create the local UГИБДД charter viewer.

        The page is instantiated only when self.gibdd_charter_document exists,
        so no empty/dead sidebar entry is ever shown when the DOCX is absent.
        """
        page = QWidget()
        page.setObjectName("gibddCharterPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(10)

        title = QLabel("Устав")
        title.setObjectName("pageTitle")

        self.gibdd_chapters_scroll = QScrollArea()
        self.gibdd_chapters_scroll.setObjectName("lawSectionsScroll")
        self.gibdd_chapters_scroll.setWidgetResizable(True)
        self.gibdd_chapters_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.gibdd_chapters_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.gibdd_chapters_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.gibdd_chapters_scroll.setFixedHeight(48)
        self.gibdd_chapters_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self.gibdd_chapters_container = QWidget()
        self.gibdd_chapters_container.setObjectName("lawSectionsContainer")
        self.gibdd_chapters_layout = QHBoxLayout(self.gibdd_chapters_container)
        self.gibdd_chapters_layout.setContentsMargins(0, 2, 0, 2)
        self.gibdd_chapters_layout.setSpacing(6)
        self.gibdd_chapters_layout.addStretch()
        self.gibdd_chapters_scroll.setWidget(self.gibdd_chapters_container)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(18)
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(
            self.gibdd_chapters_scroll,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        layout.addLayout(header)

        if self._gibdd_charter_source_type() == "url":
            metadata_lines = [
                f"Источник: {self._gibdd_charter_source_description()} — "
                "проверяется автоматически."
            ]
        else:
            metadata_lines = [
                "Выбранный DOCX — файл можно хранить в любой папке. "
                "Изменения отслеживаются автоматически."
            ]
        doc = self.gibdd_charter_document
        if doc.approval:
            metadata_lines.append(doc.approval)
        if doc.amendment:
            metadata_lines.append(doc.amendment)
        self.gibdd_charter_meta = QLabel("\n".join(metadata_lines))
        self.gibdd_charter_meta.setObjectName("muted")
        self.gibdd_charter_meta.setWordWrap(True)
        self.gibdd_charter_meta.setToolTip(str(doc.path))
        layout.addWidget(self.gibdd_charter_meta)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.gibdd_charter_list = QListWidget()
        self.gibdd_charter_list.setObjectName("gibddCharterList")

        content_panel = QWidget()
        content_layout = QVBoxLayout(content_panel)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        self.gibdd_charter_article_title = QLabel("Выберите статью")
        self.gibdd_charter_article_title.setObjectName("articleHeading")
        self.gibdd_charter_article_title.setWordWrap(True)

        self.gibdd_charter_content = QTextBrowser()
        self.gibdd_charter_content.setObjectName("gibddCharterContent")

        button_row = QHBoxLayout()
        self.gibdd_charter_copy_button = QPushButton("Копировать статью")
        self.gibdd_charter_open_button = QPushButton("Открыть DOCX")
        button_row.addWidget(self.gibdd_charter_copy_button)
        button_row.addWidget(self.gibdd_charter_open_button)
        button_row.addStretch()

        content_layout.addWidget(self.gibdd_charter_article_title)
        content_layout.addWidget(self.gibdd_charter_content, stretch=1)
        content_layout.addLayout(button_row)

        splitter.addWidget(self.gibdd_charter_list)
        splitter.addWidget(content_panel)
        splitter.setSizes([430, 800])
        layout.addWidget(splitter, stretch=1)

        self._populate_gibdd_charter()

        self.gibdd_charter_list.currentRowChanged.connect(
            self.show_gibdd_charter_article
        )
        self.gibdd_charter_copy_button.clicked.connect(
            self.copy_gibdd_charter_article
        )
        self.gibdd_charter_open_button.clicked.connect(
            self.open_gibdd_charter_file
        )

        # Open the first article on first visit.
        for row in range(self.gibdd_charter_list.count()):
            if self._gibdd_article_from_row(row) is not None:
                self.gibdd_charter_list.setCurrentRow(row)
                break

        return page

    def _populate_gibdd_charter(self):
        self.gibdd_charter_list.clear()
        self.gibdd_charter_articles = []
        self.gibdd_charter_chapter_rows = {}
        self.gibdd_charter_chapter_buttons = {}

        while self.gibdd_chapters_layout.count():
            item = self.gibdd_chapters_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for chapter in self.gibdd_charter_document.chapters:
            chapter_title = chapter.display_title

            button = QPushButton(self._compact_section_button_text(chapter_title))
            button.setObjectName("lawSectionButton")
            button.setCheckable(True)
            button.setToolTip(chapter_title)
            button.clicked.connect(
                lambda checked=False, title=chapter_title:
                self.jump_to_gibdd_chapter(title)
            )
            self.gibdd_chapters_layout.addWidget(button)
            self.gibdd_charter_chapter_buttons[chapter_title] = button

            header = QListWidgetItem(chapter_title)
            header.setData(
                Qt.ItemDataRole.UserRole,
                {"type": "chapter", "chapter": chapter_title},
            )
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = header.font()
            font.setBold(True)
            font.setPointSize(font.pointSize() + 1)
            header.setFont(font)
            header.setForeground(QColor("#6d8cff"))
            header.setToolTip(chapter_title)
            self.gibdd_charter_list.addItem(header)
            self.gibdd_charter_chapter_rows[chapter_title] = (
                self.gibdd_charter_list.count() - 1
            )

            for article in chapter.articles:
                article_index = len(self.gibdd_charter_articles)
                self.gibdd_charter_articles.append(article)
                label = f"Статья {article.number}"
                if article.title:
                    label += "\n" + article.title
                item = QListWidgetItem(label)
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    {
                        "type": "article",
                        "article_index": article_index,
                        "chapter": chapter_title,
                    },
                )
                self.gibdd_charter_list.addItem(item)

        self.gibdd_chapters_layout.addStretch()

    def _gibdd_article_from_row(self, row):
        if row < 0 or row >= self.gibdd_charter_list.count():
            return None
        item = self.gibdd_charter_list.item(row)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("type") != "article":
            return None
        index = data.get("article_index")
        if not isinstance(index, int):
            return None
        if not (0 <= index < len(self.gibdd_charter_articles)):
            return None
        return self.gibdd_charter_articles[index]

    def show_gibdd_charter_article(self, row):
        article = self._gibdd_article_from_row(row)
        if article is None:
            return

        title = f"Статья {article.number}"
        if article.title:
            title += "\n" + article.title
        self.gibdd_charter_article_title.setText(title)
        self.gibdd_charter_content.setPlainText(article.content)

        chapter_title = f"Глава {article.chapter_number}. {article.chapter_title}"
        self._set_active_gibdd_chapter(chapter_title)

    def _set_active_gibdd_chapter(self, chapter_title):
        for title, button in self.gibdd_charter_chapter_buttons.items():
            button.blockSignals(True)
            button.setChecked(title == chapter_title)
            button.blockSignals(False)

    def jump_to_gibdd_chapter(self, chapter_title):
        row = self.gibdd_charter_chapter_rows.get(chapter_title)
        if row is None:
            return

        first_article_row = row + 1
        while first_article_row < self.gibdd_charter_list.count():
            item = self.gibdd_charter_list.item(first_article_row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and data.get("type") == "article":
                self.gibdd_charter_list.setCurrentRow(first_article_row)
                break
            if isinstance(data, dict) and data.get("type") == "chapter":
                break
            first_article_row += 1

        header_item = self.gibdd_charter_list.item(row)
        if header_item is not None:
            QTimer.singleShot(
                0,
                lambda item=header_item: self.gibdd_charter_list.scrollToItem(
                    item,
                    QAbstractItemView.ScrollHint.PositionAtTop,
                ),
            )
        self._set_active_gibdd_chapter(chapter_title)

    def copy_gibdd_charter_article(self):
        row = self.gibdd_charter_list.currentRow()
        article = self._gibdd_article_from_row(row)
        if article is None:
            return
        heading = f"Статья {article.number}. {article.title}".strip()
        text = heading + "\n\n" + article.content
        QApplication.clipboard().setText(text.strip())
        self.play_ui_sound("success")
        self.show_save_toast("Скопировано")

    def open_gibdd_charter_file(self):
        if self._gibdd_charter_source_type() == "url":
            url = self._configured_gibdd_charter_url()
            if url:
                webbrowser.open(url)
                return

        path = self.gibdd_charter_path
        if path is None or not Path(path).exists():
            QMessageBox.warning(
                self,
                "Устав",
                "Источник Устава сейчас недоступен. Выберите другой "
                "файл или ссылку в Настройках.",
            )
            return
        try:
            webbrowser.open(Path(path).resolve().as_uri())
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Устав",
                f"Не удалось открыть источник:\n{exc}",
            )

    # =========================================================
    # PLACEHOLDER
    # =========================================================

    # =========================================================
    # SETTINGS v0.8
    # =========================================================

    def load_app_settings(self):
        defaults = {
            "memo_hotkey": "F8",
            "search_hotkey": "F7",
            "calculator_hotkey": "F9",
            "theme": "dark",
            "visual_theme": "default",
            "global_memo_hotkey": True,
            "global_search_hotkey": True,
            "global_calculator_hotkey": True,
            "block_quick_hotkeys_when_main_open": True,
            "memo_always_on_top": True,
            "search_overlay_geometry": "",
            "calculator_overlay_geometry": "",
            "show_penalties": True,
            "confirm_delete_column": True,
            "search_limit": 100,
            "remember_memo_layout": True,
            "overlay_geometry": "",
            "overlay_column_sizes": [],
            "overlay_section_sizes": {},
            "memo_main_sizes": [650, 220],
            "memo_column_sizes": [],
            "memo_section_sizes": {},
            "overlay_opacity": 100,
            "search_overlay_opacity": 100,
            "memo_overlay_opacity": 100,
            "calculator_overlay_opacity": 100,
            "program_font_size": 14,
            "overlay_click_through": False,
            "overlay_width": 1250,
            "overlay_height": 650,
            "memo_card_font_size": 14,
            "memo_card_min_height": 72,
            "show_article_summary": True,
            "show_article_code": True,
            "enter_runs_search": True,
            "double_click_opens_article": True,
            "ui_sounds": True,
            "report_reply_voice": True,
            "report_reply_seen_ids": [],
            "onboarding_completed": False,
            "initial_database_notice_dismissed": False,
            "auto_check_program_updates": True,
            "auto_update_laws_on_startup": True,
            "law_update_interval_hours": 6,
            "last_auto_law_update_at": 0,
            "update_channel": load_update_config().get("channel", "stable"),
            "last_seen_law_update_run": 0,
            # User-selected DOCX; the file can live anywhere on disk.
            "gibdd_charter_path": "",
            "gibdd_charter_source_type": "file",
            "gibdd_charter_url": "",
            "gibdd_charter_cache_path": "",
            # X button behavior:
            #   ask      -> show the choice dialog
            #   minimize -> minimize to the Windows taskbar
            #   exit     -> close DeiLaw completely
            "close_behavior": "ask",
            "remember_close_choice": False,
        }
        saved = {}
        try:
            if self.settings_path.exists():
                saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    defaults.update(saved)
                else:
                    saved = {}
        except Exception:
            saved = {}

        # v0.3.1 migration: the old single opacity becomes the initial value
        # for all three Quick windows until the user saves them independently.
        legacy_opacity = max(40, min(100, int(defaults.get("overlay_opacity", 100) or 100)))
        for key in (
            "search_overlay_opacity",
            "memo_overlay_opacity",
            "calculator_overlay_opacity",
        ):
            if key not in saved:
                defaults[key] = legacy_opacity
        return defaults

    def save_app_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(self.app_settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_settings_page(self):
        page = QWidget()
        page.setObjectName("settingsPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        self.settings_scroll = scroll
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setObjectName("settingsViewport")
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget()
        content.setObjectName("settingsContent")
        content.setMinimumWidth(0)
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred
        )
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        def add_setting_separator(layout):
            line = QFrame()
            line.setObjectName("settingsSeparator")
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Plain)
            line.setFixedHeight(1)
            layout.addWidget(line)

        def settings_label(text_value):
            label = QLabel(text_value)
            label.setWordWrap(True)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred
            )
            return label
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(14)

        title = QLabel("Настройки")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Настройка DeiLaw, быстрых окон, Устава, обновлений и горячих клавиш."
        )
        subtitle.setObjectName("muted")
        root.addWidget(title)
        root.addWidget(subtitle)

        controls_card = QFrame()
        controls_card.setObjectName("card")
        controls_layout = QVBoxLayout(controls_card)
        controls_title = QLabel("Управление программой")
        controls_title.setObjectName("sectionTitle")
        controls_layout.addWidget(controls_title)

        controls_hint = QLabel(
            "Основные клавиши и поведение интерфейса DeiLaw."
        )
        controls_hint.setObjectName("muted")
        controls_layout.addWidget(controls_hint)

        hotkey_main_row = QHBoxLayout()
        hotkey_main_row.addWidget(QLabel("Показать / скрыть RP Quick Memo"))
        hotkey_main_row.addStretch()
        self.settings_hotkey = SingleHotkeyEdit(
            SingleHotkeyEdit.sequence_from_spec(
                self.app_settings.get("memo_hotkey", "F8")
            )
        )
        self.settings_hotkey.setMaximumWidth(220)
        hotkey_main_row.addWidget(self.settings_hotkey)
        controls_layout.addLayout(hotkey_main_row)
        add_setting_separator(controls_layout)

        hotkey_rule_hint = QLabel(
            "Бинд: одна клавиша или Ctrl/Alt/Shift/Win + одна клавиша. "
            "NumPad определяется отдельно: Num+1 не равен обычной 1."
        )
        hotkey_rule_hint.setObjectName("muted")
        hotkey_rule_hint.setWordWrap(True)
        controls_layout.addWidget(hotkey_rule_hint)
        add_setting_separator(controls_layout)

        self.settings_global_hotkey = StatusCheckBox(
            "Глобальный бинд — работает в игре, когда DeiLaw свёрнут/в трее"
        )
        self.settings_global_hotkey.setChecked(
            bool(self.app_settings.get("global_memo_hotkey", True))
        )
        controls_layout.addWidget(self.settings_global_hotkey)
        add_setting_separator(controls_layout)

        search_hotkey_row = QHBoxLayout()
        search_hotkey_row.addWidget(QLabel("Показать / скрыть быстрый поисковик"))
        search_hotkey_row.addStretch()
        self.settings_search_hotkey = SingleHotkeyEdit(
            SingleHotkeyEdit.sequence_from_spec(
                self.app_settings.get("search_hotkey", "F7")
            )
        )
        self.settings_search_hotkey.setMaximumWidth(220)
        search_hotkey_row.addWidget(self.settings_search_hotkey)
        controls_layout.addLayout(search_hotkey_row)
        add_setting_separator(controls_layout)

        self.settings_global_search_hotkey = StatusCheckBox(
            "Глобальный бинд поисковика — работает в игре, когда DeiLaw свёрнут/в трее"
        )
        self.settings_global_search_hotkey.setChecked(
            bool(self.app_settings.get("global_search_hotkey", True))
        )
        controls_layout.addWidget(self.settings_global_search_hotkey)
        add_setting_separator(controls_layout)

        calculator_hotkey_row = QHBoxLayout()
        calculator_hotkey_row.addWidget(
            QLabel("Открыть / скрыть калькулятор наказаний")
        )
        calculator_hotkey_row.addStretch()
        self.settings_calculator_hotkey = SingleHotkeyEdit(
            SingleHotkeyEdit.sequence_from_spec(
                self.app_settings.get("calculator_hotkey", "F9")
            )
        )
        self.settings_calculator_hotkey.setMaximumWidth(220)
        calculator_hotkey_row.addWidget(self.settings_calculator_hotkey)
        controls_layout.addLayout(calculator_hotkey_row)
        add_setting_separator(controls_layout)

        self.settings_global_calculator_hotkey = StatusCheckBox(
            "Глобальный бинд калькулятора — работает в игре, когда DeiLaw свёрнут/в трее"
        )
        self.settings_global_calculator_hotkey.setChecked(
            bool(self.app_settings.get("global_calculator_hotkey", True))
        )
        controls_layout.addWidget(self.settings_global_calculator_hotkey)
        add_setting_separator(controls_layout)

        self.settings_block_hotkeys_when_main_open = StatusCheckBox(
            "Не открывать быстрые окна по биндам, пока DeiLaw развёрнут"
        )
        self.settings_block_hotkeys_when_main_open.setToolTip(
            "Если включено, F7/F8/F9 и назначенные бинды не вызывают "
            "Quick Search, Quick Memo и Quick Calculator, пока главное окно "
            "DeiLaw открыто. После сворачивания или закрытия в системный трей "
            "бинды снова работают."
        )
        self.settings_block_hotkeys_when_main_open.setChecked(
            bool(
                self.app_settings.get(
                    "block_quick_hotkeys_when_main_open",
                    True,
                )
            )
        )
        controls_layout.addWidget(
            self.settings_block_hotkeys_when_main_open
        )
        add_setting_separator(controls_layout)

        self.settings_enter_search = StatusCheckBox(
            "Enter запускает поиск во вкладке «Поиск»"
        )
        self.settings_enter_search.setChecked(
            bool(self.app_settings.get("enter_runs_search", True))
        )
        controls_layout.addWidget(self.settings_enter_search)
        add_setting_separator(controls_layout)

        self.settings_double_open = StatusCheckBox(
            "Двойной клик открывает полный текст статьи"
        )
        self.settings_double_open.setChecked(
            bool(self.app_settings.get("double_click_opens_article", True))
        )
        controls_layout.addWidget(self.settings_double_open)
        add_setting_separator(controls_layout)

        self.settings_ui_sounds = StatusCheckBox(
            "Включить звуки программы"
        )
        self.settings_ui_sounds.setToolTip(
            "Главный переключатель всех звуков DeiLaw: кнопки, галочки, "
            "вкладки, сохранение, Quick Memo и голосовые уведомления."
        )
        self.settings_ui_sounds.setChecked(
            bool(self.app_settings.get("ui_sounds", True))
        )
        controls_layout.addWidget(self.settings_ui_sounds)
        add_setting_separator(controls_layout)

        self.settings_report_reply_voice = StatusCheckBox(
            "Озвучивать ответ разработчика на репорт"
        )
        self.settings_report_reply_voice.setToolTip(
            "Когда разработчик отвечает на ваш баг-репорт, DeiLaw проигрывает "
            "голосовое уведомление «Разработчик ответил на ваш репорт». "
            "Работает и когда DeiLaw свёрнут в системный трей. "
            "Требует включённых звуков программы."
        )
        self.settings_report_reply_voice.setChecked(
            bool(self.app_settings.get("report_reply_voice", True))
        )
        controls_layout.addWidget(self.settings_report_reply_voice)
        add_setting_separator(controls_layout)

        close_choice_title = QLabel("Поведение кнопки ×")
        close_choice_title.setObjectName("sectionTitle")
        controls_layout.addWidget(close_choice_title)

        self.settings_remember_close_choice = StatusCheckBox(
            "Использовать запомненный выбор при закрытии"
        )
        controls_layout.addWidget(self.settings_remember_close_choice)

        self.settings_close_choice_hint = QLabel("")
        self.settings_close_choice_hint.setObjectName("muted")
        self.settings_close_choice_hint.setWordWrap(True)
        controls_layout.addWidget(self.settings_close_choice_hint)

        self.refresh_close_behavior_settings_ui()
        add_setting_separator(controls_layout)

        self.settings_tutorial_button = QPushButton("🎓  Повторить обучение")
        self.settings_tutorial_button.setToolTip(
            "Снова открыть пошаговую инструкцию по DeiLaw."
        )
        self.settings_tutorial_button.clicked.connect(
            lambda checked=False: self.show_onboarding_tutorial(first_run=False)
        )
        controls_layout.addWidget(self.settings_tutorial_button)

        memo_card = QFrame()
        memo_card.setObjectName("card")
        memo_layout = QVBoxLayout(memo_card)
        memo_title = QLabel("RP Quick Memo")
        memo_title.setObjectName("sectionTitle")
        memo_layout.addWidget(memo_title)

        self.settings_topmost = StatusCheckBox("Памятка всегда поверх других окон")
        self.settings_topmost.setChecked(
            bool(self.app_settings.get("memo_always_on_top", True))
        )
        self.settings_remember_layout = StatusCheckBox(
            "Запоминать размеры окна, столбцов и разделов памятки"
        )
        self.settings_remember_layout.setChecked(
            bool(self.app_settings.get("remember_memo_layout", True))
        )
        self.settings_penalties = StatusCheckBox("Показывать наказания на карточках")
        self.settings_penalties.setChecked(
            bool(self.app_settings.get("show_penalties", True))
        )
        self.settings_confirm_delete = StatusCheckBox(
            "Подтверждать удаление столбца со статьями"
        )
        self.settings_confirm_delete.setChecked(
            bool(self.app_settings.get("confirm_delete_column", True))
        )
        memo_layout.addWidget(self.settings_topmost)
        add_setting_separator(memo_layout)

        self.settings_click_through = StatusCheckBox(
            "Памятка не кликабельная — клики проходят в игру"
        )
        self.settings_click_through.setToolTip(
            "Окно остаётся видимым, но мышь взаимодействует с игрой под ним. "
            "Показать или скрыть памятку можно глобальным биндом."
        )
        self.settings_click_through.setChecked(
            bool(self.app_settings.get("overlay_click_through", False))
        )
        memo_layout.addWidget(self.settings_click_through)
        add_setting_separator(memo_layout)
        memo_layout.addWidget(self.settings_remember_layout)
        add_setting_separator(memo_layout)
        memo_layout.addWidget(self.settings_penalties)
        add_setting_separator(memo_layout)
        memo_layout.addWidget(self.settings_confirm_delete)
        add_setting_separator(memo_layout)

        self.settings_reset_layout = QPushButton(
            "Сбросить сохранённые размеры и положение памятки"
        )
        self.settings_reset_layout.clicked.connect(
            self.reset_memo_layout_state
        )
        memo_layout.addWidget(self.settings_reset_layout)

        display_card = QFrame()
        display_card.setObjectName("card")
        display_layout = QVBoxLayout(display_card)
        display_title = QLabel("Внешний вид")
        display_title.setObjectName("sectionTitle")
        display_layout.addWidget(display_title)

        theme_row = QHBoxLayout()
        theme_text = QVBoxLayout()
        theme_label = QLabel("Светлая тема")
        theme_hint = QLabel("Переключает всю программу, памятку и быстрый поисковик.")
        theme_hint.setObjectName("muted")
        theme_hint.setWordWrap(True)
        theme_text.addWidget(theme_label)
        theme_text.addWidget(theme_hint)
        theme_row.addLayout(theme_text, stretch=1)
        self.settings_theme_switch = ThemeSwitch()
        self.settings_theme_switch.setChecked(
            self.app_settings.get("theme", "dark") == "light"
        )
        self.settings_theme_switch.toggled.connect(self.preview_theme)
        theme_row.addWidget(self.settings_theme_switch, alignment=Qt.AlignmentFlag.AlignVCenter)
        display_layout.addLayout(theme_row)
        add_setting_separator(display_layout)

        visual_theme_row = QHBoxLayout()
        visual_theme_text = QVBoxLayout()
        visual_theme_label = QLabel("Стиль оформления")
        visual_theme_hint = QLabel(
            "Меняет цвета, акценты и фон всей программы. "
            "Каждый стиль автоматически адаптируется к светлому режиму."
        )
        visual_theme_hint.setObjectName("muted")
        visual_theme_hint.setWordWrap(True)
        visual_theme_text.addWidget(visual_theme_label)
        visual_theme_text.addWidget(visual_theme_hint)
        visual_theme_row.addLayout(visual_theme_text, stretch=1)

        self.settings_visual_theme = QComboBox()
        self.settings_visual_theme.setMinimumWidth(190)
        self.settings_visual_theme.addItem("По умолчанию", "default")
        self.settings_visual_theme.addItem("Retro", "retro")
        self.settings_visual_theme.addItem("Neon", "neon")
        self.settings_visual_theme.addItem("Градиент", "gradient")
        self.settings_visual_theme.addItem("Moscow Night", "moscow_night")
        self.settings_visual_theme.addItem("Police Blue", "police_blue")
        self.settings_visual_theme.addItem("Crimson", "crimson")
        self.settings_visual_theme.addItem("AMOLED", "amoled")
        self.settings_visual_theme.addItem("Terminal", "terminal")
        self.settings_visual_theme.addItem("Cyber Blue", "cyber_blue")
        self.settings_visual_theme.addItem("Arctic", "arctic")
        self.settings_visual_theme.addItem("Carbon", "carbon")
        self.settings_visual_theme.addItem("Midnight Purple", "midnight_purple")
        self.settings_visual_theme.addItem("Amber", "amber")
        self.settings_visual_theme.addItem("Government", "government")
        self.settings_visual_theme.addItem("Rainy Moscow", "rainy_moscow")
        self.settings_visual_theme.addItem("Hazard", "hazard")
        self.settings_visual_theme.addItem("Paper", "paper")
        self.settings_visual_theme.addItem("Deep Space", "deep_space")

        current_visual_theme = str(
            self.app_settings.get("visual_theme", "default") or "default"
        ).strip().lower()
        visual_index = self.settings_visual_theme.findData(
            current_visual_theme
        )
        if visual_index < 0:
            visual_index = 0
        self.settings_visual_theme.setCurrentIndex(visual_index)
        self.settings_visual_theme.currentIndexChanged.connect(
            self.preview_visual_theme
        )
        visual_theme_row.addWidget(
            self.settings_visual_theme,
            alignment=Qt.AlignmentFlag.AlignVCenter,
        )
        display_layout.addLayout(visual_theme_row)
        add_setting_separator(display_layout)

        program_font_row = QHBoxLayout()
        program_font_row.addWidget(settings_label("Размер шрифта во всей программе"))
        program_font_row.addStretch()
        self.settings_program_font = QSpinBox()
        self.settings_program_font.setMinimumWidth(110)
        self.settings_program_font.setRange(10, 22)
        self.settings_program_font.setValue(
            int(self.app_settings.get("program_font_size", 14))
        )
        self.settings_program_font.valueChanged.connect(
            self.preview_program_font_size
        )
        program_font_row.addWidget(self.settings_program_font)
        display_layout.addLayout(program_font_row)
        add_setting_separator(display_layout)

        opacity_title = QLabel("Прозрачность быстрых окон")
        opacity_title.setObjectName("articleHeading")
        display_layout.addWidget(opacity_title)

        def create_opacity_setting(label_text, key, callback):
            row = QHBoxLayout()
            row.addWidget(settings_label(label_text))
            row.addStretch()
            combo = QComboBox()
            combo.setMinimumWidth(110)
            combo.setEditable(True)
            combo.addItems(["100", "90", "80", "70", "60", "50", "40"])
            combo.setCurrentText(str(int(self.app_settings.get(key, 100))))
            combo.lineEdit().setValidator(QIntValidator(40, 100, combo))
            combo.setToolTip("Можно выбрать готовое значение или вписать вручную 40–100.")
            combo.currentTextChanged.connect(callback)
            row.addWidget(combo)
            display_layout.addLayout(row)
            return combo

        self.settings_search_overlay_opacity = create_opacity_setting(
            "F7 — Quick Search, %",
            "search_overlay_opacity",
            self.preview_search_overlay_opacity,
        )
        self.settings_memo_overlay_opacity = create_opacity_setting(
            "F8 — Quick Memo, %",
            "memo_overlay_opacity",
            self.preview_memo_overlay_opacity,
        )
        self.settings_calculator_overlay_opacity = create_opacity_setting(
            "F9 — Quick Calculator, %",
            "calculator_overlay_opacity",
            self.preview_calculator_overlay_opacity,
        )
        # Compatibility alias for older helper code / third-party patches.
        self.settings_overlay_opacity = self.settings_memo_overlay_opacity
        add_setting_separator(display_layout)

        font_row = QHBoxLayout()
        font_row.addWidget(settings_label("Размер текста карточек"))
        font_row.addStretch()
        self.settings_card_font = QSpinBox()
        self.settings_card_font.setMinimumWidth(110)
        self.settings_card_font.setRange(10, 24)
        self.settings_card_font.setValue(
            int(self.app_settings.get("memo_card_font_size", 14))
        )
        font_row.addWidget(self.settings_card_font)
        display_layout.addLayout(font_row)
        add_setting_separator(display_layout)

        height_row = QHBoxLayout()
        height_row.addWidget(settings_label("Минимальная высота карточки"))
        height_row.addStretch()
        self.settings_card_height = QSpinBox()
        self.settings_card_height.setMinimumWidth(110)
        self.settings_card_height.setRange(50, 180)
        self.settings_card_height.setSingleStep(5)
        self.settings_card_height.setValue(
            int(self.app_settings.get("memo_card_min_height", 72))
        )
        height_row.addWidget(self.settings_card_height)
        display_layout.addLayout(height_row)
        add_setting_separator(display_layout)

        self.settings_show_code = StatusCheckBox(
            "Показывать номер статьи и сокращение кодекса"
        )
        self.settings_show_code.setChecked(
            bool(self.app_settings.get("show_article_code", True))
        )
        self.settings_show_summary = StatusCheckBox(
            "Показывать краткое описание статьи"
        )
        self.settings_show_summary.setChecked(
            bool(self.app_settings.get("show_article_summary", True))
        )
        display_layout.addWidget(self.settings_show_code)
        add_setting_separator(display_layout)
        display_layout.addWidget(self.settings_show_summary)

        window_card = QFrame()
        window_card.setObjectName("card")
        window_layout = QVBoxLayout(window_card)
        window_title = QLabel("Окна по биндам")
        window_title.setObjectName("sectionTitle")
        window_layout.addWidget(window_title)

        window_hint = QLabel(
            "Размер применяется к Quick Search (F7), Quick Memo (F8) "
            "и Quick Calculator (F9). Изменение размера заменяет ранее "
            "запомненный размер быстрых окон."
        )
        window_hint.setObjectName("muted")
        window_hint.setWordWrap(True)
        window_layout.addWidget(window_hint)
        add_setting_separator(window_layout)

        width_row = QHBoxLayout()
        width_row.addWidget(settings_label("Ширина быстрых окон"))
        width_row.addStretch()
        self.settings_overlay_width = QSpinBox()
        self.settings_overlay_width.setMinimumWidth(110)
        self.settings_overlay_width.setRange(760, 2500)
        self.settings_overlay_width.setSingleStep(50)
        self.settings_overlay_width.setValue(
            int(self.app_settings.get("overlay_width", 1250))
        )
        width_row.addWidget(self.settings_overlay_width)
        window_layout.addLayout(width_row)
        add_setting_separator(window_layout)

        height2_row = QHBoxLayout()
        height2_row.addWidget(settings_label("Высота быстрых окон"))
        height2_row.addStretch()
        self.settings_overlay_height = QSpinBox()
        self.settings_overlay_height.setMinimumWidth(110)
        self.settings_overlay_height.setRange(420, 1400)
        self.settings_overlay_height.setSingleStep(50)
        self.settings_overlay_height.setValue(
            int(self.app_settings.get("overlay_height", 650))
        )
        height2_row.addWidget(self.settings_overlay_height)
        window_layout.addLayout(height2_row)

        search_card = QFrame()
        search_card.setObjectName("card")
        search_layout = QVBoxLayout(search_card)
        search_title = QLabel("Поиск")
        search_title.setObjectName("sectionTitle")
        search_layout.addWidget(search_title)
        row = QHBoxLayout()
        row.addWidget(settings_label("Максимум результатов обычного поиска"))
        row.addStretch()
        self.settings_search_limit = QSpinBox()
        self.settings_search_limit.setMinimumWidth(110)
        self.settings_search_limit.setRange(20, 500)
        self.settings_search_limit.setSingleStep(20)
        self.settings_search_limit.setValue(
            int(self.app_settings.get("search_limit", 100))
        )
        row.addWidget(self.settings_search_limit)
        search_layout.addLayout(row)

        charter_card = QFrame()
        charter_card.setObjectName("card")
        charter_layout = QVBoxLayout(charter_card)

        charter_title = QLabel("Устав")
        charter_title.setObjectName("sectionTitle")
        charter_layout.addWidget(charter_title)

        charter_hint = QLabel(
            "Устав можно подключить двумя способами: выбрать локальный DOCX "
            "или вставить ссылку. Поддерживаются публичные Google Документы, "
            "прямые ссылки на DOCX и страницы форума/сайта с текстом Устава. "
            "После подключения вкладка «Устав» появится автоматически."
        )
        charter_hint.setObjectName("muted")
        charter_hint.setWordWrap(True)
        charter_layout.addWidget(charter_hint)

        charter_path_row = QHBoxLayout()
        self.settings_charter_path = QLineEdit()
        self.settings_charter_path.setReadOnly(True)
        self.settings_charter_path.setPlaceholderText(
            "Файл Устава не выбран"
        )
        self.settings_charter_select_button = QPushButton(
            "Выбрать DOCX"
        )
        self.settings_charter_select_button.setObjectName("primary")
        charter_path_row.addWidget(
            self.settings_charter_path,
            stretch=1,
        )
        charter_path_row.addWidget(
            self.settings_charter_select_button
        )
        charter_layout.addLayout(charter_path_row)

        charter_or_label = QLabel(
            "или подключить по ссылке"
        )
        charter_or_label.setObjectName("muted")
        charter_layout.addWidget(charter_or_label)

        charter_url_row = QHBoxLayout()
        self.settings_charter_url = QLineEdit()
        self.settings_charter_url.setPlaceholderText(
            "https://docs.google.com/document/d/... или ссылка на форум / DOCX"
        )
        self.settings_charter_url.setClearButtonEnabled(True)

        self.settings_charter_connect_url_button = QPushButton(
            "Подключить ссылку"
        )
        self.settings_charter_connect_url_button.setObjectName(
            "primary"
        )
        charter_url_row.addWidget(
            self.settings_charter_url,
            stretch=1,
        )
        charter_url_row.addWidget(
            self.settings_charter_connect_url_button
        )
        charter_layout.addLayout(charter_url_row)

        self.settings_charter_refresh_url_button = QPushButton(
            "Обновить по ссылке"
        )

        charter_buttons = QHBoxLayout()
        self.settings_charter_open_button = QPushButton(
            "Открыть выбранный файл"
        )
        self.settings_charter_clear_button = QPushButton(
            "Отключить Устав"
        )
        charter_buttons.addWidget(
            self.settings_charter_open_button
        )
        charter_buttons.addWidget(
            self.settings_charter_refresh_url_button
        )
        charter_buttons.addWidget(
            self.settings_charter_clear_button
        )
        charter_buttons.addStretch()
        charter_layout.addLayout(charter_buttons)

        self.settings_charter_status = QLabel("")
        self.settings_charter_status.setObjectName("muted")
        self.settings_charter_status.setWordWrap(True)
        charter_layout.addWidget(self.settings_charter_status)

        self.settings_charter_select_button.clicked.connect(
            self.select_gibdd_charter_file
        )
        self.settings_charter_connect_url_button.clicked.connect(
            self.connect_gibdd_charter_url
        )
        self.settings_charter_url.returnPressed.connect(
            self.connect_gibdd_charter_url
        )
        self.settings_charter_refresh_url_button.clicked.connect(
            lambda: self.refresh_gibdd_charter_url(manual=True)
        )
        self.settings_charter_open_button.clicked.connect(
            self.open_selected_gibdd_charter_from_settings
        )
        self.settings_charter_clear_button.clicked.connect(
            self.clear_gibdd_charter_selection
        )
        self.refresh_gibdd_charter_settings_ui()

        law_update_card = QFrame()
        law_update_card.setObjectName("card")
        law_update_layout = QVBoxLayout(law_update_card)
        law_update_title = QLabel("Обновление законодательства")
        law_update_title.setObjectName("sectionTitle")
        law_update_layout.addWidget(law_update_title)

        self.settings_auto_law_updates = StatusCheckBox(
            "Автоматически обновлять законку при запуске"
        )
        self.settings_auto_law_updates.setChecked(
            bool(self.app_settings.get("auto_update_laws_on_startup", True))
        )
        self.settings_auto_law_updates.setToolTip(
            "DeiLaw запускает обычную синхронизацию законки после старта, "
            "если с предыдущей автоматической проверки прошло выбранное время."
        )
        law_update_layout.addWidget(self.settings_auto_law_updates)

        law_interval_row = QHBoxLayout()
        law_interval_row.addWidget(QLabel("Проверять не чаще"))
        law_interval_row.addStretch()
        self.settings_law_update_interval = QComboBox()
        self.settings_law_update_interval.addItem("Раз в 6 часов", 6)
        self.settings_law_update_interval.addItem("Раз в 12 часов", 12)
        self.settings_law_update_interval.addItem("Раз в 24 часа", 24)
        saved_law_interval = int(self.app_settings.get("law_update_interval_hours", 6) or 6)
        law_interval_index = self.settings_law_update_interval.findData(saved_law_interval)
        self.settings_law_update_interval.setCurrentIndex(
            law_interval_index if law_interval_index >= 0 else 0
        )
        law_interval_row.addWidget(self.settings_law_update_interval)
        law_update_layout.addLayout(law_interval_row)

        law_update_hint = QLabel(
            "На первом запуске пустая база по-прежнему заполняется через обычный мастер. "
            "Автообновление включается для следующих запусков и не запускается чаще заданного интервала."
        )
        law_update_hint.setObjectName("muted")
        law_update_hint.setWordWrap(True)
        law_update_layout.addWidget(law_update_hint)

        update_program_card = QFrame()
        update_program_card.setObjectName("card")
        update_program_layout = QVBoxLayout(update_program_card)
        update_program_title = QLabel("Обновления программы")
        update_program_title.setObjectName("sectionTitle")
        update_program_layout.addWidget(update_program_title)

        self.settings_auto_program_updates = StatusCheckBox(
            "Автоматическое обновление всегда включено"
        )
        self.settings_auto_program_updates.setChecked(True)
        self.settings_auto_program_updates.setEnabled(False)
        self.settings_auto_program_updates.setToolTip(
            "Проверка выполняется перед каждым запуском и каждые 3 минуты "
            "во время работы DeiLaw."
        )
        update_program_layout.addWidget(
            self.settings_auto_program_updates
        )

        channel_row = QHBoxLayout()
        channel_row.addWidget(QLabel("Канал обновлений"))
        channel_row.addStretch()
        self.settings_update_channel = QComboBox()
        self.settings_update_channel.addItem("Stable", "stable")
        self.settings_update_channel.addItem("Beta / тестовые версии", "beta")
        saved_channel = str(
            self.app_settings.get(
                "update_channel",
                load_update_config().get("channel", "stable"),
            ) or "stable"
        ).lower()
        channel_index = self.settings_update_channel.findData(saved_channel)
        self.settings_update_channel.setCurrentIndex(
            channel_index if channel_index >= 0 else 0
        )
        self.settings_update_channel.setToolTip(
            "Stable получает только обычные релизы. Beta также получает "
            "тестовые версии a/b/c/…, alpha, beta и RC."
        )
        channel_row.addWidget(self.settings_update_channel)
        update_program_layout.addLayout(channel_row)

        program_update_row = QHBoxLayout()
        self.settings_program_version_label = QLabel(
            f"Текущая версия: {APP_VERSION}"
        )
        self.settings_program_version_label.setObjectName("muted")
        self.settings_check_program_update_button = QPushButton(
            "Проверить обновления"
        )
        self.settings_check_program_update_button.clicked.connect(
            lambda: self.check_program_update(manual=True)
        )
        program_update_row.addWidget(
            self.settings_program_version_label
        )
        program_update_row.addStretch()
        program_update_row.addWidget(
            self.settings_check_program_update_button
        )
        update_program_layout.addLayout(program_update_row)

        self.settings_program_update_status = QLabel(
            self.program_update_status_text
        )
        self.settings_program_update_status.setObjectName("muted")
        self.settings_program_update_status.setWordWrap(True)
        update_program_layout.addWidget(
            self.settings_program_update_status
        )

        self.settings_status_card = QFrame()
        self.settings_status_card.setObjectName("card")
        state_layout = QVBoxLayout(self.settings_status_card)
        state_layout.setSpacing(10)

        state_header = QHBoxLayout()
        state_title = QLabel("Состояние DeiLaw")
        state_title.setObjectName("sectionTitle")
        state_header.addWidget(state_title)
        state_header.addStretch()
        self.settings_refresh_status_button = QPushButton("↻ Обновить")
        self.settings_refresh_status_button.clicked.connect(
            self.refresh_status_page
        )
        state_header.addWidget(self.settings_refresh_status_button)
        state_layout.addLayout(state_header)

        state_hint = QLabel(
            "Сводка по локальной базе, поиску, обновлениям, AI и текущим "
            "настройкам DeiLaw. Раньше эта информация находилась в отдельной вкладке «Состояние»."
        )
        state_hint.setObjectName("muted")
        state_hint.setWordWrap(True)
        state_layout.addWidget(state_hint)

        def add_state_section(title_text):
            heading = QLabel(title_text)
            heading.setObjectName("articleHeading")
            state_layout.addWidget(heading)
            body = QLabel("Загрузка…")
            body.setObjectName("muted")
            body.setWordWrap(True)
            body.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            state_layout.addWidget(body)
            add_setting_separator(state_layout)
            return body

        self.status_database_label = add_state_section(
            "📚 База законодательства"
        )
        self.status_search_label = add_state_section("🔎 Умный поиск")
        self.status_update_label = add_state_section(
            "🔄 Обновления и изменения"
        )
        self.status_app_label = add_state_section("⚙ Программа")
        self.status_ai_label = add_state_section("🤖 DeiLaw AI и обучение")

        diagnostics_card = QFrame()
        diagnostics_card.setObjectName("card")
        diagnostics_layout = QVBoxLayout(diagnostics_card)
        diagnostics_title = QLabel("Диагностика и тестирование")
        diagnostics_title.setObjectName("sectionTitle")
        diagnostics_layout.addWidget(diagnostics_title)
        diagnostics_hint = QLabel(
            "Инструменты для проверки горячих клавиш и глобальной "
            "регистрации биндов в Windows."
        )
        diagnostics_hint.setObjectName("muted")
        diagnostics_hint.setWordWrap(True)
        diagnostics_layout.addWidget(diagnostics_hint)

        diagnostics_buttons = QHBoxLayout()
        self.settings_hotkey_diagnostics_button = QPushButton(
            "⌨ Диагностика биндов"
        )
        self.settings_hotkey_diagnostics_button.clicked.connect(
            self.show_hotkey_diagnostics
        )
        diagnostics_buttons.addWidget(
            self.settings_hotkey_diagnostics_button
        )
        diagnostics_buttons.addStretch()
        diagnostics_layout.addLayout(diagnostics_buttons)

        backup_card = QFrame()
        backup_card.setObjectName("card")
        backup_layout = QVBoxLayout(backup_card)
        backup_title = QLabel("Резервные копии")
        backup_title.setObjectName("sectionTitle")
        backup_layout.addWidget(backup_title)
        backup_hint = QLabel(
            "DeiLaw автоматически создаёт резервную копию пользовательских "
            "настроек перед обновлением программы. Здесь можно сделать копию "
            "вручную или восстановить последнюю."
        )
        backup_hint.setObjectName("muted")
        backup_hint.setWordWrap(True)
        backup_layout.addWidget(backup_hint)
        backup_buttons = QHBoxLayout()
        self.settings_backup_create_button = QPushButton("Создать копию")
        self.settings_backup_restore_button = QPushButton("Восстановить последнюю")
        self.settings_backup_create_button.clicked.connect(
            self.create_manual_backup
        )
        self.settings_backup_restore_button.clicked.connect(
            self.restore_latest_backup
        )
        backup_buttons.addWidget(self.settings_backup_create_button)
        backup_buttons.addWidget(self.settings_backup_restore_button)
        backup_buttons.addStretch()
        backup_layout.addLayout(backup_buttons)

        note = QLabel(
            "Глобальные бинды поддерживают латиницу, кириллицу, NumPad и "
            "большинство служебных клавиш. Они работают в игре, когда DeiLaw "
            "свёрнут или находится в системном трее. Блокировку биндов при "
            "развёрнутом главном окне можно включать и выключать выше."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.addStretch()
        reset = QPushButton("По умолчанию")
        save = QPushButton("Сохранить настройки")
        save.setObjectName("primary")
        reset.clicked.connect(self.reset_app_settings)
        save.clicked.connect(self.apply_app_settings)
        buttons.addWidget(reset)
        buttons.addWidget(save)

        self.settings_status = QLabel("")
        self.settings_status.setObjectName("muted")

        root.addWidget(controls_card)
        root.addWidget(memo_card)
        root.addWidget(display_card)
        root.addWidget(window_card)
        root.addWidget(search_card)
        root.addWidget(charter_card)
        root.addWidget(law_update_card)
        root.addWidget(update_program_card)
        root.addWidget(self.settings_status_card)
        root.addWidget(diagnostics_card)
        root.addWidget(backup_card)
        root.addWidget(note)
        root.addStretch()
        root.addWidget(self.settings_status)
        root.addLayout(buttons)
        root.addStretch()

        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        dirty_widgets = [
            self.settings_hotkey,
            self.settings_global_hotkey,
            self.settings_search_hotkey,
            self.settings_global_search_hotkey,
            self.settings_calculator_hotkey,
            self.settings_global_calculator_hotkey,
            self.settings_block_hotkeys_when_main_open,
            self.settings_enter_search,
            self.settings_double_open,
            self.settings_ui_sounds,
            self.settings_report_reply_voice,
            self.settings_remember_close_choice,
            self.settings_topmost,
            self.settings_click_through,
            self.settings_remember_layout,
            self.settings_penalties,
            self.settings_confirm_delete,
            self.settings_theme_switch,
            self.settings_visual_theme,
            self.settings_search_overlay_opacity,
            self.settings_memo_overlay_opacity,
            self.settings_calculator_overlay_opacity,
            self.settings_card_font,
            self.settings_card_height,
            self.settings_show_code,
            self.settings_show_summary,
            self.settings_overlay_width,
            self.settings_overlay_height,
            self.settings_search_limit,
            self.settings_auto_program_updates,
            self.settings_auto_law_updates,
            self.settings_law_update_interval,
            self.settings_update_channel,
        ]
        for widget in dirty_widgets:
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self.mark_settings_dirty)
                widget.toggled.connect(
                    lambda checked, self=self: self.play_ui_sound("toggle")
                )
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self.mark_settings_dirty)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.mark_settings_dirty)
            elif isinstance(widget, QKeySequenceEdit):
                widget.keySequenceChanged.connect(self.mark_settings_dirty)

        return page

    def collect_settings_form_state(self):
        """Return the current Settings form values without saving anything."""
        hotkey = self.settings_hotkey.hotkey_text().strip() or "F8"
        search_hotkey = self.settings_search_hotkey.hotkey_text().strip() or "F7"
        calculator_hotkey = (
            self.settings_calculator_hotkey.hotkey_text().strip()
            or "F9"
        )
        def opacity_value(combo):
            try:
                value = int(combo.currentText() or 100)
            except (TypeError, ValueError):
                value = 100
            return max(40, min(100, value))

        search_opacity = opacity_value(self.settings_search_overlay_opacity)
        memo_opacity = opacity_value(self.settings_memo_overlay_opacity)
        calculator_opacity = opacity_value(self.settings_calculator_overlay_opacity)

        return {
            "memo_hotkey": hotkey,
            "search_hotkey": search_hotkey,
            "calculator_hotkey": calculator_hotkey,
            "theme": "light" if self.settings_theme_switch.isChecked() else "dark",
            "visual_theme": (
                self.settings_visual_theme.currentData()
                or "default"
            ),
            "global_memo_hotkey": self.settings_global_hotkey.isChecked(),
            "global_search_hotkey": self.settings_global_search_hotkey.isChecked(),
            "global_calculator_hotkey": self.settings_global_calculator_hotkey.isChecked(),
            "block_quick_hotkeys_when_main_open": (
                self.settings_block_hotkeys_when_main_open.isChecked()
            ),
            "enter_runs_search": self.settings_enter_search.isChecked(),
            "double_click_opens_article": self.settings_double_open.isChecked(),
            "ui_sounds": self.settings_ui_sounds.isChecked(),
            "report_reply_voice": self.settings_report_reply_voice.isChecked(),
            "remember_close_choice": (
                self.settings_remember_close_choice.isChecked()
            ),
            "auto_check_program_updates": True,
            "auto_update_laws_on_startup": self.settings_auto_law_updates.isChecked(),
            "law_update_interval_hours": int(
                self.settings_law_update_interval.currentData() or 6
            ),
            "update_channel": (
                self.settings_update_channel.currentData() or "stable"
            ),
            "memo_always_on_top": self.settings_topmost.isChecked(),
            "overlay_click_through": self.settings_click_through.isChecked(),
            "remember_memo_layout": self.settings_remember_layout.isChecked(),
            "show_penalties": self.settings_penalties.isChecked(),
            "confirm_memo_delete": self.settings_confirm_delete.isChecked(),
            "overlay_opacity": memo_opacity,
            "search_overlay_opacity": search_opacity,
            "memo_overlay_opacity": memo_opacity,
            "calculator_overlay_opacity": calculator_opacity,
            "program_font_size": self.settings_program_font.value(),
            "memo_card_font_size": self.settings_card_font.value(),
            "memo_card_min_height": self.settings_card_height.value(),
            "show_article_code": self.settings_show_code.isChecked(),
            "show_article_summary": self.settings_show_summary.isChecked(),
            "overlay_width": self.settings_overlay_width.value(),
            "overlay_height": self.settings_overlay_height.value(),
            "search_limit": self.settings_search_limit.value(),
        }

    def refresh_close_behavior_settings_ui(self):
        """Reflect the saved close-button preference in Settings."""
        if not hasattr(self, "settings_remember_close_choice"):
            return

        behavior = str(
            self.app_settings.get("close_behavior", "ask") or "ask"
        ).strip().lower()
        remembered = bool(
            self.app_settings.get("remember_close_choice", False)
        )
        valid = behavior in ("minimize", "exit")

        # The checkbox is a reset switch for an already remembered choice.
        # Until the user checks "Запомнить мой выбор" in the X-dialog there is
        # intentionally nothing to enable here.
        self.settings_remember_close_choice.blockSignals(True)
        self.settings_remember_close_choice.setChecked(
            remembered and valid
        )
        self.settings_remember_close_choice.setEnabled(valid)
        self.settings_remember_close_choice.blockSignals(False)

        if remembered and behavior == "minimize":
            message = (
                "Запомненный выбор: Свернуть в трей. При нажатии × DeiLaw "
                "будет скрываться из панели задач и оставаться в системном трее. "
                "Снимите галочку и сохраните "
                "настройки, чтобы снова показывать выбор."
            )
        elif remembered and behavior == "exit":
            message = (
                "Запомненный выбор: Закрыть полностью. Снимите галочку и "
                "сохраните настройки, чтобы при нажатии × снова появлялся выбор."
            )
        elif valid:
            message = (
                "Запомненный выбор отключён. После сохранения при следующем "
                "нажатии × DeiLaw снова спросит, что сделать."
            )
        else:
            message = (
                "Запомненного выбора пока нет. Нажмите ×, выберите "
                "«Свернуть» или «Закрыть полностью» и поставьте галочку "
                "«Запомнить мой выбор»."
            )

        if hasattr(self, "settings_close_choice_hint"):
            self.settings_close_choice_hint.setText(message)

        # If the preference was changed by the close dialog while Settings was
        # already open, update only this saved field in the snapshot. Other
        # unsaved Settings changes must remain dirty.
        if isinstance(getattr(self, "settings_snapshot", None), dict):
            self.settings_snapshot["remember_close_choice"] = (
                remembered and valid
            )

    def capture_settings_snapshot(self):
        if not hasattr(self, "settings_hotkey"):
            return
        self.settings_snapshot = self.collect_settings_form_state()
        self.settings_dirty = False

    def mark_settings_dirty(self, *args):
        if self.settings_snapshot is None:
            return
        self.settings_dirty = (
            self.collect_settings_form_state() != self.settings_snapshot
        )

    def _preview_quick_opacity(self, key, value, apply_callback):
        value = str(value).strip()
        if not value.isdigit():
            return
        percent = int(value)
        if percent < 40 or percent > 100:
            return
        self.app_settings[key] = percent
        # Preserve the legacy key as the F8/Memo value for compatibility.
        if key == "memo_overlay_opacity":
            self.app_settings["overlay_opacity"] = percent
        apply_callback()
        self.mark_settings_dirty()

    def preview_search_overlay_opacity(self, value):
        self._preview_quick_opacity(
            "search_overlay_opacity",
            value,
            lambda: self.apply_search_overlay_style() if self.search_overlay is not None else None,
        )

    def preview_memo_overlay_opacity(self, value):
        self._preview_quick_opacity(
            "memo_overlay_opacity",
            value,
            lambda: self.apply_overlay_background_opacity() if self.memo_overlay is not None else None,
        )

    def preview_calculator_overlay_opacity(self, value):
        self._preview_quick_opacity(
            "calculator_overlay_opacity",
            value,
            lambda: self.apply_calculator_overlay_style() if self.calculator_overlay is not None else None,
        )

    def preview_overlay_opacity(self, value):
        # Compatibility alias: old callers control F8 Quick Memo.
        self.preview_memo_overlay_opacity(value)

    def preview_theme(self, checked):
        """Preview the selected theme immediately; persistence still uses Save."""
        self.app_settings["theme"] = "light" if checked else "dark"
        self.apply_style()
        if self.memo_overlay is not None:
            self.apply_overlay_background_opacity()
        if self.search_overlay is not None:
            self.apply_search_overlay_style()
        if self.calculator_overlay is not None:
            self.apply_calculator_overlay_style()
        self.mark_settings_dirty()

    def preview_visual_theme(self, _index=None):
        """Preview Default / Retro / Neon / Gradient immediately."""
        if not hasattr(self, "settings_visual_theme"):
            return

        visual_theme = (
            self.settings_visual_theme.currentData()
            or "default"
        )
        self.app_settings["visual_theme"] = visual_theme
        self.apply_style()

        if self.memo_overlay is not None:
            self.apply_overlay_background_opacity()
        if self.search_overlay is not None:
            self.apply_search_overlay_style()
        if self.calculator_overlay is not None:
            self.apply_calculator_overlay_style()

        self.mark_settings_dirty()

    def preview_program_font_size(self, value):
        """Preview global font immediately without persisting it yet."""
        if self.settings_original_font_size is None:
            self.settings_original_font_size = int(
                self.app_settings.get("program_font_size", 14)
            )

        self.app_settings["program_font_size"] = int(value)
        self.apply_style()
        self.mark_settings_dirty()

    def confirm_settings_leave(self):
        """Ask whether changed settings should be saved before leaving Settings."""
        if not self.settings_dirty:
            return True

        box = QMessageBox(self)
        box.setWindowTitle("Настройки DeiLaw")
        box.setText("Сохранить изменения настроек?")
        box.setInformativeText(
            "Изменения уже показаны в интерфейсе, но ещё не сохранены."
        )
        save_btn = box.addButton(
            "Сохранить",
            QMessageBox.ButtonRole.AcceptRole
        )
        discard_btn = box.addButton(
            "Не сохранять",
            QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_btn = box.addButton(
            "Остаться в настройках",
            QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(save_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is cancel_btn:
            return False

        if clicked is save_btn:
            self.apply_app_settings()
            self.capture_settings_snapshot()
            return True

        # Revert live font preview if user discards.
        if self.settings_original_font_size is not None:
            self.app_settings["program_font_size"] = (
                self.settings_original_font_size
            )
            self.settings_program_font.blockSignals(True)
            self.settings_program_font.setValue(
                self.settings_original_font_size
            )
            self.settings_program_font.blockSignals(False)
            self.apply_style()

        if isinstance(self.settings_original_overlay_opacities, dict):
            mapping = (
                ("search_overlay_opacity", self.settings_search_overlay_opacity),
                ("memo_overlay_opacity", self.settings_memo_overlay_opacity),
                ("calculator_overlay_opacity", self.settings_calculator_overlay_opacity),
            )
            for key, combo in mapping:
                value = int(self.settings_original_overlay_opacities.get(key, 100))
                self.app_settings[key] = value
                combo.blockSignals(True)
                combo.setCurrentText(str(value))
                combo.blockSignals(False)
            self.app_settings["overlay_opacity"] = int(
                self.settings_original_overlay_opacities.get("memo_overlay_opacity", 100)
            )

        if self.settings_original_theme is not None:
            self.app_settings["theme"] = self.settings_original_theme
            self.settings_theme_switch.blockSignals(True)
            self.settings_theme_switch.setChecked(self.settings_original_theme == "light")
            self.settings_theme_switch.blockSignals(False)

        if self.settings_original_visual_theme is not None:
            self.app_settings["visual_theme"] = (
                self.settings_original_visual_theme
            )
            if hasattr(self, "settings_visual_theme"):
                theme_index = self.settings_visual_theme.findData(
                    self.settings_original_visual_theme
                )
                self.settings_visual_theme.blockSignals(True)
                self.settings_visual_theme.setCurrentIndex(
                    max(0, theme_index)
                )
                self.settings_visual_theme.blockSignals(False)

        self.apply_style()
        if self.memo_overlay is not None:
            self.apply_overlay_background_opacity()
        if self.search_overlay is not None:
            self.apply_search_overlay_style()
        if self.calculator_overlay is not None:
            self.apply_calculator_overlay_style()

        self.capture_settings_snapshot()
        self.settings_original_font_size = int(
            self.app_settings.get("program_font_size", 14)
        )
        self.settings_original_overlay_opacity = int(
            self.app_settings.get("memo_overlay_opacity", self.app_settings.get("overlay_opacity", 100))
        )
        self.settings_original_overlay_opacities = {
            "search_overlay_opacity": int(self.app_settings.get("search_overlay_opacity", 100)),
            "memo_overlay_opacity": int(self.app_settings.get("memo_overlay_opacity", self.app_settings.get("overlay_opacity", 100))),
            "calculator_overlay_opacity": int(self.app_settings.get("calculator_overlay_opacity", 100)),
        }
        self.settings_original_theme = self.app_settings.get("theme", "dark")
        self.settings_original_visual_theme = self.app_settings.get(
            "visual_theme",
            "default",
        )
        return True

    def show_save_toast(self, message_text="Сохранено"):
        """Show a short action notification that fades away automatically."""
        if self.save_toast is not None:
            self.save_toast.close()
            self.save_toast.deleteLater()

        toast = QFrame(self)
        toast.setObjectName("saveToast")
        toast.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        toast.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        toast.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        layout = QHBoxLayout(toast)
        layout.setContentsMargins(34, 20, 34, 20)
        layout.setSpacing(8)

        icon = QLabel("✓")
        icon.setObjectName("saveToastIcon")
        message = QLabel(str(message_text or "Сохранено"))
        message.setObjectName("saveToastText")

        layout.addWidget(icon)
        layout.addWidget(message)

        light_theme = self.app_settings.get("theme", "dark") == "light"
        toast_palette = self._visual_theme_overlay_palette(light_theme)
        bg_r, bg_g, bg_b = toast_palette["surface"]
        tx_r, tx_g, tx_b = toast_palette["text"]
        br_r, br_g, br_b = toast_palette["primary_border"]
        pr_r, pr_g, pr_b = toast_palette["primary"]

        toast_bg = f"rgba({bg_r}, {bg_g}, {bg_b}, 245)"
        toast_text = f"rgb({tx_r}, {tx_g}, {tx_b})"
        toast_border = f"rgba({br_r}, {br_g}, {br_b}, 220)"
        toast_icon = f"rgb({pr_r}, {pr_g}, {pr_b})"
        toast.setStyleSheet(f"""
            QFrame#saveToast {{
                background-color: {toast_bg};
                border: 1px solid {toast_border};
                border-radius: 14px;
            }}
            QLabel#saveToastIcon {{
                color: {toast_icon};
                background: transparent;
                font-size: 30px;
                font-weight: 800;
            }}
            QLabel#saveToastText {{
                color: {toast_text};
                background: transparent;
                font-size: 20px;
                font-weight: 600;
            }}
        """)

        toast.adjustSize()

        # Center of the screen containing the DeiLaw window.
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = area.x() + (area.width() - toast.width()) // 2
            y = area.y() + (area.height() - toast.height()) // 2
        else:
            parent_rect = self.frameGeometry()
            x = parent_rect.center().x() - toast.width() // 2
            y = parent_rect.center().y() - toast.height() // 2

        toast.move(x, y)
        toast.setWindowOpacity(1.0)
        toast.show()

        self.save_toast = toast

        # Keep it visible briefly, then smoothly dissolve.
        QTimer.singleShot(1000, self.fade_save_toast)

    def fade_save_toast(self):
        if self.save_toast is None:
            return

        animation = QPropertyAnimation(
            self.save_toast, b"windowOpacity", self
        )
        animation.setDuration(650)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self.finish_save_toast)
        self.save_toast_animation = animation
        animation.start()

    def finish_save_toast(self):
        if self.save_toast is not None:
            self.save_toast.close()
            self.save_toast.deleteLater()
            self.save_toast = None
        self.save_toast_animation = None

    def get_ui_sound_path(self, filename):
        """Resolve bundled sound both in source mode and future packaged builds."""
        candidates = [
            Path(__file__).resolve().parent.parent / "assets" / "sounds" / filename,
            Path.cwd() / "assets" / "sounds" / filename,
        ]
        for path in candidates:
            if path.exists():
                return str(path)
        return None

    def install_button_sounds(self):
        """Attach the DeiLaw button sound to all push/tool buttons."""
        buttons = (
            self.findChildren(QPushButton)
            + self.findChildren(QToolButton)
        )
        for button in buttons:
            if button.property("deilawSoundInstalled"):
                continue
            button.setProperty("deilawSoundInstalled", True)

            # Navigation has its own click.wav in switch_page().
            if hasattr(self, "nav_buttons") and button in self.nav_buttons:
                continue

            button.clicked.connect(
                lambda checked=False, self=self: self.play_ui_sound("button")
            )

    def refresh_button_sounds(self):
        """Attach sound to buttons created dynamically after startup."""
        self.install_button_sounds()
        if self.memo_overlay is not None:
            buttons = (
                self.memo_overlay.findChildren(QPushButton)
                + self.memo_overlay.findChildren(QToolButton)
            )
            for button in buttons:
                if button.property("deilawSoundInstalled"):
                    continue
                button.setProperty("deilawSoundInstalled", True)
                button.clicked.connect(
                    lambda checked=False, self=self:
                    self.play_ui_sound("button")
                )

    def play_ui_sound(self, kind="click"):
        """Play short non-blocking DeiLaw UI sounds."""
        if not self.app_settings.get("ui_sounds", True):
            return

        if winsound is None:
            QApplication.beep()
            return

        custom_files = {
            "click": "click.wav",
            "button": "button.wav",
            "toggle": "toggle.wav",
            "success": "save.wav",
            "open": "memo_open.wav",
            "close": "memo_close.wav",
            "law_update_complete": "law_update_complete.wav",
            "ai_complete": "ai_complete.wav",
        }

        try:
            filename = custom_files.get(kind)
            if filename:
                sound_path = self.get_ui_sound_path(filename)
                if sound_path:
                    winsound.PlaySound(
                        sound_path,
                        winsound.SND_FILENAME
                        | winsound.SND_ASYNC
                        | winsound.SND_NODEFAULT,
                    )
                    return

            aliases = {
                "open": "SystemAsterisk",
                "close": "SystemAsterisk",
                "warning": "SystemExclamation",
            }
            winsound.PlaySound(
                aliases.get(kind, "SystemAsterisk"),
                winsound.SND_ALIAS
                | winsound.SND_ASYNC
                | winsound.SND_NODEFAULT,
            )
        except Exception:
            pass


    def create_manual_backup(self):
        try:
            self.save_current_profile_runtime()
            self.save_app_settings()
            folder = self.backup_manager.create_backup("manual")
            self.settings_status.setText(
                f"Резервная копия создана: {folder.name}"
            )
            self.show_save_toast("Резервная копия создана")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Резервная копия",
                f"Не удалось создать резервную копию:\n{exc}",
            )

    def restore_latest_backup(self):
        answer = QMessageBox.question(
            self,
            "Восстановление DeiLaw",
            "Восстановить последнюю резервную копию настроек и "
            "пользовательских данных? Текущие файлы будут заменены.\n\n"
            "После восстановления рекомендуется перезапустить DeiLaw.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            folder, restored = self.backup_manager.restore_latest()
            QMessageBox.information(
                self,
                "Восстановление завершено",
                f"Восстановлено файлов: {restored}.\n"
                f"Копия: {folder.name}\n\nПерезапустите DeiLaw, чтобы все данные перечитались.",
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Восстановление",
                str(exc),
            )

    def update_active_nav(self, index):
        if not hasattr(self, "pages"):
            return

        pairs = [
            (getattr(self, "search_nav", None), getattr(self, "search_page", None)),
            (getattr(self, "laws_nav", None), getattr(self, "laws_page", None)),
            (getattr(self, "favorites_nav", None), getattr(self, "favorites_page", None)),
            (getattr(self, "gibdd_charter_nav", None), getattr(self, "gibdd_charter_page", None)),
            (getattr(self, "assistant_nav", None), getattr(self, "assistant_page", None)),
            (getattr(self, "memo_nav", None), getattr(self, "memo_page", None)),
            (getattr(self, "calculator_nav", None), getattr(self, "calculator_page", None)),
            (getattr(self, "update_nav", None), getattr(self, "update_page", None)),
            (getattr(self, "update_history_nav", None), getattr(self, "update_history_page", None)),
            (getattr(self, "ahk_nav", None), getattr(self, "ahk_page", None)),
            (getattr(self, "community_nav", None), getattr(self, "community_page", None)),
            (getattr(self, "settings_nav", None), getattr(self, "settings_page", None)),
        ]
        for button, page in pairs:
            if button is None:
                continue
            page_index = self.pages.indexOf(page) if page is not None else -1
            button.setChecked(page_index == index)

    def switch_page(self, index):
        current = self.pages.currentIndex()
        if (
            current == self.settings_page_index
            and index != self.settings_page_index
            and not self.confirm_settings_leave()
        ):
            return

        if index == self.assistant_page_index and self.safe_mode:
            QMessageBox.information(
                self,
                "Безопасный режим",
                "DeiLaw AI отключён в безопасном режиме. Перезапустите программу "
                "обычно, когда проблема запуска будет устранена.",
            )
            self.update_active_nav(current)
            return

        # RP assistant is still in beta. Show a clear warning before entering
        # the page unless the user suppressed repeats for this app session.
        if (
            index == self.assistant_page_index
            and current != index
            and not self.rp_beta_warning_suppressed
        ):
            if not self.show_rp_beta_warning():
                self.update_active_nav(current)
                return

        self.pages.setCurrentIndex(index)
        self.update_active_nav(index)
        if current != index:
            self.play_ui_sound("click")

        if index == self.ahk_page_index:
            self.refresh_ahk_bindings_page()

        if index == self.update_page_index:
            self.refresh_update_history()

        if index == self.update_history_page_index:
            self.refresh_update_history()

        if index == self.favorites_page_index:
            self.refresh_favorites_page()

        if index == self.community_page_index:
            self.refresh_community_reviews()

        if index == self.settings_page_index:
            self.refresh_status_page()
            self.settings_original_font_size = int(
                self.app_settings.get("program_font_size", 14)
            )
            self.settings_original_overlay_opacity = int(
                self.app_settings.get("memo_overlay_opacity", self.app_settings.get("overlay_opacity", 100))
            )
            self.settings_original_overlay_opacities = {
                "search_overlay_opacity": int(self.app_settings.get("search_overlay_opacity", 100)),
                "memo_overlay_opacity": int(self.app_settings.get("memo_overlay_opacity", self.app_settings.get("overlay_opacity", 100))),
                "calculator_overlay_opacity": int(self.app_settings.get("calculator_overlay_opacity", 100)),
            }
            self.settings_original_theme = self.app_settings.get("theme", "dark")
            self.settings_original_visual_theme = self.app_settings.get(
                "visual_theme",
                "default",
            )
            self.capture_settings_snapshot()

    def reset_memo_layout_state(self):
        self.app_settings["overlay_geometry"] = ""
        self.app_settings["overlay_column_sizes"] = []
        self.app_settings["overlay_section_sizes"] = {}
        self.app_settings["memo_main_sizes"] = [650, 220]
        self.app_settings["memo_column_sizes"] = []
        self.app_settings["memo_section_sizes"] = {}
        self.save_app_settings()

        if hasattr(self, "memo_main_splitter"):
            self.memo_main_splitter.setSizes([650, 220])

        if self.memo_overlay is not None:
            self.memo_overlay.resize(
                int(self.app_settings.get("overlay_width", 1250)),
                int(self.app_settings.get("overlay_height", 650)),
            )
            self.build_memo_overlay()

        self.settings_status.setText(
            "Размеры и положение памятки сброшены."
        )

    def apply_app_settings(self):
        previous_overlay_width = int(
            self.app_settings.get("overlay_width", 1250)
        )
        previous_overlay_height = int(
            self.app_settings.get("overlay_height", 650)
        )

        hotkey = self.settings_hotkey.hotkey_text().strip() or "F8"
        search_hotkey = self.settings_search_hotkey.hotkey_text().strip() or "F7"
        calculator_hotkey = (
            self.settings_calculator_hotkey.hotkey_text().strip()
            or "F9"
        )

        remembered_close_behavior = str(
            self.app_settings.get("close_behavior", "ask") or "ask"
        ).strip().lower()
        remember_close_choice = (
            self.settings_remember_close_choice.isChecked()
            and remembered_close_behavior in ("minimize", "exit")
        )
        if not remember_close_choice:
            remembered_close_behavior = "ask"

        self.app_settings.update({
            "memo_hotkey": hotkey,
            "search_hotkey": search_hotkey,
            "calculator_hotkey": calculator_hotkey,
            "theme": "light" if self.settings_theme_switch.isChecked() else "dark",
            "visual_theme": (
                self.settings_visual_theme.currentData()
                or "default"
            ),
            "global_memo_hotkey": self.settings_global_hotkey.isChecked(),
            "global_search_hotkey": self.settings_global_search_hotkey.isChecked(),
            "global_calculator_hotkey": self.settings_global_calculator_hotkey.isChecked(),
            "block_quick_hotkeys_when_main_open": (
                self.settings_block_hotkeys_when_main_open.isChecked()
            ),
            "memo_always_on_top": self.settings_topmost.isChecked(),
            "remember_memo_layout": self.settings_remember_layout.isChecked(),
            "show_penalties": self.settings_penalties.isChecked(),
            "confirm_delete_column": self.settings_confirm_delete.isChecked(),
            "search_limit": self.settings_search_limit.value(),
            "overlay_opacity": max(40, min(100, int(self.settings_memo_overlay_opacity.currentText() or 100))),
            "search_overlay_opacity": max(40, min(100, int(self.settings_search_overlay_opacity.currentText() or 100))),
            "memo_overlay_opacity": max(40, min(100, int(self.settings_memo_overlay_opacity.currentText() or 100))),
            "calculator_overlay_opacity": max(40, min(100, int(self.settings_calculator_overlay_opacity.currentText() or 100))),
            "program_font_size": self.settings_program_font.value(),
            "overlay_click_through": self.settings_click_through.isChecked(),
            "overlay_width": self.settings_overlay_width.value(),
            "overlay_height": self.settings_overlay_height.value(),
            "memo_card_font_size": self.settings_card_font.value(),
            "memo_card_min_height": self.settings_card_height.value(),
            "show_article_summary": self.settings_show_summary.isChecked(),
            "show_article_code": self.settings_show_code.isChecked(),
            "enter_runs_search": self.settings_enter_search.isChecked(),
            "double_click_opens_article": self.settings_double_open.isChecked(),
            "ui_sounds": self.settings_ui_sounds.isChecked(),
            "report_reply_voice": self.settings_report_reply_voice.isChecked(),
            "auto_check_program_updates": True,
            "auto_update_laws_on_startup": self.settings_auto_law_updates.isChecked(),
            "law_update_interval_hours": int(self.settings_law_update_interval.currentData() or 6),
            "update_channel": (
                self.settings_update_channel.currentData() or "stable"
            ),
            "close_behavior": remembered_close_behavior,
            "remember_close_choice": remember_close_choice,
        })

        quick_window_size_changed = (
            previous_overlay_width
            != int(self.app_settings.get("overlay_width", 1250))
            or previous_overlay_height
            != int(self.app_settings.get("overlay_height", 650))
        )

        if quick_window_size_changed:
            # A manually remembered geometry must not override an explicit
            # size change made in Settings.
            self.app_settings["overlay_geometry"] = ""
            self.app_settings["search_overlay_geometry"] = ""
            self.app_settings["calculator_overlay_geometry"] = ""

        self.save_app_settings()
        self.apply_style()
        self.install_memo_shortcut()
        self.update_program_update_monitor_state()
        self.refresh_memo_board()
        self.apply_overlay_window_settings()

        if quick_window_size_changed:
            self.apply_quick_window_size_settings()

        self.refresh_close_behavior_settings_ui()
        self.settings_status.setText(
            f"Сохранено. Поиск: {search_hotkey} • "
            f"Памятка: {hotkey} • Калькулятор: {calculator_hotkey}"
        )
        self.play_ui_sound("success")
        self.show_save_toast("Сохранено")
        self.capture_settings_snapshot()
        self.settings_original_font_size = int(
            self.app_settings.get("program_font_size", 14)
        )
        self.settings_original_overlay_opacity = int(
            self.app_settings.get("memo_overlay_opacity", self.app_settings.get("overlay_opacity", 100))
        )
        self.settings_original_overlay_opacities = {
            "search_overlay_opacity": int(self.app_settings.get("search_overlay_opacity", 100)),
            "memo_overlay_opacity": int(self.app_settings.get("memo_overlay_opacity", self.app_settings.get("overlay_opacity", 100))),
            "calculator_overlay_opacity": int(self.app_settings.get("calculator_overlay_opacity", 100)),
        }
        self.settings_original_theme = self.app_settings.get("theme", "dark")
        self.settings_original_visual_theme = self.app_settings.get(
            "visual_theme",
            "default",
        )


    def reset_app_settings(self):
        self.settings_hotkey.setKeySequence(QKeySequence("F8"))
        self.settings_search_hotkey.setKeySequence(QKeySequence("F7"))
        self.settings_calculator_hotkey.setKeySequence(QKeySequence("F9"))
        self.settings_theme_switch.setChecked(False)
        self.settings_visual_theme.setCurrentIndex(0)
        self.settings_global_hotkey.setChecked(True)
        self.settings_global_search_hotkey.setChecked(True)
        self.settings_global_calculator_hotkey.setChecked(True)
        self.settings_block_hotkeys_when_main_open.setChecked(True)
        self.settings_topmost.setChecked(True)
        self.settings_remember_layout.setChecked(True)
        self.settings_penalties.setChecked(True)
        self.settings_confirm_delete.setChecked(True)
        self.settings_search_limit.setValue(100)
        self.settings_search_overlay_opacity.setCurrentText("100")
        self.settings_memo_overlay_opacity.setCurrentText("100")
        self.settings_calculator_overlay_opacity.setCurrentText("100")
        self.settings_program_font.setValue(14)
        self.settings_click_through.setChecked(False)
        self.settings_overlay_width.setValue(1250)
        self.settings_overlay_height.setValue(650)
        self.settings_card_font.setValue(14)
        self.settings_card_height.setValue(72)
        self.settings_show_summary.setChecked(True)
        self.settings_show_code.setChecked(True)
        self.settings_enter_search.setChecked(True)
        self.settings_double_open.setChecked(True)
        self.settings_ui_sounds.setChecked(True)
        self.settings_report_reply_voice.setChecked(True)
        self.settings_auto_program_updates.setChecked(True)
        self.settings_auto_law_updates.setChecked(True)
        law_default_index = self.settings_law_update_interval.findData(6)
        self.settings_law_update_interval.setCurrentIndex(max(0, law_default_index))
        default_channel = load_update_config().get("channel", "stable")
        default_channel_index = self.settings_update_channel.findData(
            default_channel
        )
        self.settings_update_channel.setCurrentIndex(
            default_channel_index if default_channel_index >= 0 else 0
        )
        self.settings_remember_close_choice.setChecked(False)
        self.app_settings["close_behavior"] = "ask"
        self.app_settings["remember_close_choice"] = False
        self.apply_app_settings()

    def _probe_windows_hotkey(self, sequence):
        if sys.platform != "win32":
            return "недоступно вне Windows"
        parsed = self.parse_windows_hotkey(sequence)
        if parsed is None:
            return "не распознано"

        normalized = SingleHotkeyEdit.normalize_spec(sequence).casefold()
        own = {
            SingleHotkeyEdit.normalize_spec(
                self.app_settings.get("search_hotkey", "F7")
            ).casefold(),
            SingleHotkeyEdit.normalize_spec(
                self.app_settings.get("memo_hotkey", "F8")
            ).casefold(),
            SingleHotkeyEdit.normalize_spec(
                self.app_settings.get("calculator_hotkey", "F9")
            ).casefold(),
        }
        if normalized in own:
            return "используется самим DeiLaw"

        modifiers, vk = parsed
        probe_id = 0xD39A
        try:
            ok = bool(
                ctypes.windll.user32.RegisterHotKey(
                    None, probe_id, modifiers, vk
                )
            )
            if ok:
                ctypes.windll.user32.UnregisterHotKey(None, probe_id)
                return "свободен для глобальной регистрации"
            return "занят другой программой или зарезервирован Windows"
        except Exception as exc:
            return f"не удалось проверить: {exc}"

    def _format_hotkey_diagnostic(self, name, sequence, enabled, registered):
        parsed = self.parse_windows_hotkey(sequence)
        if parsed is None:
            parsed_text = "НЕ РАСПОЗНАН"
        else:
            modifiers, vk = parsed
            parsed_text = f"VK=0x{vk:02X}, modifiers=0x{modifiers:04X}"

        if sys.platform != "win32":
            register_text = "глобальная регистрация доступна только в Windows"
        elif not enabled:
            register_text = "глобальный режим выключен"
        else:
            register_text = "зарегистрирован" if registered else "НЕ зарегистрирован"

        return (
            f"{name}: {sequence}\n"
            f"  распознавание: {parsed_text}\n"
            f"  Windows: {register_text}"
        )

    def build_hotkey_diagnostics_text(self, test_sequence=None):
        lines = [
            f"DeiLaw {APP_VERSION} — диагностика биндов",
            f"ОС: {platform.platform()}",
            "",
            self._format_hotkey_diagnostic(
                "Quick Search",
                self.app_settings.get("search_hotkey", "F7"),
                bool(self.app_settings.get("global_search_hotkey", True)),
                bool(self.search_global_hotkey_registered),
            ),
            "",
            self._format_hotkey_diagnostic(
                "Quick Memo",
                self.app_settings.get("memo_hotkey", "F8"),
                bool(self.app_settings.get("global_memo_hotkey", True)),
                bool(self.global_hotkey_registered),
            ),
            "",
            self._format_hotkey_diagnostic(
                "Quick Calculator",
                self.app_settings.get("calculator_hotkey", "F9"),
                bool(self.app_settings.get("global_calculator_hotkey", True)),
                bool(self.calculator_global_hotkey_registered),
            ),
            "",
            "Блокировать бинды при развёрнутом DeiLaw: "
            + (
                "да"
                if self.app_settings.get(
                    "block_quick_hotkeys_when_main_open", True
                )
                else "нет"
            ),
            "Состояние главного окна: "
            + (
                "развёрнуто"
                if self.isVisible() and not self.isMinimized()
                else "свёрнуто / трей"
            ),
        ]

        if sys.platform == "win32":
            try:
                layout = int(ctypes.windll.user32.GetKeyboardLayout(0))
                lines.append(f"Windows keyboard layout: 0x{layout & 0xFFFF:04X}")
            except Exception:
                pass

        if test_sequence:
            lines.extend([
                "",
                "Тест выбранной клавиши:",
                self._format_hotkey_diagnostic(
                    "Test",
                    test_sequence,
                    False,
                    False,
                ),
                f"  занятость: {self._probe_windows_hotkey(test_sequence)}",
            ])
        return "\n".join(lines)

    def show_hotkey_diagnostics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Диагностика биндов DeiLaw")
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("⌨ Диагностика горячих клавиш")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Ниже виден статус текущих биндов. Для проверки отдельной "
            "клавиши нажмите её в поле: DeiLaw покажет NumPad/модификаторы, "
            "Windows VK-код и проверит, свободен ли глобальный бинд."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        test_row = QHBoxLayout()
        test_edit = SingleHotkeyEdit(QKeySequence(""))
        test_button = QPushButton("Проверить клавишу")
        test_row.addWidget(test_edit, stretch=1)
        test_row.addWidget(test_button)
        layout.addLayout(test_row)

        output = QTextBrowser()
        output.setPlainText(self.build_hotkey_diagnostics_text())
        layout.addWidget(output, stretch=1)

        def refresh_test():
            seq = test_edit.hotkey_text().strip()
            output.setPlainText(
                self.build_hotkey_diagnostics_text(seq or None)
            )

        test_button.clicked.connect(refresh_test)
        test_edit.keySequenceChanged.connect(lambda _seq: refresh_test())

        buttons = QHBoxLayout()
        copy_button = QPushButton("Скопировать диагностику")
        close_button = QPushButton("Закрыть")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(output.toPlainText())
        )
        close_button.clicked.connect(dialog.accept)
        buttons.addWidget(copy_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        dialog.exec()

    def _recent_log_tail(self, max_lines=80):
        candidates = [
            Path("data/deilaw.log"),
            Path(sys.executable).resolve().parent / "data" / "deilaw.log"
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent / "data" / "deilaw.log",
        ]
        for path in candidates:
            try:
                if path.is_file():
                    lines = path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    return "\n".join(lines[-max_lines:])
            except Exception:
                continue
        return "Лог пока пуст или недоступен."

    def build_bug_report_text(self, description=""):
        channel = self.app_settings.get("update_channel", "stable")
        theme = self.app_settings.get("theme", "dark")
        visual = self.app_settings.get("visual_theme", "default")
        ai_line = "Cloud AI: Supabase Edge Function / OpenAI • локальные модели не используются"

        report = [
            "=== DeiLaw Bug Report ===",
            f"Версия: {APP_VERSION}",
            f"ОС: {platform.platform()}",
            f"Python: {platform.python_version()}",
            f"Канал обновлений: {channel}",
            f"Тема: {theme} / {visual}",
            f"Профиль: {self.active_profile}",
            f"Безопасный режим: {'да' if self.safe_mode else 'нет'}",
            f"AI: {ai_line}",
            "",
            "Описание пользователя:",
            description.strip() or "Не заполнено",
            "",
            "--- Бинды ---",
            self.build_hotkey_diagnostics_text(),
            "",
            "--- Последние строки лога ---",
            self._recent_log_tail(),
        ]
        return "\n".join(report)

    def _latest_deilaw_log_file(self):
        candidates = [
            Path("data/deilaw.log"),
            Path(sys.executable).resolve().parent / "data" / "deilaw.log"
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent / "data" / "deilaw.log",
        ]
        existing = []
        for path in candidates:
            try:
                if path.is_file():
                    existing.append(path.resolve())
            except Exception:
                pass
        if not existing:
            return None
        return max(existing, key=lambda path: path.stat().st_mtime)

    def show_bug_report_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Сообщить о проблеме — DeiLaw")
        dialog.resize(820, 790)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("🐞 Сообщить о проблеме")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Отчёт отправится разработчику прямо из DeiLaw. "
            "Версия программы, Windows, тема, бинды и состояние AI "
            "добавляются автоматически."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        category_row = QHBoxLayout()
        category_row.addWidget(QLabel("Категория"))
        category = QComboBox()
        category.addItems([
            "Бинды",
            "Поиск",
            "AI",
            "Устав",
            "Калькулятор",
            "Интерфейс",
            "Обновление",
            "Производительность",
            "Другое",
        ])
        category_row.addWidget(category, stretch=1)
        layout.addLayout(category_row)

        report_title = QLineEdit()
        report_title.setPlaceholderText(
            "Короткое название проблемы"
        )
        report_title.setMaxLength(150)
        layout.addWidget(report_title)

        description = QTextEdit()
        description.setPlaceholderText(
            "Что произошло? Опишите проблему своими словами."
        )
        description.setMaximumHeight(135)
        layout.addWidget(description)

        reproduce = QTextEdit()
        reproduce.setPlaceholderText(
            "Как повторить проблему?\n"
            "1. ...\n2. ...\n3. ..."
        )
        reproduce.setMaximumHeight(120)
        layout.addWidget(reproduce)

        expected = QTextEdit()
        expected.setPlaceholderText(
            "Что должно было произойти?"
        )
        expected.setMaximumHeight(90)
        layout.addWidget(expected)

        include_logs = QCheckBox(
            "Приложить последние строки технического лога"
        )
        include_logs.setChecked(True)
        layout.addWidget(include_logs)

        attachment_paths = []
        attachments_title = QLabel("📎 Вложения — до 5 файлов, не более 10 МБ каждый")
        attachments_title.setObjectName("muted")
        layout.addWidget(attachments_title)

        attachments_list = QListWidget()
        attachments_list.setMaximumHeight(92)
        attachments_list.setToolTip("PNG, JPG, WEBP, TXT, LOG или ZIP")
        layout.addWidget(attachments_list)

        attachment_buttons = QHBoxLayout()
        add_attachment_button = QPushButton("＋ Прикрепить файлы")
        add_log_button = QPushButton("📄 Приложить последний лог")
        remove_attachment_button = QPushButton("Убрать выбранное")
        attachment_buttons.addWidget(add_attachment_button)
        attachment_buttons.addWidget(add_log_button)
        attachment_buttons.addWidget(remove_attachment_button)
        attachment_buttons.addStretch()
        layout.addLayout(attachment_buttons)

        def refresh_attachment_list():
            attachments_list.clear()
            for file_path in attachment_paths:
                path = Path(file_path)
                try:
                    size_mb = path.stat().st_size / (1024 * 1024)
                    size_text = f"{size_mb:.1f} МБ" if size_mb >= 0.1 else f"{max(1, path.stat().st_size // 1024)} КБ"
                except Exception:
                    size_text = "?"
                attachments_list.addItem(f"{path.name} • {size_text}")

        def append_attachment(path_value):
            path = Path(path_value)
            if not path.is_file():
                status.setText(f"Файл не найден: {path}")
                return
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".txt", ".log", ".zip"}:
                status.setText("Поддерживаются PNG, JPG, WEBP, TXT, LOG и ZIP.")
                return
            if path.stat().st_size > 10 * 1024 * 1024:
                status.setText(f"{path.name}: файл больше 10 МБ.")
                return
            normalized = str(path.resolve())
            if normalized in attachment_paths:
                return
            if len(attachment_paths) >= 5:
                status.setText("К одному репорту можно прикрепить не больше 5 файлов.")
                return
            attachment_paths.append(normalized)
            refresh_attachment_list()
            status.setText("")

        def choose_attachments():
            paths, _ = QFileDialog.getOpenFileNames(
                dialog,
                "Вложения к репорту",
                "",
                "Поддерживаемые файлы (*.png *.jpg *.jpeg *.webp *.txt *.log *.zip);;Все файлы (*)",
            )
            for path in paths:
                append_attachment(path)

        def attach_last_log():
            path = self._latest_deilaw_log_file()
            if path is None:
                status.setText("Последний deilaw.log не найден.")
                return
            append_attachment(path)

        def remove_selected_attachment():
            row = attachments_list.currentRow()
            if 0 <= row < len(attachment_paths):
                attachment_paths.pop(row)
                refresh_attachment_list()

        add_attachment_button.clicked.connect(choose_attachments)
        add_log_button.clicked.connect(attach_last_log)
        remove_attachment_button.clicked.connect(remove_selected_attachment)
        attachments_list.itemDoubleClicked.connect(lambda _item: remove_selected_attachment())

        diagnostics = QTextBrowser()
        diagnostics.setMaximumHeight(170)
        diagnostics.setPlainText(
            self.build_bug_report_text(
                "Техническая информация будет приложена к онлайн-отчёту."
            )
        )
        layout.addWidget(diagnostics)

        status = QLabel("")
        status.setObjectName("muted")
        status.setWordWrap(True)
        layout.addWidget(status)

        buttons = QHBoxLayout()
        copy_button = QPushButton("Скопировать технический отчёт")
        cancel_button = QPushButton("Отмена")
        send_button = QPushButton("Отправить отчёт")
        send_button.setObjectName("primary")

        buttons.addWidget(copy_button)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(send_button)
        layout.addLayout(buttons)

        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.build_bug_report_text(
                    description.toPlainText()
                )
            )
        )
        cancel_button.clicked.connect(dialog.reject)

        def send_report():
            title_value = report_title.text().strip()
            description_value = description.toPlainText().strip()

            if len(title_value) < 3:
                status.setText(
                    "Укажите короткое название проблемы."
                )
                return
            if len(description_value) < 3:
                status.setText(
                    "Опишите, что произошло."
                )
                return

            payload = self._bug_report_payload(
                category=category.currentText(),
                title=title_value,
                description=description_value,
                reproduce_steps=reproduce.toPlainText().strip(),
                expected_result=expected.toPlainText().strip(),
                include_logs=include_logs.isChecked(),
            )

            send_button.setEnabled(False)
            cancel_button.setEnabled(False)
            status.setText("Отправляю отчёт разработчику…")

            def sent(_result):
                result = dict(_result or {})
                attachment_errors = list(result.get("_attachment_upload_errors") or [])
                uploaded_count = len(result.get("_uploaded_attachments") or [])
                self.play_ui_sound("success")
                self.show_save_toast("Отчёт отправлен")
                dialog.accept()
                message = (
                    "Отчёт отправлен разработчику. "
                    "Его статус и переписка доступны в разделе «Репорты»."
                )
                if attachment_paths:
                    message += f"\n\nВложений загружено: {uploaded_count}/{len(attachment_paths)}."
                if attachment_errors:
                    message += "\n\nНе удалось загрузить некоторые вложения:\n• " + "\n• ".join(attachment_errors)
                QMessageBox.information(self, "DeiLaw", message)

            def failed(message):
                send_button.setEnabled(True)
                cancel_button.setEnabled(True)
                status.setText(
                    f"Не удалось отправить отчёт: {message}"
                )

            self._run_community_task(
                self.community_client.submit_bug_report_with_attachments,
                args=(payload, list(attachment_paths)),
                on_success=sent,
                on_error=failed,
            )

        send_button.clicked.connect(send_report)
        dialog.exec()

    def _normalized_hotkey_setting(self, key, default):
        value = SingleHotkeyEdit.normalize_spec(
            self.app_settings.get(key, default)
        )
        if not value:
            value = default
        self.app_settings[key] = value
        return value

    def install_memo_shortcut(self):
        """Install local shortcut and, on Windows, the optional system-wide hotkey."""
        if self.memo_shortcut is not None:
            self.memo_shortcut.setEnabled(False)
            self.memo_shortcut.deleteLater()

        sequence_text = self._normalized_hotkey_setting("memo_hotkey", "F8")
        self.memo_shortcut = QShortcut(
            SingleHotkeyEdit.sequence_from_spec(sequence_text), self
        )
        self.memo_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.memo_shortcut.activated.connect(self.toggle_memo_overlay)

        self.unregister_global_hotkey()

        if (
            not self.safe_mode
            and sys.platform == "win32"
            and self.app_settings.get("global_memo_hotkey", True)
        ):
            ok, message = self.register_global_hotkey(sequence_text)
            if hasattr(self, "settings_status"):
                self.settings_status.setText(message)

        # Second independent hotkey: quick search overlay.
        if self.search_shortcut is not None:
            self.search_shortcut.setEnabled(False)
            self.search_shortcut.deleteLater()

        search_sequence = self._normalized_hotkey_setting("search_hotkey", "F7")
        self.search_shortcut = QShortcut(
            SingleHotkeyEdit.sequence_from_spec(search_sequence), self
        )
        self.search_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.search_shortcut.activated.connect(self.toggle_search_overlay)

        self.unregister_search_global_hotkey()
        if (
            not self.safe_mode
            and sys.platform == "win32"
            and self.app_settings.get("global_search_hotkey", True)
        ):
            ok, search_message = self.register_search_global_hotkey(search_sequence)
            if hasattr(self, "settings_status") and not ok:
                self.settings_status.setText(search_message)

        # Third independent hotkey: penalty calculator.
        if self.calculator_shortcut is not None:
            self.calculator_shortcut.setEnabled(False)
            self.calculator_shortcut.deleteLater()

        calculator_sequence = self._normalized_hotkey_setting(
            "calculator_hotkey", "F9"
        )
        self.calculator_shortcut = QShortcut(
            SingleHotkeyEdit.sequence_from_spec(calculator_sequence),
            self,
        )
        self.calculator_shortcut.setContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self.calculator_shortcut.activated.connect(
            self.toggle_calculator_hotkey
        )

        self.unregister_calculator_global_hotkey()
        if (
            not self.safe_mode
            and sys.platform == "win32"
            and self.app_settings.get("global_calculator_hotkey", True)
        ):
            ok, calculator_message = self.register_calculator_global_hotkey(
                calculator_sequence
            )
            if hasattr(self, "settings_status") and not ok:
                self.settings_status.setText(calculator_message)

        # RP AHK binds are real global Windows hotkeys too. They work directly
        # from DeiLaw; AutoHotkey itself is only required for exported .ahk files.
        self.install_ahk_runtime_hotkeys()

    @staticmethod
    def _enum_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(value.value)

    @staticmethod
    def _cyrillic_vk_fallback(character):
        """Map Russian JCUKEN characters to the corresponding Windows VK."""
        mapping = {
            "Й": 0x51,  # Q
            "Ц": 0x57,  # W
            "У": 0x45,  # E
            "К": 0x52,  # R
            "Е": 0x54,  # T
            "Н": 0x59,  # Y
            "Г": 0x55,  # U
            "Ш": 0x49,  # I
            "Щ": 0x4F,  # O
            "З": 0x50,  # P
            "Х": 0xDB,  # [
            "Ъ": 0xDD,  # ]
            "Ф": 0x41,  # A
            "Ы": 0x53,  # S
            "В": 0x44,  # D
            "А": 0x46,  # F
            "П": 0x47,  # G
            "Р": 0x48,  # H
            "О": 0x4A,  # J
            "Л": 0x4B,  # K
            "Д": 0x4C,  # L
            "Ж": 0xBA,  # ;
            "Э": 0xDE,  # '
            "Я": 0x5A,  # Z
            "Ч": 0x58,  # X
            "С": 0x43,  # C
            "М": 0x56,  # V
            "И": 0x42,  # B
            "Т": 0x4E,  # N
            "Ь": 0x4D,  # M
            "Б": 0xBC,  # ,
            "Ю": 0xBE,  # .
            "Ё": 0xC0,  # `
        }
        return mapping.get(str(character or "").upper())

    def _windows_vk_from_character(self, character):
        """Resolve a printable character for the current Windows layout."""
        char = str(character or "")
        if len(char) != 1:
            return None

        upper = char.upper()
        if "A" <= upper <= "Z":
            return ord(upper)

        if "0" <= char <= "9":
            return ord(char)

        # Common OEM keys. These are also useful if the active layout changes
        # after the shortcut was saved.
        oem = {
            ";": 0xBA,
            "=": 0xBB,
            ",": 0xBC,
            "-": 0xBD,
            ".": 0xBE,
            "/": 0xBF,
            "`": 0xC0,
            "[": 0xDB,
            "\\": 0xDC,
            "]": 0xDD,
            "'": 0xDE,
        }
        if char in oem:
            return oem[char]

        # First ask the active Windows keyboard layout. This makes shortcuts
        # captured while the Russian layout is active work normally.
        if sys.platform == "win32":
            try:
                user32 = ctypes.windll.user32
                layout = user32.GetKeyboardLayout(0)
                result = int(
                    user32.VkKeyScanExW(
                        ord(char),
                        layout,
                    )
                )
                if result != -1:
                    return result & 0xFF
            except Exception:
                pass

        # If the user switched layout after saving the bind, keep standard
        # Russian physical-key mapping as a stable fallback.
        return self._cyrillic_vk_fallback(char)

    def parse_windows_hotkey(self, sequence_text):
        """Convert a Qt shortcut into Win32 modifiers/VK.

        Supports F1-F24, Latin/Cyrillic keys, NumPad digits/operators,
        navigation keys, lock keys and common punctuation.
        """
        raw = str(sequence_text or "").strip()
        if not raw:
            return None

        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002
        MOD_SHIFT = 0x0004
        MOD_WIN = 0x0008
        MOD_NOREPEAT = 0x4000

        modifiers = MOD_NOREPEAT
        numpad = False
        qt_key_value = None

        # Preferred path: let Qt parse its own QKeySequence format. This keeps
        # KeypadModifier and modifiers intact and is much more reliable than
        # splitting the visible text by '+'.
        try:
            sequence = QKeySequence(raw)
            if not sequence.isEmpty():
                combo = sequence[0]
                qt_modifiers = combo.keyboardModifiers()
                qt_key_value = self._enum_int(combo.key())

                if qt_modifiers & Qt.KeyboardModifier.ControlModifier:
                    modifiers |= MOD_CONTROL
                if qt_modifiers & Qt.KeyboardModifier.AltModifier:
                    modifiers |= MOD_ALT
                if qt_modifiers & Qt.KeyboardModifier.ShiftModifier:
                    modifiers |= MOD_SHIFT
                if qt_modifiers & Qt.KeyboardModifier.MetaModifier:
                    modifiers |= MOD_WIN

                numpad = bool(
                    qt_modifiers
                    & Qt.KeyboardModifier.KeypadModifier
                )
        except Exception:
            qt_key_value = None

        if qt_key_value is not None:
            key_0 = self._enum_int(Qt.Key.Key_0)
            key_9 = self._enum_int(Qt.Key.Key_9)
            key_a = self._enum_int(Qt.Key.Key_A)
            key_z = self._enum_int(Qt.Key.Key_Z)
            key_f1 = self._enum_int(Qt.Key.Key_F1)
            key_f24 = self._enum_int(Qt.Key.Key_F24)

            # Numeric keypad has distinct VK codes.
            if numpad and key_0 <= qt_key_value <= key_9:
                return (
                    modifiers,
                    0x60 + (qt_key_value - key_0),
                )

            if numpad:
                keypad_ops = {
                    self._enum_int(Qt.Key.Key_Asterisk): 0x6A,
                    self._enum_int(Qt.Key.Key_Plus): 0x6B,
                    self._enum_int(Qt.Key.Key_Minus): 0x6D,
                    self._enum_int(Qt.Key.Key_Period): 0x6E,
                    self._enum_int(Qt.Key.Key_Comma): 0x6E,
                    self._enum_int(Qt.Key.Key_Slash): 0x6F,
                    self._enum_int(Qt.Key.Key_Enter): 0x0D,
                    self._enum_int(Qt.Key.Key_Return): 0x0D,
                }
                if qt_key_value in keypad_ops:
                    return modifiers, keypad_ops[qt_key_value]

            if key_f1 <= qt_key_value <= key_f24:
                return (
                    modifiers,
                    0x70 + (qt_key_value - key_f1),
                )

            if key_a <= qt_key_value <= key_z:
                return modifiers, qt_key_value

            if key_0 <= qt_key_value <= key_9:
                return modifiers, qt_key_value

            qt_special = {
                self._enum_int(Qt.Key.Key_Backspace): 0x08,
                self._enum_int(Qt.Key.Key_Tab): 0x09,
                self._enum_int(Qt.Key.Key_Backtab): 0x09,
                self._enum_int(Qt.Key.Key_Return): 0x0D,
                self._enum_int(Qt.Key.Key_Enter): 0x0D,
                self._enum_int(Qt.Key.Key_Pause): 0x13,
                self._enum_int(Qt.Key.Key_CapsLock): 0x14,
                self._enum_int(Qt.Key.Key_Escape): 0x1B,
                self._enum_int(Qt.Key.Key_Space): 0x20,
                self._enum_int(Qt.Key.Key_PageUp): 0x21,
                self._enum_int(Qt.Key.Key_PageDown): 0x22,
                self._enum_int(Qt.Key.Key_End): 0x23,
                self._enum_int(Qt.Key.Key_Home): 0x24,
                self._enum_int(Qt.Key.Key_Left): 0x25,
                self._enum_int(Qt.Key.Key_Up): 0x26,
                self._enum_int(Qt.Key.Key_Right): 0x27,
                self._enum_int(Qt.Key.Key_Down): 0x28,
                self._enum_int(Qt.Key.Key_Print): 0x2C,
                self._enum_int(Qt.Key.Key_Insert): 0x2D,
                self._enum_int(Qt.Key.Key_Delete): 0x2E,
                self._enum_int(Qt.Key.Key_NumLock): 0x90,
                self._enum_int(Qt.Key.Key_ScrollLock): 0x91,
            }
            if qt_key_value in qt_special:
                if (
                    qt_key_value
                    == self._enum_int(Qt.Key.Key_Backtab)
                ):
                    modifiers |= MOD_SHIFT
                return modifiers, qt_special[qt_key_value]

            # Printable Unicode keys, including Cyrillic.
            if 0 < qt_key_value <= 0x10FFFF:
                try:
                    char_vk = self._windows_vk_from_character(
                        chr(qt_key_value)
                    )
                except (ValueError, OverflowError):
                    char_vk = None
                if char_vk is not None:
                    return modifiers, char_vk

        # Compatibility fallback for old/localized settings strings.
        parts = [
            part.strip()
            for part in raw.split("+")
            if part.strip()
        ]
        if not parts:
            return None

        key_name = parts[-1]
        modifier_names = {
            part.casefold()
            for part in parts[:-1]
        }

        if modifier_names & {"ctrl", "control"}:
            modifiers |= MOD_CONTROL
        if "alt" in modifier_names:
            modifiers |= MOD_ALT
        if "shift" in modifier_names:
            modifiers |= MOD_SHIFT
        if modifier_names & {"meta", "win", "windows"}:
            modifiers |= MOD_WIN

        numpad = bool(
            modifier_names
            & {
                "num",
                "numpad",
                "keypad",
                "keypadmodifier",
            }
        )

        normalized = (
            key_name.strip()
            .upper()
            .replace(" ", "")
            .replace("_", "")
        )

        # Also accept strings like Num1 / Numpad1 / KP1.
        for prefix in ("NUMPAD", "NUM", "KP"):
            if normalized.startswith(prefix):
                numpad = True
                normalized = normalized[len(prefix):]
                break

        if numpad:
            if len(normalized) == 1 and normalized.isdigit():
                return modifiers, 0x60 + int(normalized)

            keypad_names = {
                "+": 0x6B,
                "PLUS": 0x6B,
                "ADD": 0x6B,
                "-": 0x6D,
                "MINUS": 0x6D,
                "SUBTRACT": 0x6D,
                "*": 0x6A,
                "ASTERISK": 0x6A,
                "MULTIPLY": 0x6A,
                "/": 0x6F,
                "SLASH": 0x6F,
                "DIVIDE": 0x6F,
                ".": 0x6E,
                ",": 0x6E,
                "DECIMAL": 0x6E,
                "ENTER": 0x0D,
                "RETURN": 0x0D,
            }
            if normalized in keypad_names:
                return modifiers, keypad_names[normalized]

        if normalized.startswith("F") and normalized[1:].isdigit():
            number = int(normalized[1:])
            if 1 <= number <= 24:
                return modifiers, 0x70 + number - 1

        special = {
            "BACKSPACE": 0x08,
            "TAB": 0x09,
            "ENTER": 0x0D,
            "RETURN": 0x0D,
            "PAUSE": 0x13,
            "CAPSLOCK": 0x14,
            "ESC": 0x1B,
            "ESCAPE": 0x1B,
            "SPACE": 0x20,
            "PAGEUP": 0x21,
            "PGUP": 0x21,
            "PAGEDOWN": 0x22,
            "PGDOWN": 0x22,
            "END": 0x23,
            "HOME": 0x24,
            "LEFT": 0x25,
            "UP": 0x26,
            "RIGHT": 0x27,
            "DOWN": 0x28,
            "PRINT": 0x2C,
            "PRINTSCREEN": 0x2C,
            "PRTSC": 0x2C,
            "INSERT": 0x2D,
            "INS": 0x2D,
            "DELETE": 0x2E,
            "DEL": 0x2E,
            "NUMLOCK": 0x90,
            "SCROLLLOCK": 0x91,
        }
        if normalized in special:
            return modifiers, special[normalized]

        if len(key_name) == 1:
            char_vk = self._windows_vk_from_character(key_name)
            if char_vk is not None:
                return modifiers, char_vk

        return None

    def unregister_ahk_runtime_hotkeys(self):
        app = QApplication.instance()
        for item in list(getattr(self, "ahk_runtime_hotkeys", [])):
            hotkey_id = int(item.get("id", 0))
            event_filter = item.get("filter")
            if sys.platform == "win32" and hotkey_id:
                try:
                    ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
                except Exception:
                    pass
            if app is not None and event_filter is not None:
                try:
                    app.removeNativeEventFilter(event_filter)
                except Exception:
                    pass
        self.ahk_runtime_hotkeys = []

    def install_ahk_runtime_hotkeys(self):
        """Register enabled RP binds so they work directly from DeiLaw."""
        self.unregister_ahk_runtime_hotkeys()

        if self.safe_mode:
            summary = "AHK бинды отключены в безопасном режиме."
            self.ahk_runtime_last_summary = summary
            if hasattr(self, "ahk_status_label"):
                self.ahk_status_label.setText(summary)
            return summary

        if sys.platform != "win32":
            summary = "Глобальные RP-бинды сейчас поддерживаются только в Windows."
            self.ahk_runtime_last_summary = summary
            if hasattr(self, "ahk_status_label"):
                self.ahk_status_label.setText(summary)
            return summary

        rows = [
            dict(item)
            for item in self.ahk_bind_store.bindings()
            if item.get("enabled", True)
        ]
        if not rows:
            summary = "Активных RP-биндов пока нет. Создай и сохрани бинд."
            self.ahk_runtime_last_summary = summary
            if hasattr(self, "ahk_status_label"):
                self.ahk_status_label.setText(summary)
            return summary

        app = QApplication.instance()
        registered = 0
        failed = []
        base_id = 0xD400

        for index, record in enumerate(rows):
            spec = str(record.get("hotkey") or "").strip()
            parsed = self.parse_windows_hotkey(spec)
            if parsed is None:
                failed.append(f"{record.get('name') or spec}: неподдерживаемая клавиша")
                continue

            modifiers, vk = parsed
            hotkey_id = base_id + index
            callback = lambda rec=dict(record): self.execute_ahk_runtime_binding(rec)
            event_filter = WindowsHotkeyFilter(callback, hotkey_id)
            if app is not None:
                app.installNativeEventFilter(event_filter)

            ok = bool(
                ctypes.windll.user32.RegisterHotKey(
                    None,
                    hotkey_id,
                    modifiers,
                    vk,
                )
            )
            if ok:
                self.ahk_runtime_hotkeys.append({
                    "id": hotkey_id,
                    "filter": event_filter,
                    "record": record,
                })
                registered += 1
            else:
                if app is not None:
                    try:
                        app.removeNativeEventFilter(event_filter)
                    except Exception:
                        pass
                failed.append(
                    f"{record.get('name') or 'Бинд'} ({spec}) — клавиша занята"
                )

        summary = f"RP-бинды DeiLaw активны: {registered}/{len(rows)}"
        if failed:
            summary += ". Не зарегистрированы: " + "; ".join(failed[:4])
            if len(failed) > 4:
                summary += f"; ещё {len(failed) - 4}"
        else:
            summary += ". AutoHotkey для работы внутри DeiLaw не нужен."

        self.ahk_runtime_last_summary = summary
        if hasattr(self, "ahk_status_label"):
            self.ahk_status_label.setText(summary)
        return summary

    @staticmethod
    def _windows_send_vk(vk):
        if sys.platform != "win32":
            return False

        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002

        ULONG_PTR = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.wintypes.LONG),
                ("dy", ctypes.wintypes.LONG),
                ("mouseData", ctypes.wintypes.DWORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.wintypes.WORD),
                ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", ctypes.wintypes.DWORD),
                ("wParamL", ctypes.wintypes.WORD),
                ("wParamH", ctypes.wintypes.WORD),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [
                ("type", ctypes.wintypes.DWORD),
                ("u", INPUTUNION),
            ]

        events = (INPUT * 2)()
        events[0].type = INPUT_KEYBOARD
        events[0].ki = KEYBDINPUT(vk, 0, 0, 0, 0)
        events[1].type = INPUT_KEYBOARD
        events[1].ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0)
        sent = ctypes.windll.user32.SendInput(
            2,
            ctypes.byref(events),
            ctypes.sizeof(INPUT),
        )
        return int(sent) == 2

    @staticmethod
    def _windows_send_unicode_text(value):
        if sys.platform != "win32":
            return False

        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_UNICODE = 0x0004
        ULONG_PTR = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.wintypes.LONG),
                ("dy", ctypes.wintypes.LONG),
                ("mouseData", ctypes.wintypes.DWORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.wintypes.WORD),
                ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", ctypes.wintypes.DWORD),
                ("wParamL", ctypes.wintypes.WORD),
                ("wParamH", ctypes.wintypes.WORD),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [
                ("type", ctypes.wintypes.DWORD),
                ("u", INPUTUNION),
            ]

        utf16 = str(value or "").encode("utf-16-le")
        units = [
            int.from_bytes(utf16[i:i + 2], "little")
            for i in range(0, len(utf16), 2)
        ]
        if not units:
            return True

        events = (INPUT * (len(units) * 2))()
        for index, unit in enumerate(units):
            down = index * 2
            up = down + 1
            events[down].type = INPUT_KEYBOARD
            events[down].ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0)
            events[up].type = INPUT_KEYBOARD
            events[up].ki = KEYBDINPUT(
                0,
                unit,
                KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                0,
                0,
            )

        sent = ctypes.windll.user32.SendInput(
            len(events),
            ctypes.byref(events),
            ctypes.sizeof(INPUT),
        )
        return int(sent) == len(events)

    @staticmethod
    def _wait_ahk_modifier_release(timeout=0.85):
        if sys.platform != "win32":
            return
        # Wait until the physical modifier used in the macro hotkey is released;
        # otherwise Ctrl/Alt/Shift can accidentally modify the synthetic chat key.
        modifier_vks = (0x10, 0x11, 0x12, 0x5B, 0x5C)
        deadline = time.monotonic() + max(0.05, float(timeout))
        while time.monotonic() < deadline:
            if not any(
                ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
                for vk in modifier_vks
            ):
                return
            time.sleep(0.015)

    def execute_ahk_runtime_binding(self, record):
        if self.safe_mode or sys.platform != "win32":
            return
        if self.ahk_runtime_busy:
            return

        record = dict(record or {})
        commands = [
            str(line).strip()
            for line in record.get("commands", [])
            if str(line).strip()
        ]
        if not commands or not record.get("enabled", True):
            return

        self.ahk_runtime_busy = True

        def worker():
            acquired = self.ahk_runtime_lock.acquire(blocking=False)
            if not acquired:
                self.ahk_runtime_busy = False
                return
            try:
                self._wait_ahk_modifier_release()

                chat_key = str(
                    self.ahk_bind_store.data.get("chat_key", "t")
                    or "t"
                ).strip()
                parsed_chat = self.parse_windows_hotkey(chat_key)
                if parsed_chat is None:
                    return
                chat_modifiers, chat_vk = parsed_chat
                # MOD_NOREPEAT is always present. Any other modifier means the
                # chat-open setting is not a single key and should not be sent.
                if chat_modifiers & 0x000F:
                    return

                open_delay = max(
                    40,
                    min(
                        3000,
                        int(
                            self.ahk_bind_store.data.get(
                                "open_chat_delay",
                                140,
                            )
                        ),
                    ),
                )
                delay_ms = max(
                    0,
                    min(10000, int(record.get("delay_ms", 350))),
                )

                # Give the physical macro key a tiny moment to leave the game
                # input buffer before opening the chat.
                time.sleep(0.035)

                for command in commands:
                    self._windows_send_vk(chat_vk)
                    time.sleep(open_delay / 1000.0)
                    self._windows_send_unicode_text(command)
                    self._windows_send_vk(0x0D)
                    if delay_ms:
                        time.sleep(delay_ms / 1000.0)
            finally:
                self.ahk_runtime_lock.release()
                self.ahk_runtime_busy = False

        threading.Thread(
            target=worker,
            name="DeiLaw-AHK-RP-Bind",
            daemon=True,
        ).start()

    def register_global_hotkey(self, sequence_text):
        parsed = self.parse_windows_hotkey(sequence_text)
        if parsed is None:
            return False, (
                f"Бинд «{sequence_text}» нельзя использовать как глобальный. "
                "Поддерживаются F1–F24, кириллица/латиница, NumPad, стрелки, "
                "служебные клавиши и сочетания Ctrl/Alt/Shift/Win."
            )

        modifiers, vk = parsed

        if self.global_hotkey_filter is None:
            self.global_hotkey_filter = WindowsHotkeyFilter(
                self.toggle_memo_overlay,
                self.global_hotkey_id,
            )
            QApplication.instance().installNativeEventFilter(
                self.global_hotkey_filter
            )

        ok = bool(
            ctypes.windll.user32.RegisterHotKey(
                None,
                self.global_hotkey_id,
                modifiers,
                vk,
            )
        )
        self.global_hotkey_registered = ok

        if ok:
            return True, f"Глобальный бинд активен: {sequence_text}"

        return False, (
            f"Windows не смог зарегистрировать «{sequence_text}». "
            "Возможно, клавиша уже занята другой программой."
        )

    def unregister_global_hotkey(self):
        if sys.platform == "win32" and self.global_hotkey_registered:
            ctypes.windll.user32.UnregisterHotKey(
                None,
                self.global_hotkey_id,
            )
        self.global_hotkey_registered = False

    def register_search_global_hotkey(self, sequence_text):
        parsed = self.parse_windows_hotkey(sequence_text)
        if parsed is None:
            return False, (
                f"Бинд поисковика «{sequence_text}» нельзя использовать как глобальный."
            )

        modifiers, vk = parsed
        if self.search_global_hotkey_filter is None:
            self.search_global_hotkey_filter = WindowsHotkeyFilter(
                self.toggle_search_overlay,
                self.search_global_hotkey_id,
            )
            QApplication.instance().installNativeEventFilter(
                self.search_global_hotkey_filter
            )

        ok = bool(
            ctypes.windll.user32.RegisterHotKey(
                None,
                self.search_global_hotkey_id,
                modifiers,
                vk,
            )
        )
        self.search_global_hotkey_registered = ok
        if ok:
            return True, f"Глобальный бинд поисковика активен: {sequence_text}"
        return False, (
            f"Windows не смог зарегистрировать бинд поисковика «{sequence_text}». "
            "Возможно, клавиша уже занята другой программой."
        )

    def unregister_search_global_hotkey(self):
        if sys.platform == "win32" and self.search_global_hotkey_registered:
            ctypes.windll.user32.UnregisterHotKey(
                None,
                self.search_global_hotkey_id,
            )
        self.search_global_hotkey_registered = False

    def register_calculator_global_hotkey(self, sequence_text):
        parsed = self.parse_windows_hotkey(sequence_text)
        if parsed is None:
            return False, (
                f"Бинд калькулятора «{sequence_text}» нельзя использовать "
                "как глобальный."
            )

        modifiers, vk = parsed
        if self.calculator_global_hotkey_filter is None:
            self.calculator_global_hotkey_filter = WindowsHotkeyFilter(
                self.toggle_calculator_hotkey,
                self.calculator_global_hotkey_id,
            )
            QApplication.instance().installNativeEventFilter(
                self.calculator_global_hotkey_filter
            )

        ok = bool(
            ctypes.windll.user32.RegisterHotKey(
                None,
                self.calculator_global_hotkey_id,
                modifiers,
                vk,
            )
        )
        self.calculator_global_hotkey_registered = ok
        if ok:
            return True, (
                f"Глобальный бинд калькулятора активен: {sequence_text}"
            )

        return False, (
            f"Windows не смог зарегистрировать бинд калькулятора "
            f"«{sequence_text}». Возможно, клавиша уже занята."
        )

    def unregister_calculator_global_hotkey(self):
        if (
            sys.platform == "win32"
            and self.calculator_global_hotkey_registered
        ):
            ctypes.windll.user32.UnregisterHotKey(
                None,
                self.calculator_global_hotkey_id,
            )
        self.calculator_global_hotkey_registered = False

    def _quick_hotkeys_blocked_by_main_window(self):
        """Optionally block quick-overlay hotkeys only while DeiLaw is open.

        Hidden-to-tray and minimized states intentionally return False, so
        global hotkeys keep working in the game after closing DeiLaw to tray.
        """
        enabled = bool(
            self.app_settings.get(
                "block_quick_hotkeys_when_main_open",
                True,
            )
        )
        if not enabled:
            return False

        return self.isVisible() and not self.isMinimized()

    def toggle_memo_overlay(self):
        if self.safe_mode:
            return
        # Prevent the same physical key press from being handled once by
        # QShortcut and again by WM_HOTKEY.
        now = self.memo_hotkey_timer.elapsed()
        if now - self.last_memo_hotkey_ms < 180:
            return
        self.last_memo_hotkey_ms = now

        if self.memo_overlay is not None and self.memo_overlay.isVisible():
            self.memo_overlay.hide()
            self.play_ui_sound("close")
            return

        if self._quick_hotkeys_blocked_by_main_window():
            return

        self.show_memo_overlay(auto_fit=True)
        self.play_ui_sound("open")
        if self.memo_overlay is not None:
            self.memo_overlay.show()
            self.apply_overlay_background_opacity()
            QTimer.singleShot(0, self.apply_overlay_background_opacity)
            self.apply_overlay_click_through()
            self.memo_overlay.raise_()

            # In click-through mode the game must keep focus.
            if not self.app_settings.get("overlay_click_through", False):
                self.memo_overlay.activateWindow()

    def toggle_search_overlay(self):
        """Show/hide the fast search window with its own hotkey."""
        if self.safe_mode:
            return
        now = self.search_hotkey_timer.elapsed()
        if now - self.last_search_hotkey_ms < 180:
            return
        self.last_search_hotkey_ms = now

        if self.search_overlay is not None and self.search_overlay.isVisible():
            self.search_overlay.hide()
            self.play_ui_sound("close")
            return

        if self._quick_hotkeys_blocked_by_main_window():
            return

        self.show_search_overlay()
        self.play_ui_sound("open")

    def toggle_calculator_hotkey(self):
        """Show/hide the standalone F9 Quick Calculator overlay."""
        if self.safe_mode:
            return
        now = self.calculator_hotkey_timer.elapsed()
        if now - self.last_calculator_hotkey_ms < 180:
            return
        self.last_calculator_hotkey_ms = now

        if (
            self.calculator_overlay is not None
            and self.calculator_overlay.isVisible()
        ):
            self.hide_calculator_overlay()
            self.play_ui_sound("close")
            return

        if self._quick_hotkeys_blocked_by_main_window():
            return

        self.show_calculator_overlay()
        self.play_ui_sound("open")

    def apply_calculator_overlay_style(self):
        """Apply the active DeiLaw theme/opacity to the F9 calculator."""
        if self.calculator_overlay is None:
            return

        percent = max(
            40,
            min(100, int(self.app_settings.get("calculator_overlay_opacity", self.app_settings.get("overlay_opacity", 100)))),
        )
        alpha = max(110, min(255, round(255 * percent / 100)))
        light = self.app_settings.get("theme", "dark") == "light"

        palette = self._visual_theme_overlay_palette(light)

        def rgba(key):
            r, g, b = palette[key]
            return f"rgba({r}, {g}, {b}, {alpha})"

        def rgb(key):
            r, g, b = palette[key]
            return f"rgb({r}, {g}, {b})"

        dialog_bg = rgba("dialog")
        surface_bg = rgba("surface")
        card_bg = rgba("surface")
        button_bg = rgba("button")
        button_hover = rgba("button_hover")
        border = rgba("border")
        text_color = rgb("text")
        muted = rgb("muted")
        handle = rgba("handle")
        selected = rgb("selected")
        selected_text = rgb("selected_text")
        primary = rgb("primary")
        primary_border = rgb("primary_border")

        self.calculator_overlay.setStyleSheet(
            f"""
            QDialog#calculatorOverlayWindow {{
                background-color: {dialog_bg};
                border: 1px solid {border};
                border-radius: 10px;
                color: {text_color};
            }}
            QLabel {{
                background: transparent;
                color: {text_color};
            }}
            QLabel#calcOverlayMuted {{
                color: {muted};
            }}
            QLabel#calcOverlayTotal {{
                font-size: 22px;
                font-weight: 700;
                color: {text_color};
            }}
            QFrame#calcOverlaySummaryCard {{
                background-color: {card_bg};
                border: 1px solid {border};
                border-radius: 9px;
            }}
            QLineEdit, QListWidget, QTextBrowser {{
                background-color: {surface_bg};
                border: 1px solid {border};
                border-radius: 7px;
                color: {text_color};
                padding: 8px;
                selection-background-color: {selected};
                selection-color: {selected_text};
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 5px;
            }}
            QListWidget::item:selected {{
                background-color: {selected};
                color: {selected_text};
            }}
            QPushButton {{
                background-color: {button_bg};
                border: 1px solid {border};
                border-radius: 7px;
                color: {text_color};
                padding: 8px 14px;
            }}
            QPushButton:hover {{
                background-color: {button_hover};
            }}
            QPushButton#primary {{
                background-color: {primary};
                border: 1px solid {primary_border};
                color: white;
            }}
            QSplitter::handle {{
                background-color: {handle};
            }}
            QScrollBar {{
                background: transparent;
            }}
            QScrollBar::handle {{
                background-color: {handle};
                border-radius: 4px;
            }}
            """
        )

    def save_calculator_overlay_geometry(self):
        if self.calculator_overlay is None:
            return
        self.app_settings["calculator_overlay_geometry"] = (
            bytes(
                self.calculator_overlay.saveGeometry().toBase64()
            ).decode("ascii")
        )
        self.save_app_settings()

    def hide_calculator_overlay(self):
        if self.calculator_overlay is None:
            return
        self.save_calculator_overlay_geometry()
        self.calculator_overlay.hide()

    def _position_new_calculator_overlay(self):
        """Center a fresh F9 overlay on the monitor under the mouse cursor."""
        if self.calculator_overlay is None:
            return

        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        area = screen.availableGeometry()
        width, height = self._quick_window_requested_size(
            840,
            500,
        )
        self.calculator_overlay.resize(width, height)
        self.calculator_overlay.move(
            area.x() + max(0, (area.width() - width) // 2),
            area.y() + max(0, (area.height() - height) // 2),
        )

    def show_calculator_overlay(self):
        """Create/show the floating F9 calculator without opening DeiLaw itself."""
        if self.calculator_overlay is None:
            self.calculator_overlay = QDialog(None)
            self.calculator_overlay.setObjectName(
                "calculatorOverlayWindow"
            )
            self.calculator_overlay.setWindowTitle(
                "DeiLaw — Быстрый калькулятор"
            )
            self.calculator_overlay.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground,
                True,
            )
            self.calculator_overlay.installEventFilter(self)

            flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            if self.app_settings.get("memo_always_on_top", True):
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.calculator_overlay.setWindowFlags(flags)
            self.calculator_overlay.setMinimumSize(840, 500)

            layout = QVBoxLayout(self.calculator_overlay)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)

            top = QHBoxLayout()
            title = QLabel("🧮 Быстрый калькулятор")
            title.setObjectName("pageTitle")
            hint = QLabel("F9 — скрыть")
            hint.setObjectName("calcOverlayMuted")
            close = QPushButton("Скрыть")
            close.clicked.connect(self.hide_calculator_overlay)
            top.addWidget(title)
            top.addSpacing(8)
            top.addWidget(hint)
            top.addStretch()
            top.addWidget(close)
            layout.addLayout(top)

            search_row = QHBoxLayout()
            self.calculator_overlay_input = QLineEdit()
            self.calculator_overlay_input.setPlaceholderText(
                "Статья или ситуация: 91 УК РФ, 9.8 КоАП, побег от ДПС..."
            )
            self.calculator_overlay_input.setClearButtonEnabled(True)
            self.calculator_overlay_add_button = QPushButton("+ Добавить")
            self.calculator_overlay_add_button.setObjectName("primary")
            search_row.addWidget(
                self.calculator_overlay_input,
                stretch=1,
            )
            search_row.addWidget(
                self.calculator_overlay_add_button
            )
            layout.addLayout(search_row)

            self.calculator_overlay_suggestion_model = QStringListModel(
                self.calculator_overlay
            )
            self.calculator_overlay_completer = QCompleter(
                self.calculator_overlay_suggestion_model,
                self.calculator_overlay_input,
            )
            self.calculator_overlay_completer.setCompletionMode(
                QCompleter.CompletionMode.PopupCompletion
            )
            self.calculator_overlay_completer.setCaseSensitivity(
                Qt.CaseSensitivity.CaseInsensitive
            )
            self.calculator_overlay_completer.setFilterMode(
                Qt.MatchFlag.MatchContains
            )
            self.calculator_overlay_completer.setMaxVisibleItems(10)
            self.calculator_overlay_input.setCompleter(
                self.calculator_overlay_completer
            )

            self.calculator_overlay_suggestion_timer = QTimer(
                self.calculator_overlay
            )
            self.calculator_overlay_suggestion_timer.setSingleShot(True)
            self.calculator_overlay_suggestion_timer.setInterval(220)
            self.calculator_overlay_suggestion_timer.timeout.connect(
                self.run_calculator_overlay_suggestions
            )

            summary = QHBoxLayout()

            fine_card = QFrame()
            fine_card.setObjectName("calcOverlaySummaryCard")
            fine_layout = QVBoxLayout(fine_card)
            fine_layout.setContentsMargins(12, 10, 12, 10)
            fine_title = QLabel("💰 Штрафы")
            fine_title.setObjectName("calcOverlayMuted")
            self.calculator_overlay_fine_total = QLabel("0 ₽")
            self.calculator_overlay_fine_total.setObjectName(
                "calcOverlayTotal"
            )
            fine_layout.addWidget(fine_title)
            fine_layout.addWidget(
                self.calculator_overlay_fine_total
            )

            prison_card = QFrame()
            prison_card.setObjectName("calcOverlaySummaryCard")
            prison_layout = QVBoxLayout(prison_card)
            prison_layout.setContentsMargins(12, 10, 12, 10)
            prison_title = QLabel("⛓ Лишение свободы")
            prison_title.setObjectName("calcOverlayMuted")
            self.calculator_overlay_prison_total = QLabel("0 дней")
            self.calculator_overlay_prison_total.setObjectName(
                "calcOverlayTotal"
            )
            prison_layout.addWidget(prison_title)
            prison_layout.addWidget(
                self.calculator_overlay_prison_total
            )

            count_card = QFrame()
            count_card.setObjectName("calcOverlaySummaryCard")
            count_layout = QVBoxLayout(count_card)
            count_layout.setContentsMargins(12, 10, 12, 10)
            count_title = QLabel("📚 Выбрано")
            count_title.setObjectName("calcOverlayMuted")
            self.calculator_overlay_count_total = QLabel("0 статей")
            self.calculator_overlay_count_total.setObjectName(
                "calcOverlayTotal"
            )
            count_layout.addWidget(count_title)
            count_layout.addWidget(
                self.calculator_overlay_count_total
            )

            arrest_card = QFrame()
            arrest_card.setObjectName("calcOverlaySummaryCard")
            arrest_layout = QVBoxLayout(arrest_card)
            arrest_layout.setContentsMargins(12, 10, 12, 10)
            arrest_title = QLabel("🚔 Административный арест")
            arrest_title.setObjectName("calcOverlayMuted")
            self.calculator_overlay_arrest_total = QLabel("0 дней")
            self.calculator_overlay_arrest_total.setObjectName(
                "calcOverlayTotal"
            )
            arrest_layout.addWidget(arrest_title)
            arrest_layout.addWidget(
                self.calculator_overlay_arrest_total
            )

            summary.addWidget(fine_card, stretch=1)
            summary.addWidget(prison_card, stretch=1)
            summary.addWidget(arrest_card, stretch=1)
            summary.addWidget(count_card, stretch=1)
            layout.addLayout(summary)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setChildrenCollapsible(False)
            splitter.setHandleWidth(7)

            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)
            selected_title = QLabel("Выбранные статьи")
            selected_title.setObjectName("calcOverlayMuted")
            self.calculator_overlay_list = QListWidget()
            self.calculator_overlay_list.setWordWrap(True)
            self.calculator_overlay_list.setSpacing(4)
            left_layout.addWidget(selected_title)
            left_layout.addWidget(
                self.calculator_overlay_list,
                stretch=1,
            )

            controls = QHBoxLayout()
            self.calculator_overlay_remove_button = QPushButton(
                "− Удалить"
            )
            self.calculator_overlay_clear_button = QPushButton(
                "Очистить"
            )
            self.calculator_overlay_copy_button = QPushButton(
                "Копировать итог"
            )
            controls.addWidget(
                self.calculator_overlay_remove_button
            )
            controls.addWidget(
                self.calculator_overlay_clear_button
            )
            controls.addStretch()
            controls.addWidget(
                self.calculator_overlay_copy_button
            )
            left_layout.addLayout(controls)

            right = QWidget()
            right_layout = QVBoxLayout(right)
            right_layout.setContentsMargins(0, 0, 0, 0)
            details_title = QLabel(
                "Источник и распознанное наказание"
            )
            details_title.setObjectName("calcOverlayMuted")
            self.calculator_overlay_details = QTextBrowser()
            right_layout.addWidget(details_title)
            right_layout.addWidget(
                self.calculator_overlay_details,
                stretch=1,
            )

            splitter.addWidget(left)
            splitter.addWidget(right)
            splitter.setSizes([430, 760])
            layout.addWidget(splitter, stretch=1)

            self.calculator_overlay_status = QLabel(
                "Добавьте статью или опишите ситуацию."
            )
            self.calculator_overlay_status.setObjectName(
                "calcOverlayMuted"
            )
            self.calculator_overlay_status.setWordWrap(True)
            layout.addWidget(self.calculator_overlay_status)

            self.calculator_overlay_input.textChanged.connect(
                self.schedule_calculator_overlay_suggestions
            )
            self.calculator_overlay_completer.activated[str].connect(
                self.on_calculator_overlay_suggestion_activated
            )
            self.calculator_overlay_input.returnPressed.connect(
                self.add_penalty_calculator_article_from_overlay
            )
            self.calculator_overlay_add_button.clicked.connect(
                self.add_penalty_calculator_article_from_overlay
            )
            self.calculator_overlay_list.currentRowChanged.connect(
                self.show_penalty_calculator_overlay_entry
            )
            self.calculator_overlay_remove_button.clicked.connect(
                self.remove_penalty_calculator_overlay_article
            )
            self.calculator_overlay_clear_button.clicked.connect(
                self.clear_penalty_calculator_from_overlay
            )
            self.calculator_overlay_copy_button.clicked.connect(
                self.copy_penalty_calculator_from_overlay
            )

            geometry = self.app_settings.get(
                "calculator_overlay_geometry",
                "",
            )
            if geometry:
                try:
                    self.calculator_overlay.restoreGeometry(
                        QByteArray.fromBase64(
                            geometry.encode("ascii")
                        )
                    )
                except Exception:
                    self._position_new_calculator_overlay()
            else:
                self._position_new_calculator_overlay()

        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if self.app_settings.get("memo_always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.calculator_overlay.setWindowFlags(flags)

        self.apply_calculator_overlay_style()
        self.refresh_penalty_calculator_overlay()

        self.calculator_overlay.show()
        self.calculator_overlay.raise_()
        self.calculator_overlay.activateWindow()
        self.calculator_overlay_input.setFocus()
        self.calculator_overlay_input.selectAll()

    def schedule_calculator_overlay_suggestions(self, text):
        query = (text or "").strip()
        self._pending_calculator_overlay_query = query
        self.calculator_overlay_suggestion_timer.stop()

        if len(query) < 2:
            self.calculator_overlay_suggestion_model.setStringList([])
            return

        self.calculator_overlay_suggestion_timer.start()

    def run_calculator_overlay_suggestions(self):
        query = str(
            getattr(
                self,
                "_pending_calculator_overlay_query",
                "",
            ) or ""
        ).strip()

        if (
            not query
            or query
            != self.calculator_overlay_input.text().strip()
        ):
            return

        try:
            suggestions = self.smart_text_search.suggest(
                query,
                limit=10,
                history=self.search_history,
            )
        except Exception:
            suggestions = []

        if query != self.calculator_overlay_input.text().strip():
            return

        self.calculator_overlay_suggestion_model.setStringList(
            suggestions
        )
        if suggestions:
            self.calculator_overlay_completer.setCompletionPrefix("")
            self.calculator_overlay_completer.complete()

    def on_calculator_overlay_suggestion_activated(
        self,
        suggestion,
    ):
        suggestion = str(suggestion or "").strip()
        if not suggestion:
            return
        self.calculator_overlay_input.setText(suggestion)
        self.calculator_overlay_input.setCursorPosition(
            len(suggestion)
        )

    def _show_calculator_overlay_choices(self, articles):
        menu = QMenu(self.calculator_overlay)
        for article in list(articles)[:10]:
            action = menu.addAction(
                self._penalty_calculator_article_label(article)
            )
            action.triggered.connect(
                lambda checked=False, row=article:
                self.commit_penalty_calculator_article_from_overlay(
                    row
                )
            )

        self.calculator_overlay_choice_menu = menu
        point = self.calculator_overlay_input.mapToGlobal(
            self.calculator_overlay_input.rect().bottomLeft()
        )
        menu.popup(point)

    def add_penalty_calculator_article_from_overlay(self):
        query = self.calculator_overlay_input.text().strip()
        if not query:
            self.calculator_overlay_status.setText(
                "Введите статью или описание ситуации."
            )
            return

        self.calculator_overlay_suggestion_timer.stop()

        exact = self._smart_article_search(query)
        if exact:
            self.commit_penalty_calculator_article_from_overlay(
                exact[0]
            )
            return

        self.calculator_overlay_status.setText(
            "Ищу подходящие статьи…"
        )
        QApplication.processEvents()

        try:
            results = list(
                self.smart_text_search.search(query, 10)
            )
        except Exception:
            results = []

        if not results:
            self.calculator_overlay_status.setText(
                "Подходящие статьи не найдены. "
                "Проверьте запрос или обновите базу."
            )
            return

        if len(results) == 1:
            self.commit_penalty_calculator_article_from_overlay(
                results[0]
            )
            return

        self.calculator_overlay_status.setText(
            "Выберите нужную статью из найденных вариантов."
        )
        self._show_calculator_overlay_choices(results)

    def commit_penalty_calculator_article_from_overlay(
        self,
        article,
    ):
        before = len(self.penalty_calc_entries)
        self.commit_penalty_calculator_article(
            article,
            dialog_parent=self.calculator_overlay,
        )
        after = len(self.penalty_calc_entries)

        if after > before:
            self.calculator_overlay_input.clear()

        if hasattr(self, "calc_status"):
            self.calculator_overlay_status.setText(
                self.calc_status.text()
            )
        self.refresh_penalty_calculator_overlay()

        if after > 0:
            self.calculator_overlay_list.setCurrentRow(
                after - 1
            )

    def _calculator_overlay_item_text(self, entry):
        lines = [self._penalty_calculator_article_label(entry)]

        fine_min = entry.get("fine_min")
        fine_max = entry.get("fine_max")
        selected_type = entry.get("selected_penalty_type")
        fine_is_active = selected_type in (None, "fine")
        prison_is_active = selected_type in (None, "prison")
        arrest_is_active = selected_type in (None, "arrest")

        if selected_type == "fine":
            lines.append("✓ Выбрано: штраф")
        elif selected_type == "prison":
            lines.append("✓ Выбрано: лишение свободы")
        elif selected_type == "arrest":
            lines.append("✓ Выбрано: административный арест")

        if fine_is_active and (fine_min is not None or fine_max is not None):
            low = fine_min if fine_min is not None else fine_max
            high = fine_max if fine_max is not None else fine_min
            selected_fine = entry.get("selected_fine_amount")

            if selected_fine is not None and low != high:
                lines.append(
                    "💰 "
                    f"{self._format_calc_money(selected_fine)} "
                    f"(из {self._format_calc_money(low)} – "
                    f"{self._format_calc_money(high)})"
                )
            elif selected_fine is not None:
                lines.append(
                    f"💰 {self._format_calc_money(selected_fine)}"
                )
            elif low == high:
                lines.append(
                    f"💰 {self._format_calc_money(low)}"
                )
            else:
                lines.append(
                    "💰 "
                    f"{self._format_calc_money(low)} – "
                    f"{self._format_calc_money(high)}"
                )

        prison_min = entry.get("prison_min_days")
        prison_max = entry.get("prison_max_days")
        arrest_min = entry.get("arrest_min_days")
        arrest_max = entry.get("arrest_max_days")
        if prison_is_active and (
            prison_min is not None or prison_max is not None
        ):
            low = (
                prison_min
                if prison_min is not None
                else prison_max
            )
            high = (
                prison_max
                if prison_max is not None
                else prison_min
            )
            if low == high:
                lines.append(
                    f"⛓ {self._format_calc_duration(low)}"
                )
            else:
                lines.append(
                    "⛓ "
                    f"{self._format_calc_duration(low)} – "
                    f"{self._format_calc_duration(high)}"
                )

        if arrest_is_active and (
            arrest_min is not None or arrest_max is not None
        ):
            low = arrest_min if arrest_min is not None else arrest_max
            high = arrest_max if arrest_max is not None else arrest_min
            if low == high:
                lines.append(
                    f"🚔 {self._format_calc_duration(low)}"
                )
            else:
                lines.append(
                    "🚔 "
                    f"{self._format_calc_duration(low)} – "
                    f"{self._format_calc_duration(high)}"
                )

        if entry.get("alternative") and selected_type is None:
            lines.append(
                "↔ альтернативное наказание: «или / либо»"
            )

        if not entry.get("recognized"):
            lines.append("⚠ числовая санкция не распознана")

        return "\n".join(lines)

    def refresh_penalty_calculator_overlay(self):
        if self.calculator_overlay is None:
            return

        current = self.calculator_overlay_list.currentRow()
        self.calculator_overlay_list.clear()

        for index, entry in enumerate(self.penalty_calc_entries):
            item = QListWidgetItem(
                self._calculator_overlay_item_text(entry)
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(
                entry.get("clause")
                or entry.get("content")
                or ""
            )
            self.calculator_overlay_list.addItem(item)

        if hasattr(self, "calc_fine_total"):
            self.calculator_overlay_fine_total.setText(
                self.calc_fine_total.text()
            )
            self.calculator_overlay_prison_total.setText(
                self.calc_prison_total.text()
            )
            self.calculator_overlay_arrest_total.setText(
                self.calc_arrest_total.text()
            )
            self.calculator_overlay_count_total.setText(
                self.calc_count_total.text()
            )

        if self.penalty_calc_entries:
            current = max(
                0,
                min(
                    current,
                    len(self.penalty_calc_entries) - 1,
                ),
            )
            self.calculator_overlay_list.setCurrentRow(current)
        else:
            self.calculator_overlay_details.clear()

    def show_penalty_calculator_overlay_entry(self, row):
        if row < 0 or row >= len(self.penalty_calc_entries):
            self.calculator_overlay_details.clear()
            return

        # Reuse the exact same details renderer as the main Calculator page,
        # then mirror its text into the overlay.
        self.show_penalty_calculator_entry(row)
        self.calculator_overlay_details.setPlainText(
            self.calc_details.toPlainText()
        )

    def remove_penalty_calculator_overlay_article(self):
        row = self.calculator_overlay_list.currentRow()
        if row < 0 or row >= len(self.penalty_calc_entries):
            return

        self.penalty_calc_entries.pop(row)
        self.refresh_penalty_calculator()
        self.calculator_overlay_status.setText(
            "Статья удалена из расчёта."
        )

    def clear_penalty_calculator_from_overlay(self):
        self.clear_penalty_calculator()
        self.calculator_overlay_status.setText(
            "Расчёт очищен."
        )

    def copy_penalty_calculator_from_overlay(self):
        self.copy_penalty_calculator_total()
        if self.penalty_calc_entries:
            self.calculator_overlay_status.setText(
                "Итог скопирован в буфер обмена."
            )
        else:
            self.calculator_overlay_status.setText(
                "Сначала добавьте статьи."
            )

    def apply_search_overlay_style(self):
        """Apply the active theme to the quick-search overlay."""
        if self.search_overlay is None:
            return

        percent = max(40, min(100, int(self.app_settings.get("search_overlay_opacity", self.app_settings.get("overlay_opacity", 100)))))
        alpha = max(110, min(255, round(255 * percent / 100)))
        light = self.app_settings.get("theme", "dark") == "light"

        palette = self._visual_theme_overlay_palette(light)

        def rgba(key):
            r, g, b = palette[key]
            return f"rgba({r}, {g}, {b}, {alpha})"

        def rgb(key):
            r, g, b = palette[key]
            return f"rgb({r}, {g}, {b})"

        dialog_bg = rgba("dialog")
        surface_bg = rgba("surface")
        button_bg = rgba("button")
        button_hover = rgba("button_hover")
        border = rgba("border")
        text_color = rgb("text")
        handle = rgba("handle")
        selected = rgb("selected")
        selected_text = rgb("selected_text")
        primary = rgb("primary")
        primary_border = rgb("primary_border")

        self.search_overlay.setStyleSheet(
            f"""
            QDialog#memoOverlayWindow {{
                background-color: {dialog_bg};
                border: 1px solid {border};
                border-radius: 10px;
                color: {text_color};
            }}
            QLabel {{
                background: transparent;
                color: {text_color};
            }}
            QLineEdit, QListWidget, QTextBrowser {{
                background-color: {surface_bg};
                border: 1px solid {border};
                border-radius: 7px;
                color: {text_color};
                padding: 8px;
                selection-background-color: {selected};
                selection-color: {selected_text};
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 5px;
            }}
            QListWidget::item:selected {{
                background-color: {selected};
                color: {selected_text};
            }}
            QPushButton {{
                background-color: {button_bg};
                border: 1px solid {border};
                border-radius: 7px;
                color: {text_color};
                padding: 8px 14px;
            }}
            QPushButton:hover {{
                background-color: {button_hover};
            }}
            QPushButton#primary {{
                background-color: {primary};
                border: 1px solid {primary_border};
                color: white;
            }}
            QSplitter::handle {{
                background-color: {handle};
            }}
            QScrollBar {{
                background: transparent;
            }}
            QScrollBar::handle {{
                background-color: {handle};
                border-radius: 4px;
            }}
            """
        )

    def show_search_overlay(self):
        if self.search_overlay is None:
            self.search_overlay = QDialog(None)
            self.search_overlay.setObjectName("memoOverlayWindow")
            self.search_overlay.setWindowTitle("DeiLaw — Быстрый поиск")
            self.search_overlay.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground, True
            )
            self.search_overlay.installEventFilter(self)

            flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            if self.app_settings.get("memo_always_on_top", True):
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.search_overlay.setWindowFlags(flags)
            self.search_overlay.setMinimumSize(760, 420)
            search_width, search_height = (
                self._quick_window_requested_size(760, 420)
            )
            self.search_overlay.resize(
                search_width,
                search_height,
            )

            layout = QVBoxLayout(self.search_overlay)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)

            top = QHBoxLayout()
            title = QLabel("🔎 Быстрый поиск")
            title.setObjectName("pageTitle")
            close = QPushButton("Скрыть")
            close.clicked.connect(self.search_overlay.hide)
            top.addWidget(title)
            top.addStretch()
            top.addWidget(close)
            layout.addLayout(top)

            search_row = QHBoxLayout()
            self.search_overlay_input = QLineEdit()
            self.search_overlay_input.setPlaceholderText(
                "Например: 9.8 КоАП, 63.1 УК РФ, 2.2 ПДД или текст..."
            )
            self.search_overlay_input.setClearButtonEnabled(True)
            search_button = QPushButton("Найти")
            search_button.setObjectName("primary")
            search_row.addWidget(self.search_overlay_input, stretch=1)
            search_row.addWidget(search_button)
            layout.addLayout(search_row)

            self.search_overlay_count = QLabel("Введите запрос")
            self.search_overlay_count.setObjectName("muted")
            layout.addWidget(self.search_overlay_count)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setChildrenCollapsible(False)
            splitter.setHandleWidth(7)

            self.search_overlay_list = QListWidget()
            self.search_overlay_list.setWordWrap(True)
            self.search_overlay_content = QTextBrowser()

            splitter.addWidget(self.search_overlay_list)
            splitter.addWidget(self.search_overlay_content)
            splitter.setSizes([380, 850])
            layout.addWidget(splitter, stretch=1)

            # F7 использует такие же живые подсказки поиска.
            self.search_overlay_suggestion_model = QStringListModel(self.search_overlay)
            self.search_overlay_completer = QCompleter(
                self.search_overlay_suggestion_model, self.search_overlay_input
            )
            self.search_overlay_completer.setCompletionMode(
                QCompleter.CompletionMode.PopupCompletion
            )
            self.search_overlay_completer.setCaseSensitivity(
                Qt.CaseSensitivity.CaseInsensitive
            )
            self.search_overlay_completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.search_overlay_completer.setMaxVisibleItems(10)
            self.search_overlay_input.setCompleter(self.search_overlay_completer)
            self.search_overlay_completer.activated[str].connect(
                self.on_overlay_search_suggestion_activated
            )

            self.search_overlay_input.textChanged.connect(
                self.update_overlay_search_suggestions
            )
            search_button.clicked.connect(self.run_overlay_search_now)
            self.search_overlay_input.returnPressed.connect(
                self.run_overlay_search_now
            )
            self.search_overlay_list.currentRowChanged.connect(
                self.show_overlay_search_result
            )

            geometry = self.app_settings.get("search_overlay_geometry", "")
            if geometry:
                try:
                    self.search_overlay.restoreGeometry(
                        QByteArray.fromBase64(geometry.encode("ascii"))
                    )
                except Exception:
                    pass

        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if self.app_settings.get("memo_always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.search_overlay.setWindowFlags(flags)
        self.apply_search_overlay_style()
        self.search_overlay.show()
        self.search_overlay.raise_()
        self.search_overlay.activateWindow()
        self.search_overlay_input.setFocus()
        self.search_overlay_input.selectAll()

    def update_overlay_search_suggestions(self, text):
        """Показывает варианты поиска в быстром поисковике F7."""
        query = (text or "").strip()

        if not query:
            self.search_overlay_suggestion_model.setStringList([])
            self.search_overlay_results = []
            self.search_overlay_list.clear()
            self.search_overlay_content.clear()
            self.search_overlay_count.setText("Введите запрос")
            return

        if len(query) < 2:
            self.search_overlay_suggestion_model.setStringList([])
            self.search_overlay_count.setText("Продолжайте ввод — появятся варианты поиска…")
            return

        suggestions = self.smart_text_search.suggest(
            query, limit=10, history=self.search_history
        )
        self.search_overlay_suggestion_model.setStringList(suggestions)
        self.search_overlay_count.setText(
            f"Умные подсказки • вариантов: {len(suggestions)} • выберите вариант или нажмите Enter"
        )

        completer = getattr(self, "search_overlay_completer", None)
        if completer is not None and suggestions:
            completer.setCompletionPrefix("")
            completer.complete()

    def on_overlay_search_suggestion_activated(self, suggestion):
        """Запускает поиск по выбранной подсказке в F7."""
        if not suggestion:
            return
        self.search_overlay_input.setText(suggestion)
        self.search_overlay_input.setCursorPosition(len(suggestion))
        self.perform_overlay_search()

    def run_overlay_search_now(self):
        """Run the overlay search from Enter or the Search button."""
        self.perform_overlay_search()

    def perform_overlay_search(self):
        query = self.search_overlay_input.text().strip()
        if not query:
            self.search_overlay_results = []
            self.search_overlay_list.clear()
            self.search_overlay_content.clear()
            self.search_overlay_count.setText("Введите запрос")
            return

        self.add_search_history(query)
        smart_results = self._smart_article_search(query)
        if smart_results is not None:
            self.search_overlay_results = smart_results
            mode = "Точный поиск"
        else:
            self.search_overlay_results = list(
                self.smart_text_search.search(
                    query,
                    int(self.app_settings.get("search_limit", 100)),
                )
            )
            mode = "Умный поиск"

        self.search_overlay_list.clear()
        self.search_overlay_content.clear()
        self.search_overlay_count.setText(
            f"{mode} • Найдено: {len(self.search_overlay_results)}"
        )

        for result in self.search_overlay_results:
            title = result["article_title"] or ""
            item_text = (
                f"Статья {result['article_number']}\n"
                f"{result['law_title']}"
            )
            if title:
                item_text += f"\n{title}"
            self.search_overlay_list.addItem(item_text)

        if self.search_overlay_results:
            self.search_overlay_list.setCurrentRow(0)
        else:
            self.search_overlay_content.setPlainText(
                "Ничего не найдено. Проверьте номер статьи, кодекс или текст запроса."
            )

    def show_overlay_search_result(self, row):
        if row < 0 or row >= len(self.search_overlay_results):
            return

        result = self.search_overlay_results[row]
        heading = (
            f"{result['law_title']}\n\n"
            f"Статья {result['article_number']}"
        )
        if result["article_title"]:
            heading += "\n" + result["article_title"]

        self.search_overlay_content.setPlainText(
            heading + "\n\n" + (result["content"] or "")
        )

    def save_search_overlay_geometry(self):
        if self.search_overlay is None:
            return
        self.app_settings["search_overlay_geometry"] = (
            bytes(self.search_overlay.saveGeometry().toBase64()).decode("ascii")
        )
        self.save_app_settings()


    def closeEvent(self, event):
        self.save_last_ai_session()
        if (
            hasattr(self, "pages")
            and self.pages.currentIndex() == self.settings_page_index
            and not self.confirm_settings_leave()
        ):
            event.ignore()
            return

        self.save_memo_layout_state()
        self.save_overlay_layout_state()
        self.save_search_overlay_geometry()
        self.save_calculator_overlay_geometry()
        self.unregister_global_hotkey()
        self.unregister_search_global_hotkey()
        self.unregister_calculator_global_hotkey()
        self.unregister_ahk_runtime_hotkeys()
        super().closeEvent(event)

    def apply_overlay_background_opacity(self):
        """Apply opacity and the active dark/light theme to Quick Memo."""
        if self.memo_overlay is None:
            return

        try:
            percent = int(self.app_settings.get("memo_overlay_opacity", self.app_settings.get("overlay_opacity", 100)))
        except (TypeError, ValueError):
            percent = 100
        percent = max(40, min(100, percent))
        alpha = round(255 * percent / 100)
        light = self.app_settings.get("theme", "dark") == "light"

        palette = self._visual_theme_overlay_palette(light)

        def rgba(key):
            r, g, b = palette[key]
            return f"rgba({r}, {g}, {b}, {alpha})"

        def rgb(key):
            r, g, b = palette[key]
            return f"rgb({r}, {g}, {b})"

        dialog_bg = rgba("dialog")
        frame_bg = rgba("surface")
        card_bg = rgba("surface")
        button_bg = rgba("button")
        border = rgba("border")
        text_color = rgb("text")
        handle = rgba("handle")

        self.memo_overlay.setWindowOpacity(1.0)
        self.memo_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self.memo_overlay.setAutoFillBackground(False)

        for child in self.memo_overlay.findChildren(QWidget):
            child.setAutoFillBackground(False)

            if isinstance(child, QLabel):
                if child.objectName() != "memoOverlayArticleCard":
                    child.setStyleSheet(
                        f"background: transparent; color: {text_color};"
                    )
            elif isinstance(child, (QScrollArea, QAbstractScrollArea)):
                child.setStyleSheet("background: transparent; border: none;")
                if child.viewport() is not None:
                    child.viewport().setAutoFillBackground(False)
                    child.viewport().setStyleSheet("background: transparent;")
            elif isinstance(child, QSplitter):
                child.setStyleSheet(
                    f"""
                    QSplitter {{ background: transparent; }}
                    QSplitter::handle {{ background: {handle}; }}
                    """
                )
            elif isinstance(child, QFrame):
                child.setStyleSheet(
                    f"""
                    background-color: {frame_bg};
                    border: 1px solid {border};
                    border-radius: 8px;
                    """
                )
            elif not isinstance(child, (QPushButton, QToolButton)):
                child.setStyleSheet("background: transparent;")

        self.memo_overlay.setStyleSheet(
            f"""
            QDialog#memoOverlayWindow {{
                background-color: {dialog_bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}

            QLabel#memoOverlayArticleCard {{
                background-color: {card_bg};
                border: 1px solid {border};
                border-radius: 7px;
                padding: 10px;
                color: {text_color};
            }}

            QDialog#memoOverlayWindow QPushButton,
            QDialog#memoOverlayWindow QToolButton {{
                background-color: {button_bg};
                border: 1px solid {border};
                color: {text_color};
            }}

            QDialog#memoOverlayWindow QScrollBar {{ background: transparent; }}
            QDialog#memoOverlayWindow QScrollBar::handle {{
                background-color: {handle};
                border-radius: 4px;
            }}
            """
        )

        for card in self.memo_overlay.findChildren(QLabel, "memoOverlayArticleCard"):
            card.setStyleSheet(
                f"""
                background-color: {card_bg};
                border: 1px solid {border};
                border-radius: 7px;
                padding: 10px;
                color: {text_color};
                """
            )

        self.memo_overlay.update()

    def apply_overlay_click_through(self):
        """Make the hotkey memo overlay mouse-click-through on Windows."""
        if self.memo_overlay is None:
            return

        enabled = bool(
            self.app_settings.get("overlay_click_through", False)
        )

        # Qt flag keeps the overlay from accepting mouse input.
        self.memo_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            enabled,
        )

        if sys.platform != "win32":
            return

        try:
            hwnd = int(self.memo_overlay.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000

            get_style = ctypes.windll.user32.GetWindowLongW
            set_style = ctypes.windll.user32.SetWindowLongW

            style = get_style(hwnd, GWL_EXSTYLE)
            if enabled:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                style &= ~WS_EX_TRANSPARENT
            set_style(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _quick_window_requested_size(
        self,
        minimum_width,
        minimum_height,
    ):
        """Return configured quick-window size clamped to the active monitor."""
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()

        requested_width = int(
            self.app_settings.get("overlay_width", 1250)
        )
        requested_height = int(
            self.app_settings.get("overlay_height", 650)
        )

        if screen is None:
            return (
                max(minimum_width, requested_width),
                max(minimum_height, requested_height),
            )

        area = screen.availableGeometry()
        return (
            min(
                max(minimum_width, requested_width),
                max(minimum_width, area.width() - 40),
            ),
            min(
                max(minimum_height, requested_height),
                max(minimum_height, area.height() - 40),
            ),
        )

    def apply_quick_window_size_settings(self):
        """Apply Settings -> 'Окно по бинду' to F7, F8 and F9 immediately."""
        memo_size = self._quick_window_requested_size(760, 420)
        search_size = self._quick_window_requested_size(760, 420)
        calculator_size = self._quick_window_requested_size(840, 500)

        if self.memo_overlay is not None:
            self.memo_overlay.resize(*memo_size)
            self.position_memo_overlay_from_settings()
            self.update_overlay_card_widths()

        if self.search_overlay is not None:
            self.search_overlay.resize(*search_size)

        if self.calculator_overlay is not None:
            self.calculator_overlay.resize(*calculator_size)

    def apply_overlay_window_settings(self):
        if self.memo_overlay is None:
            return
        visible = self.memo_overlay.isVisible()
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )
        if self.app_settings.get("memo_always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.memo_overlay.setWindowFlags(flags)
        self.memo_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self.memo_overlay.setWindowOpacity(1.0)
        self.apply_overlay_background_opacity()
        self.apply_overlay_click_through()
        if not self.app_settings.get("remember_memo_layout", True):
            self.position_memo_overlay_from_settings()
        if visible:
            self.memo_overlay.show()
            self.build_memo_overlay()

    def create_placeholder_page(self):

        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            40, 40, 40, 40
        )

        self.placeholder_title = QLabel()

        self.placeholder_title.setObjectName(
            "pageTitle"
        )

        self.placeholder_text = QLabel()

        self.placeholder_text.setObjectName(
            "muted"
        )

        layout.addWidget(
            self.placeholder_title
        )

        layout.addWidget(
            self.placeholder_text
        )

        layout.addStretch()

        return page

    def show_placeholder(
        self,
        title,
        text
    ):

        self.placeholder_title.setText(
            title
        )

        self.placeholder_text.setText(
            text
        )

        self.switch_page(self.settings_page_index)

    # =========================================================
    # RP ASSISTANT / DEILAW AI CHAT
    # =========================================================

    @staticmethod
    def _rp_training_explanation_html():
        return """
        <h2>DeiLaw AI — БЕТА</h2>
        <p><b>Как теперь работает AI:</b> DeiLaw сначала локально подбирает подходящие нормы
        из вашей базы законодательства RMRP. На сервер отправляются только текст текущей
        RP-ситуации, короткая история диалога и несколько найденных норм.</p>

        <p>Сам AI работает в облаке через защищённую Supabase Edge Function. Ключ OpenAI
        хранится только на сервере и отсутствует в DeiLaw.exe.</p>

        <h3>Что остаётся локально</h3>
        <ul>
          <li>база законодательства и обычный поиск;</li>
          <li>подбор источников для ответа;</li>
          <li>проверка того, что AI сослался только на реально переданные статьи;</li>
          <li>памятка, калькулятор и быстрые окна.</li>
        </ul>

        <h3>Что требует интернет</h3>
        <p>Только генерация ответа DeiLaw AI. Если интернет или облачный сервис временно
        недоступен, обычный поиск законодательства продолжает работать.</p>

        <p><b>Важно:</b> функция остаётся в БЕТА. Всегда проверяйте блок
        <b>«Источники ответа»</b> перед использованием вывода в RP.</p>
        """

    def show_rp_beta_warning(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("DeiLaw AI — БЕТА")
        dialog.setModal(True)
        dialog.resize(700, 520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("⚠  DeiLaw AI пока находится в БЕТА")
        title.setObjectName("pageTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        info = QTextBrowser()
        info.setOpenExternalLinks(False)
        info.setHtml(self._rp_training_explanation_html())
        layout.addWidget(info, stretch=1)

        dont_repeat = QCheckBox("Не показывать это предупреждение снова до перезапуска программы")
        layout.addWidget(dont_repeat)

        buttons = QHBoxLayout()
        cancel_button = QPushButton("Назад")
        open_button = QPushButton("Открыть DeiLaw AI")
        open_button.setObjectName("primary")
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(open_button)
        layout.addLayout(buttons)
        cancel_button.clicked.connect(dialog.reject)
        open_button.clicked.connect(dialog.accept)

        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted and dont_repeat.isChecked():
            self.rp_beta_warning_suppressed = True
        return accepted

    def show_rp_training_info(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Как работает DeiLaw AI")
        dialog.setModal(True)
        dialog.resize(700, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        title = QLabel("☁  Как работает DeiLaw Cloud AI")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        info = QTextBrowser()
        info.setOpenExternalLinks(False)
        info.setHtml(self._rp_training_explanation_html())
        layout.addWidget(info, stretch=1)
        close_button = QPushButton("Понятно")
        close_button.setObjectName("primary")
        close_button.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_button)
        layout.addLayout(row)
        dialog.exec()

    def load_last_ai_session(self):
        self.ai_session_draft = ""
        try:
            if not self.ai_session_path.is_file():
                return
            payload = json.loads(self.ai_session_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            messages = payload.get("messages")
            if isinstance(messages, list):
                cleaned = []
                for item in messages[-30:]:
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("role") or "").strip()
                    content = str(item.get("content") or "").strip()
                    if role in ("user", "assistant") and content:
                        cleaned.append({"role": role, "content": content[:20000]})
                self.ai_chat_messages = cleaned
            self.current_ai_situation = str(payload.get("current_situation") or "")[:10000]
            self.ai_session_draft = str(payload.get("draft") or "")[:10000]
        except Exception:
            self.ai_chat_messages = []
            self.current_ai_situation = ""
            self.ai_session_draft = ""

    def save_last_ai_session(self):
        try:
            draft = self.ai_session_draft
            if hasattr(self, "rp_input"):
                draft = self.rp_input.toPlainText()
            payload = {
                "version": 1,
                "saved_at": int(time.time()),
                "draft": str(draft or "")[:10000],
                "current_situation": str(self.current_ai_situation or "")[:10000],
                "messages": list(self.ai_chat_messages)[-30:],
            }
            self.ai_session_path.parent.mkdir(parents=True, exist_ok=True)
            self.ai_session_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def schedule_ai_session_save(self):
        if hasattr(self, "rp_input"):
            self.ai_session_draft = self.rp_input.toPlainText()
        if self.ai_session_save_timer is not None:
            self.ai_session_save_timer.start()

    def clear_last_ai_session(self):
        try:
            self.ai_session_save_timer.stop()
        except Exception:
            pass
        self.ai_session_draft = ""
        try:
            self.ai_session_path.unlink(missing_ok=True)
        except Exception:
            pass

    def create_assistant_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("DeiLaw AI — БЕТА")
        title.setObjectName("pageTitle")
        description = QLabel(
            "Cloud AI: DeiLaw локально подбирает нормы RMRP и отправляет только необходимые источники "
            "в защищённый облачный AI. Ollama и локальные модели больше не требуются."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(description)
        header.addLayout(title_box, stretch=1)

        self.rp_training_info_button = QPushButton("ℹ  Как работает")
        self.rp_training_info_button.clicked.connect(self.show_rp_training_info)
        header.addWidget(self.rp_training_info_button, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        beta_notice = QFrame()
        beta_notice.setObjectName("card")
        beta_notice_layout = QHBoxLayout(beta_notice)
        beta_notice_layout.setContentsMargins(14, 11, 14, 11)
        beta_notice_layout.setSpacing(12)
        beta_text = QLabel(
            "⚠ <b>БЕТА:</b> AI может ошибаться. Проверяйте найденные статьи и полный текст источников справа."
        )
        beta_text.setWordWrap(True)
        beta_notice_layout.addWidget(beta_text, stretch=1)
        layout.addWidget(beta_notice)

        self.ai_runtime_card = QFrame()
        self.ai_runtime_card.setObjectName("card")
        ai_runtime_layout = QHBoxLayout(self.ai_runtime_card)
        ai_runtime_layout.setContentsMargins(14, 10, 14, 10)
        ai_runtime_layout.setSpacing(10)
        ai_runtime_text = QVBoxLayout()
        ai_runtime_title = QLabel("Cloud AI")
        ai_runtime_title.setObjectName("sectionTitle")
        self.ai_runtime_status_label = QLabel("Проверяю соединение с DeiLaw Cloud AI…")
        self.ai_runtime_status_label.setObjectName("muted")
        self.ai_runtime_status_label.setWordWrap(True)
        ai_runtime_text.addWidget(ai_runtime_title)
        ai_runtime_text.addWidget(self.ai_runtime_status_label)
        ai_runtime_layout.addLayout(ai_runtime_text, stretch=1)
        self.ai_runtime_check_button = QPushButton("Проверить соединение")
        self.ai_runtime_check_button.clicked.connect(
            lambda checked=False: self.check_cloud_ai(manual=True)
        )
        ai_runtime_layout.addWidget(self.ai_runtime_check_button)
        layout.addWidget(self.ai_runtime_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        chat_panel = QFrame()
        chat_panel.setObjectName("card")
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        self.ai_chat_scroll = QScrollArea()
        self.ai_chat_scroll.setWidgetResizable(True)
        self.ai_chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.ai_chat_scroll.setObjectName("aiChatScroll")
        self.ai_chat_container = QWidget()
        self.ai_chat_container.setObjectName("aiChatContainer")
        self.ai_chat_layout = QVBoxLayout(self.ai_chat_container)
        self.ai_chat_layout.setContentsMargins(18, 18, 18, 18)
        self.ai_chat_layout.setSpacing(12)
        self.ai_chat_layout.addStretch()
        self.ai_chat_scroll.setWidget(self.ai_chat_container)
        chat_layout.addWidget(self.ai_chat_scroll, stretch=1)

        source_panel = QFrame()
        source_panel.setObjectName("card")
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(14, 14, 14, 14)
        source_layout.setSpacing(10)
        source_title = QLabel("Источники ответа")
        source_title.setObjectName("sectionTitle")
        source_hint = QLabel(
            "Эти нормы DeiLaw нашёл локально и передал Cloud AI для текущего ответа."
        )
        source_hint.setObjectName("muted")
        source_hint.setWordWrap(True)
        self.rp_results_list = QListWidget()
        self.rp_result_content = QTextBrowser()
        self.rp_result_content.setPlaceholderText("Выберите источник, чтобы увидеть полный текст нормы.")
        source_layout.addWidget(source_title)
        source_layout.addWidget(source_hint)
        source_layout.addWidget(self.rp_results_list, stretch=2)
        source_layout.addWidget(self.rp_result_content, stretch=3)

        splitter.addWidget(chat_panel)
        splitter.addWidget(source_panel)
        splitter.setSizes([860, 420])
        layout.addWidget(splitter, stretch=1)

        self.rp_status = QLabel("DeiLaw AI готов • Cloud AI • локальные источники RMRP")
        self.rp_status.setObjectName("muted")
        self.rp_status.setWordWrap(True)
        layout.addWidget(self.rp_status)

        composer = QFrame()
        composer.setObjectName("card")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(12, 10, 12, 10)
        composer_layout.setSpacing(8)
        self.rp_input = QTextEdit()
        self.rp_input.setPlaceholderText(
            "Напишите ситуацию или продолжите диалог…\n"
            "Например: водитель не остановился по требованию сотрудника ДПС\n"
            "Enter — отправить • Shift+Enter — новая строка"
        )
        self.rp_input.setFixedHeight(92)
        if self.ai_session_draft:
            self.rp_input.setPlainText(self.ai_session_draft)
        self.rp_input.installEventFilter(self)
        self.rp_input.textChanged.connect(self.schedule_ai_session_save)
        composer_layout.addWidget(self.rp_input)

        controls = QHBoxLayout()
        self.rp_clear_button = QPushButton("＋  Новый чат")
        self.rp_analyze_button = QPushButton("➤  Отправить")
        self.rp_analyze_button.setObjectName("primary")
        controls.addWidget(self.rp_clear_button)
        controls.addStretch()
        controls.addWidget(self.rp_analyze_button)
        composer_layout.addLayout(controls)
        layout.addWidget(composer)

        self.rp_analyze_button.clicked.connect(self.analyze_rp_with_ai)
        self.rp_clear_button.clicked.connect(self.clear_rp_assistant)
        self.rp_results_list.currentRowChanged.connect(self.show_rp_result)
        self.rebuild_ai_chat()
        QTimer.singleShot(700, lambda: self.check_cloud_ai(manual=False))
        return page

    def _update_cloud_ai_ui(self, status):
        status = dict(status or {})
        ok = bool(status.get("ok"))
        if ok:
            model = str(status.get("model") or "OpenAI")
            text = f"✅ Cloud AI онлайн • модель сервера: {model}"
        else:
            text = "⚠ " + str(status.get("error") or "Cloud AI временно недоступен.")
        if hasattr(self, "ai_runtime_status_label"):
            self.ai_runtime_status_label.setText(text)
        return ok

    def check_cloud_ai(self, manual=True):
        if hasattr(self, "ai_runtime_check_button"):
            self.ai_runtime_check_button.setEnabled(False)
        if hasattr(self, "ai_runtime_status_label"):
            self.ai_runtime_status_label.setText("Проверяю соединение с DeiLaw Cloud AI…")

        worker = CommunityTaskWorker(CloudAIClient().health, parent=self)
        self.cloud_ai_check_worker = worker

        def completed(status):
            if hasattr(self, "ai_runtime_check_button"):
                self.ai_runtime_check_button.setEnabled(True)
            ok = self._update_cloud_ai_ui(status)
            if manual and not ok:
                QMessageBox.warning(
                    self,
                    "DeiLaw Cloud AI",
                    str(status.get("error") or "Cloud AI временно недоступен."),
                )

        def failed(message):
            if hasattr(self, "ai_runtime_check_button"):
                self.ai_runtime_check_button.setEnabled(True)
            self._update_cloud_ai_ui({"ok": False, "error": message})

        worker.completed.connect(completed)
        worker.failed.connect(failed)
        worker.finished.connect(lambda: setattr(self, "cloud_ai_check_worker", None))
        worker.start()

    def _chat_palette(self, role):
        light = self.app_settings.get("theme", "dark") == "light"
        palette = self._visual_theme_overlay_palette(light)

        def hex_color(key):
            r, g, b = palette[key]
            return f"#{r:02x}{g:02x}{b:02x}"

        if role == "user":
            return hex_color("primary"), "#ffffff", hex_color("primary_border")
        return hex_color("surface"), hex_color("text"), hex_color("border")

    def _add_chat_bubble(self, role, text):
        if not hasattr(self, "ai_chat_layout"):
            return
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        bubble = QFrame()
        bubble.setMaximumWidth(820)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(14, 11, 14, 10)
        bubble_layout.setSpacing(7)
        author = QLabel("Вы" if role == "user" else "DeiLaw AI")
        author.setStyleSheet("font-weight: 700; background: transparent; border: none;")
        body = QLabel(str(text or ""))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet("background: transparent; border: none;")
        bubble_layout.addWidget(author)
        bubble_layout.addWidget(body)
        bg, fg, border = self._chat_palette(role)
        bubble.setStyleSheet(
            f"QFrame {{ background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 12px; }}"
        )
        if role == "user":
            row.addStretch()
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch()
        self.ai_chat_layout.insertWidget(max(0, self.ai_chat_layout.count() - 1), wrapper)

    def _clear_chat_widgets(self):
        if not hasattr(self, "ai_chat_layout"):
            return
        while self.ai_chat_layout.count():
            item = self.ai_chat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.ai_chat_layout.addStretch()

    def rebuild_ai_chat(self):
        self._clear_chat_widgets()
        if not self.ai_chat_messages:
            self._add_chat_bubble(
                "assistant",
                "Опишите RP-ситуацию. DeiLaw локально найдёт подходящие нормы RMRP, "
                "а Cloud AI разберёт их и сформирует ответ.",
            )
        else:
            for message in self.ai_chat_messages:
                self._add_chat_bubble(message.get("role", "assistant"), message.get("content", ""))
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _scroll_chat_to_bottom(self):
        if hasattr(self, "ai_chat_scroll"):
            bar = self.ai_chat_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _refresh_learning_status(self):
        # Compatibility hook for older UI code. Local model training was removed
        # in Cloud AI and there is nothing to refresh here.
        return

    def analyze_rp_situation(self):
        situation = self.rp_input.toPlainText().strip()
        if not situation:
            self.rp_status.setText("Сначала опишите RP-ситуацию.")
            return
        self.rp_results = self.rp_assistant.analyze(situation, limit=25)
        for row in self.rp_results:
            row.setdefault("result_type", "support")
        self._populate_ai_sources(self.rp_results)
        if not self.rp_results:
            self.rp_status.setText("Локальный поиск: подходящих норм не найдено.")
            return
        self.rp_status.setText(f"Локальный поиск: найдено кандидатов — {len(self.rp_results)}")
        self.rp_results_list.setCurrentRow(0)

    def _get_all_articles_for_ai(self):
        return self.rp_assistant.get_all_articles()

    def analyze_rp_with_ai(self):
        situation = self.rp_input.toPlainText().strip()
        if not situation:
            self.rp_status.setText("Сначала опишите RP-ситуацию.")
            return
        if self.ai_worker is not None and self.ai_worker.isRunning():
            return

        history = list(self.ai_chat_messages)[-6:]
        articles = self._get_all_articles_for_ai()
        self.current_ai_situation = situation
        self.rp_input.clear()
        self.ai_chat_messages.append({"role": "user", "content": situation})
        self.ai_session_draft = ""
        self.save_last_ai_session()
        self.rebuild_ai_chat()

        self.rp_analyze_button.setEnabled(False)
        self.rp_status.setText("DeiLaw локально подбирает источники…")

        self.ai_worker = AIWorker(
            situation,
            articles,
            history=history,
            parent=self,
        )
        self.ai_worker.status.connect(self.rp_status.setText)
        self.ai_worker.completed.connect(self.on_ai_completed)
        self.ai_worker.error.connect(self.on_ai_error)
        self.ai_worker.start()

    def on_ai_completed(self, answer, candidates):
        self.play_ui_sound("ai_complete")
        self.current_ai_candidates = list(candidates or [])
        self.rp_results = self.current_ai_candidates
        self.ai_chat_messages.append({"role": "assistant", "content": answer})
        self.save_last_ai_session()
        self.rebuild_ai_chat()
        self._populate_ai_sources(self.current_ai_candidates)
        if self.rp_results:
            self.rp_results_list.setCurrentRow(0)
        self.rp_status.setText(
            f"Cloud AI ответил • источников: {len(self.current_ai_candidates)}"
        )
        self.rp_analyze_button.setEnabled(True)

    def on_ai_error(self, message):
        logging.error("DeiLaw Cloud AI worker failed: %s", message)
        text = str(message or "Cloud AI временно недоступен.")
        self.ai_chat_messages.append({
            "role": "assistant",
            "content": "Не удалось получить ответ DeiLaw AI.\n\n" + text,
        })
        self.save_last_ai_session()
        self.rebuild_ai_chat()
        self.rp_status.setText("Cloud AI временно недоступен")
        self.rp_analyze_button.setEnabled(True)

    def _populate_ai_sources(self, candidates):
        self.rp_results_list.clear()
        for row in list(candidates or []):
            kind = "⚖ КВАЛИФИКАЦИЯ" if row.get("result_type") == "qualification" else "↳ СВЯЗАННАЯ НОРМА"
            self.rp_results_list.addItem(
                f"{kind}\nСтатья {row.get('article_number', '')}\n"
                f"{row.get('law_title', '')}\nРелевантность: {float(row.get('score') or 0):.1f}"
            )

    def show_rp_result(self, row):
        if row < 0 or row >= len(self.rp_results):
            return
        item = self.rp_results[row]
        title = f"{item.get('law_title', '')}\n\nСтатья {item.get('article_number', '')}"
        if item.get("article_title"):
            title += "\n" + str(item.get("article_title"))
        matches = ", ".join(item.get("matched_terms", []) or [])
        extra = f"\n\nПочему найдено локальным поиском:\nСовпадения: {matches}." if matches else ""
        self.rp_result_content.setPlainText(
            title + extra + "\n\n" + str(item.get("content") or "")
        )

    def rate_ai_message(self, index, positive):
        # Compatibility stub: local model training/feedback was removed in v0.3.0.
        return

    def clear_rp_assistant(self):
        if self.ai_worker is not None and self.ai_worker.isRunning():
            self.rp_status.setText("Дождитесь завершения текущего ответа DeiLaw AI.")
            return
        self.rp_input.clear()
        self.rp_results = []
        self.rp_results_list.clear()
        self.rp_result_content.clear()
        self.ai_chat_messages = []
        self.current_ai_situation = ""
        self.current_ai_candidates = []
        self.clear_last_ai_session()
        self.rp_status.setText("Новый чат • DeiLaw Cloud AI готов")
        self.rebuild_ai_chat()

    def ensure_ai_knowledge(self):
        # Local AI knowledge generation was removed. Kept for compatibility with
        # older startup code that may still call this method.
        return

    def rebuild_ai_knowledge(self):
        self.rp_status.setText("Cloud AI использует актуальные нормы из локальной базы DeiLaw.")

    def export_ai_bundle(self):
        QMessageBox.information(
            self,
            "DeiLaw Cloud AI",
            "AI Bundle больше не используется: локальная модель удалена из DeiLaw.",
        )

    def import_ai_bundle(self):
        QMessageBox.information(
            self,
            "DeiLaw Cloud AI",
            "Импорт локальной AI-модели больше не требуется.",
        )

    # =========================================================
    # QUICK MEMO v0.7
    # =========================================================

    @staticmethod
    def default_memo_columns():
        return [
            {"name": "ГИБДД", "sections": [{"name": "ГИБДД", "articles": []}]},
            {"name": "КоАП / УК", "sections": [
                {"name": "КоАП", "articles": []},
                {"name": "УК", "articles": []},
            ]},
            {"name": "Действия сотрудника", "sections": [{"name": "Процедуры", "articles": []}]},
        ]

    def load_memo_config(self):
        default = self.default_memo_columns()
        try:
            if self.memo_path.exists():
                data = json.loads(self.memo_path.read_text(encoding="utf-8"))
                columns = data.get("columns")
                if isinstance(columns, list) and columns:
                    cleaned = []
                    for column in columns:
                        sections = column.get("sections")
                        if not isinstance(sections, list) or not sections:
                            sections = [{
                                "name": str(column.get("name") or "Раздел"),
                                "articles": list(column.get("articles") or []),
                            }]
                        cleaned.append({
                            "name": str(column.get("name") or "Новый столбец"),
                            "sections": sections,
                        })
                    return cleaned
        except Exception:
            pass
        return default

    def save_memo_config(self):
        self.memo_path.parent.mkdir(parents=True, exist_ok=True)
        self.memo_path.write_text(
            json.dumps({"columns": self.memo_columns}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if hasattr(self, "profile_store"):
            self.profile_store.save_runtime(
                memo_columns=self.memo_columns,
                calculator_entries=getattr(self, "penalty_calc_entries", None),
                name=getattr(self, "active_profile", None),
            )

    @staticmethod
    def memo_law_short_name(law_title):
        name = law_title.lower().replace("ё", "е")
        if "административных правонарушениях" in name:
            return "КоАП"
        if "уголовно-процессуальный" in name:
            return "УПК"
        if "уголовный кодекс" in name:
            return "УК РФ"
        if "процессуальный кодекс" in name:
            return "ПК"
        if "правила дорожного движения" in name:
            return "ПДД"
        if "трудовой кодекс" in name:
            return "ТК"
        if "бюджетный кодекс" in name:
            return "БК"
        if "избирательный кодекс" in name:
            return "ИК"
        if "конституция" in name:
            return "КРФ"
        match = re.search(r"№\s*[\d-]+(?:-ФКЗ|-ФЗ)?", law_title, re.I)
        return match.group(0) if match else law_title[:24]

    @staticmethod
    def extract_article_penalty(content):
        """Return the exact punishment clause from the stored article text.

        The previous implementation tried to reconstruct fines/terms from nearby
        numbers.  In RP law texts that can accidentally pick an article number,
        weapon quantity, paragraph number, etc.  This version prefers the source
        wording itself, so the amount / arrest term / prison term shown on the
        card is exactly what is written in the local law database.
        """
        raw = (content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not raw:
            return ""

        # Keep meaningful line boundaries: many RMRP laws put the sanction on a
        # separate line immediately after the offence description.
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
        lines = [line for line in lines if line]

        # Strong introductions are much safer than hunting for arbitrary numbers.
        intro_re = re.compile(
            r"(?:^|[.!?;:]\s*)"
            r"(наказывается|наказание\s*[:—–-]?|влеч[её]т|"
            r"мер[ау]\s+наказания\s*[:—–-]?|санкци[яи]\s*[:—–-]?)",
            re.I,
        )
        punishment_re = re.compile(
            r"штраф|арест|лишени\w*\s+свобод\w*|"
            r"ограничени\w*\s+свобод\w*|"
            r"лишени\w*\s+(?:права|прав)|"
            r"обязательн\w*\s+работ\w*|"
            r"исправительн\w*\s+работ\w*|"
            r"принудительн\w*\s+работ\w*",
            re.I,
        )
        detail_re = re.compile(
            r"\d|руб|₽|сут|дн(?:ей|я)?|час|месяц|год|лет|срок|до\s+|от\s+|"
            r"од(?:ин|ного|ному)|два|двух|три|трех|четыре|пять|шесть|семь|восемь|"
            r"девять|десять|пятнадцать|двадцать|тридцать|пожизн",
            re.I,
        )

        def clean_clause(value):
            value = re.sub(r"\s+", " ", value or "").strip(" \t,;.—–-")
            # Avoid duplicated UI prefix: the card already adds "Наказание:".
            value = re.sub(
                r"^(?:наказание|мера наказания|санкция)\s*[:—–-]?\s*",
                "",
                value,
                flags=re.I,
            )
            return value[:650].rstrip(" ,;—–-")

        candidates = []

        # 1) Prefer whole source lines containing a clear sanction introduction.
        for i, line in enumerate(lines):
            m = intro_re.search(line)
            if not m:
                continue

            piece = line[m.start():]
            # If the intro is only a heading ("Наказание:"), include following
            # lines because the actual amount/term is often written below it.
            joined = piece

            # RMRP frequently wraps one sanction across several source lines,
            # including the MIN and MAX of a fine range.  Do not stop merely
            # because the first number was found: collect the continuation of
            # the sanction and let the calculator parse it afterwards.
            for j in range(i + 1, min(len(lines), i + 9)):
                nxt = lines[j]

                # Stop only at a real next article/subarticle heading.
                if re.match(
                    r"^(?:статья\s+)?\d+(?:[.-]\d+)+(?:\.|\s)",
                    nxt,
                    re.I,
                ):
                    break

                joined += " " + nxt

                # Once we have a complete-looking sentence, we can stop.
                # If the current phrase still ends with a continuation marker
                # (от/до/или/либо/на срок/в размере), keep reading.
                compact = re.sub(r"\s+", " ", joined).strip()
                continuation = bool(
                    re.search(
                        r"(?:\bот|\bдо|\bили|\bлибо|"
                        r"на\s+срок|в\s+размере)\s*$",
                        compact,
                        re.I,
                    )
                )
                if (
                    punishment_re.search(compact)
                    and detail_re.search(compact)
                    and re.search(r"[.!?]\s*$", compact)
                    and not continuation
                ):
                    break

            clause = clean_clause(joined)
            if clause:
                candidates.append((0 if detail_re.search(clause) else 1, clause))

        # 2) If the text has no explicit "наказывается/влечет" marker, take the
        # exact sentence/line that contains a punishment, plus a neighbouring
        # line when the numeric term is separated from the punishment name.
        if not candidates:
            for i, line in enumerate(lines):
                pm = punishment_re.search(line)
                if not pm:
                    continue
                joined = line

                # Even when the first line already contains a number, the
                # sanction may continue with "до ..." on the next line.
                if i > 0 and not detail_re.search(joined) and detail_re.search(lines[i - 1]):
                    joined = lines[i - 1] + " " + joined

                for j in range(i + 1, min(len(lines), i + 9)):
                    nxt = lines[j]
                    if re.match(
                        r"^(?:статья\s+)?\d+(?:[.-]\d+)+(?:\.|\s)",
                        nxt,
                        re.I,
                    ):
                        break

                    joined += " " + nxt
                    compact = re.sub(r"\s+", " ", joined).strip()

                    continuation = bool(
                        re.search(
                            r"(?:\bот|\bдо|\bили|\bлибо|"
                            r"на\s+срок|в\s+размере)\s*$",
                            compact,
                            re.I,
                        )
                    )
                    if (
                        detail_re.search(compact)
                        and re.search(r"[.!?]\s*$", compact)
                        and not continuation
                    ):
                        break

                clause = clean_clause(joined)
                if clause:
                    candidates.append((0 if detail_re.search(clause) else 1, clause))

        # 3) Single-line documents: sentence/window fallback.  It still returns
        # the original wording rather than fabricating an amount from a number.
        if not candidates:
            one_line = re.sub(r"\s+", " ", raw).strip()
            for pm in punishment_re.finditer(one_line):
                left = max(0, pm.start() - 140)
                right = min(len(one_line), pm.end() + 420)
                frag = one_line[left:right]

                # Trim to nearest sentence-like boundaries when possible.
                before = max(frag.rfind(". ", 0, pm.start() - left),
                             frag.rfind("; ", 0, pm.start() - left))
                if before >= 0:
                    frag = frag[before + 2:]
                after_positions = [p for p in (frag.find(". ", 1), frag.find("; ", 1)) if p >= 0]
                if after_positions:
                    frag = frag[:min(after_positions) + 1]

                clause = clean_clause(frag)
                if clause:
                    candidates.append((0 if detail_re.search(clause) else 1, clause))

        if not candidates:
            return ""

        # Prefer a clause that actually contains an amount/term.  De-duplicate
        # while preserving the source order.
        candidates.sort(key=lambda item: item[0])
        unique = []
        seen = set()
        for _, clause in candidates:
            key = clause.lower().replace("ё", "е")
            if key in seen:
                continue
            seen.add(key)
            unique.append(clause)

        # Usually one clause contains every alternative (fine / arrest / prison).
        # If several compact clauses exist, show up to three without inventing data.
        return " / ".join(unique[:3])

    @staticmethod
    def memo_summary(article):
        title = re.sub(r"\s+", " ", (article.get("article_title") or "")).strip()
        content = re.sub(r"\s+", " ", article.get("content") or "").strip()

        def norm(value):
            value = value.lower().replace("ё", "е")
            value = re.sub(r"[^\w\s]", " ", value)
            return re.sub(r"\s+", " ", value).strip()

        # Prefer the parsed title if it exists.
        if title:
            # Also collapse accidental "X X" duplication inside the title itself.
            words = title.split()
            if len(words) >= 6 and len(words) % 2 == 0:
                half = len(words) // 2
                if norm(" ".join(words[:half])) == norm(" ".join(words[half:])):
                    title = " ".join(words[:half])
            return title.rstrip(" .")

        if not content:
            return "Без краткого описания"

        first = re.split(r"(?<=[.!?])\s+", content)[0].strip()

        # Collapse duplicated sentence/phrase: "текст текст".
        words = first.split()
        if len(words) >= 6 and len(words) % 2 == 0:
            half = len(words) // 2
            if norm(" ".join(words[:half])) == norm(" ".join(words[half:])):
                first = " ".join(words[:half])

        return first[:170] + ("..." if len(first) > 170 else "")

    def memo_card_description(self, article):
        """PDD cards show the complete rule text; other laws stay compact."""
        short = self.memo_law_short_name(self._memo_result_value(article, "law_title", ""))
        if short == "ПДД":
            content = (article.get("content") or "").strip()
            title = re.sub(r"\s+", " ", (article.get("article_title") or "")).strip()
            # Avoid repeating the title when the parser also left it as the first body line.
            if title and content:
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                if lines and lines[0].rstrip(" .") == title.rstrip(" ."):
                    content = "\n".join(lines[1:]).strip()
            if title and content:
                return f"{title}\n{content}"
            return content or title or "Без текста пункта"
        return self.memo_summary(article)

    # =========================================================
    # PENALTY CALCULATOR
    # =========================================================

    @staticmethod
    def _calc_number(value):
        """Parse RMRP money values such as 5 000, 5.000 or 5,000."""
        value = str(value or "").strip()
        if not value:
            return None

        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            return None

        try:
            return int(digits)
        except ValueError:
            return None

    @staticmethod
    def _calc_duration_days(value, unit):
        """Normalize a sanction duration to days for arithmetic display."""
        try:
            amount = int(value)
        except (TypeError, ValueError):
            return None

        normalized = str(unit or "").lower().replace("ё", "е")
        if normalized.startswith(("год", "лет")):
            return amount * 365
        if normalized.startswith("месяц"):
            return amount * 30
        if normalized.startswith(("дн", "сут")):
            return amount
        return None

    @staticmethod
    def _format_calc_money(value):
        if value is None:
            return "—"
        return f"{int(value):,}".replace(",", " ") + " ₽"

    @staticmethod
    def _format_calc_duration(days):
        if days is None:
            return "—"

        days = max(0, int(days))
        if days == 0:
            return "0 дней"

        years, rest = divmod(days, 365)
        months, rest = divmod(rest, 30)
        parts = []

        if years:
            if years % 10 == 1 and years % 100 != 11:
                word = "год"
            elif years % 10 in (2, 3, 4) and years % 100 not in (12, 13, 14):
                word = "года"
            else:
                word = "лет"
            parts.append(f"{years} {word}")

        if months:
            if months == 1:
                word = "месяц"
            elif months in (2, 3, 4):
                word = "месяца"
            else:
                word = "месяцев"
            parts.append(f"{months} {word}")

        if rest:
            if rest % 10 == 1 and rest % 100 != 11:
                word = "день"
            elif rest % 10 in (2, 3, 4) and rest % 100 not in (12, 13, 14):
                word = "дня"
            else:
                word = "дней"
            parts.append(f"{rest} {word}")

        return " ".join(parts)

    @staticmethod
    def _russian_number_word_value(value):
        """Parse the small Russian number-word forms used in RMRP sanctions.

        Supports forms such as:
        - "трех" -> 3
        - "пятидесяти тысяч" -> 50 000
        - "сто тысяч" -> 100 000

        The calculator still never guesses: this helper is only used when the
        source sanction explicitly contains number words.
        """
        value = str(value or "").lower().replace("ё", "е")
        value = value.replace("-", " ")
        words = re.findall(r"[а-я]+", value)
        if not words:
            return None

        units = {
            "ноль": 0,
            "один": 1, "одна": 1, "одно": 1, "одного": 1, "одной": 1,
            "два": 2, "две": 2, "двух": 2,
            "три": 3, "трех": 3, "трем": 3,
            "четыре": 4, "четырех": 4,
            "пять": 5, "пяти": 5,
            "шесть": 6, "шести": 6,
            "семь": 7, "семи": 7,
            "восемь": 8, "восьми": 8,
            "девять": 9, "девяти": 9,
        }
        teens = {
            "десять": 10, "десяти": 10,
            "одиннадцать": 11, "одиннадцати": 11,
            "двенадцать": 12, "двенадцати": 12,
            "тринадцать": 13, "тринадцати": 13,
            "четырнадцать": 14, "четырнадцати": 14,
            "пятнадцать": 15, "пятнадцати": 15,
            "шестнадцать": 16, "шестнадцати": 16,
            "семнадцать": 17, "семнадцати": 17,
            "восемнадцать": 18, "восемнадцати": 18,
            "девятнадцать": 19, "девятнадцати": 19,
        }
        tens = {
            "двадцать": 20, "двадцати": 20,
            "тридцать": 30, "тридцати": 30,
            "сорок": 40, "сорока": 40,
            "пятьдесят": 50, "пятидесяти": 50,
            "шестьдесят": 60, "шестидесяти": 60,
            "семьдесят": 70, "семидесяти": 70,
            "восемьдесят": 80, "восьмидесяти": 80,
            "девяносто": 90, "девяноста": 90,
        }
        hundreds = {
            "сто": 100, "ста": 100,
            "двести": 200, "двухсот": 200,
            "триста": 300, "трехсот": 300,
            "четыреста": 400, "четырехсот": 400,
            "пятьсот": 500, "пятисот": 500,
            "шестьсот": 600, "шестисот": 600,
            "семьсот": 700, "семисот": 700,
            "восемьсот": 800, "восьмисот": 800,
            "девятьсот": 900, "девятисот": 900,
        }
        thousand_words = {
            "тысяча", "тысячи", "тысяч", "тысячу", "тысячах", "тысячами"
        }
        million_words = {
            "миллион", "миллиона", "миллионов"
        }

        total = 0
        current = 0
        matched = False

        for word in words:
            if word in units:
                current += units[word]
                matched = True
            elif word in teens:
                current += teens[word]
                matched = True
            elif word in tens:
                current += tens[word]
                matched = True
            elif word in hundreds:
                current += hundreds[word]
                matched = True
            elif word in thousand_words:
                current = max(current, 1) * 1000
                total += current
                current = 0
                matched = True
            elif word in million_words:
                current = max(current, 1) * 1_000_000
                total += current
                current = 0
                matched = True

        if not matched:
            return None
        return total + current

    @classmethod
    def _calc_explicit_number(cls, value):
        """Parse either explicit digits or explicit Russian number words."""
        value = str(value or "").strip()
        if not value:
            return None

        digit_match = re.search(r"\d", value)
        if digit_match:
            return cls._calc_number(value)

        return cls._russian_number_word_value(value)

    @classmethod
    def _calc_duration_value_days(cls, value, unit):
        amount = cls._calc_explicit_number(value)
        if amount is None:
            return None
        return cls._calc_duration_days(amount, unit)

    @classmethod
    def _extract_money_amount_fragment(cls, fragment):
        """Extract one explicit monetary amount from a short sanction fragment.

        Handles digits, grouped digits and written-out Russian numbers. Numeric
        values in parentheses have priority, e.g. "(15.000)".
        """
        fragment = str(fragment or "").strip()
        if not fragment:
            return None

        parenthesized = re.search(
            r"\(\s*(\d(?:[\d\s.,]*\d)?)\s*\)",
            fragment,
            re.I,
        )
        if parenthesized:
            return cls._calc_number(parenthesized.group(1))

        digits = re.search(
            r"(?<!\d)(\d(?:[\d\s.,]*\d)?)(?!\d)",
            fragment,
            re.I,
        )
        if digits:
            return cls._calc_number(digits.group(1))

        words_only = re.sub(
            r"(?:₽|руб(?:ль|ля|лей|\.?)?)",
            " ",
            fragment,
            flags=re.I,
        )
        words_only = re.sub(r"[()\[\],.;:—–-]", " ", words_only)
        words_only = re.sub(r"\s+", " ", words_only).strip()
        return cls._russian_number_word_value(words_only)

    @classmethod
    def _parse_penalty_for_calculator(cls, content):
        """Extract fine / imprisonment values only from explicit source wording.

        Handles both numeric and common written-out RMRP forms, including:
        "пятидесяти тысяч (50.000) рублей" and "трех лет".
        """
        clause = cls.extract_article_penalty(content)
        if not clause:
            return {
                "clause": "",
                "fine_min": None,
                "fine_max": None,
                "prison_min_days": None,
                "prison_max_days": None,
                "arrest_min_days": None,
                "arrest_max_days": None,
                "alternative": False,
                "recognized": False,
            }

        normalized = re.sub(r"\s+", " ", clause.replace("\xa0", " ")).strip()
        lower = normalized.lower().replace("ё", "е")

        fine_min = fine_max = None
        prison_min = prison_max = None
        arrest_min = arrest_max = None

        # Detect explicit alternatives.  КоАП frequently uses:
        # "штраф ... либо административного ареста ...".
        alternative = bool(
            re.search(
                r"штраф\w*.*?\b(?:или|либо)\b.*?"
                r"(?:лишени\w*\s+свобод\w*|административн\w*\s+арест\w*)|"
                r"(?:лишени\w*\s+свобод\w*|административн\w*\s+арест\w*)"
                r".*?\b(?:или|либо)\b.*?штраф\w*",
                lower,
                re.I,
            )
        )

        # A reusable source-number expression. It accepts:
        #   50 000
        #   50.000
        #   (50.000)
        #   пятидесяти тысяч
        word_num = (
            r"(?:ноль|один|одна|одного|два|две|двух|три|трех|четыре|"
            r"четырех|пять|пяти|шесть|шести|семь|семи|восемь|восьми|"
            r"девять|девяти|десять|десяти|одиннадцать|одиннадцати|"
            r"двенадцать|двенадцати|тринадцать|тринадцати|четырнадцать|"
            r"четырнадцати|пятнадцать|пятнадцати|шестнадцать|"
            r"шестнадцати|семнадцать|семнадцати|восемнадцать|"
            r"восемнадцати|девятнадцать|девятнадцати|двадцать|двадцати|"
            r"тридцать|тридцати|сорок|сорока|пятьдесят|пятидесяти|"
            r"шестьдесят|шестидесяти|семьдесят|семидесяти|восемьдесят|"
            r"восьмидесяти|девяносто|девяноста|сто|ста|двести|двухсот|"
            r"триста|трехсот|четыреста|четырехсот|пятьсот|пятисот|"
            r"шестьсот|шестисот|семьсот|семисот|восемьсот|восьмисот|"
            r"девятьсот|девятисот|тысяча|тысячи|тысяч|миллион|"
            r"миллиона|миллионов)"
        )
        number_expr = rf"(?:\(?\d[\d\s.,]*\)?|{word_num}(?:\s+{word_num}){{0,4}})"

        # -------- Fine --------
        fine_match = re.search(r"штраф\w*", lower, re.I)
        if fine_match:
            left = max(0, fine_match.start() - 70)
            right = min(len(normalized), fine_match.end() + 520)
            fine_window = normalized[left:right]

            # Parse a RANGE BEFORE attempting one exact amount. Otherwise
            # "от 15 000 до 30 000 рублей" can be reduced to the last number.
            range_match = re.search(
                r"\bот\b\s+(.{1,110}?)\s+\bдо\b\s+(.{1,160})",
                fine_window,
                re.I,
            )
            if range_match:
                low_fragment = range_match.group(1)
                high_fragment = re.split(
                    r"\b(?:или|либо)\b|;",
                    range_match.group(2),
                    maxsplit=1,
                    flags=re.I,
                )[0]
                low_value = cls._extract_money_amount_fragment(low_fragment)
                high_value = cls._extract_money_amount_fragment(high_fragment)
                if (
                    low_value is not None
                    and high_value is not None
                    and low_value <= high_value
                ):
                    fine_min, fine_max = low_value, high_value

            # Common RMRP format: written amount + numeric amount in
            # parentheses on both sides of the range.
            if fine_min is None:
                paren_range = re.search(
                    r"\bот\b[^()]{0,100}\(\s*(\d(?:[\d\s.,]*\d)?)\s*\)"
                    r"\s+\bдо\b[^()]{0,100}\(\s*(\d(?:[\d\s.,]*\d)?)\s*\)"
                    r"\s*(?:₽|руб\w*)?",
                    fine_window,
                    re.I,
                )
                if paren_range:
                    low_value = cls._calc_number(paren_range.group(1))
                    high_value = cls._calc_number(paren_range.group(2))
                    if (
                        low_value is not None
                        and high_value is not None
                        and low_value <= high_value
                    ):
                        fine_min, fine_max = low_value, high_value

            # Compact range through hyphen/en-dash/em-dash.
            if fine_min is None:
                dash_range = re.search(
                    r"(\d(?:[\d\s.,]*\d)?)\s*[-—–]\s*"
                    r"(\d(?:[\d\s.,]*\d)?)"
                    r"(?:\s*(?:₽|руб\w*))?",
                    fine_window,
                    re.I,
                )
                if dash_range:
                    low_value = cls._calc_number(dash_range.group(1))
                    high_value = cls._calc_number(dash_range.group(2))
                    if (
                        low_value is not None
                        and high_value is not None
                        and low_value <= high_value
                    ):
                        fine_min, fine_max = low_value, high_value

            # Maximum-only wording.
            if fine_min is None:
                max_match = re.search(
                    r"(?:до|не\s+более)\s+(.{1,100})",
                    fine_window,
                    re.I,
                )
                if max_match:
                    max_fragment = re.split(
                        r"\b(?:или|либо)\b|;",
                        max_match.group(1),
                        maxsplit=1,
                        flags=re.I,
                    )[0]
                    value = cls._extract_money_amount_fragment(max_fragment)
                    if value is not None:
                        fine_min, fine_max = 0, value

            # Exact amount comes last.
            if fine_min is None:
                digit_rubles = re.search(
                    r"\(?\s*(\d(?:[\d\s.,]*\d)?)\s*\)?"
                    r"\s*(?:₽|руб\w*)",
                    fine_window,
                    re.I,
                )
                if digit_rubles:
                    value = cls._calc_number(digit_rubles.group(1))
                    fine_min = fine_max = value

            if fine_min is None:
                word_rubles = re.search(
                    r"([а-яё\s-]{2,90})\s*(?:₽|руб\w*)",
                    fine_window,
                    re.I,
                )
                if word_rubles:
                    value = cls._extract_money_amount_fragment(word_rubles.group(1))
                    if value is not None:
                        fine_min = fine_max = value

        # -------- Imprisonment --------
        prison_phrase = re.search(
            r"лишени\w*\s+свобод\w*",
            lower,
            re.I,
        )
        if prison_phrase:
            left = max(0, prison_phrase.start() - 100)
            right = min(len(normalized), prison_phrase.end() + 260)
            prison_window = normalized[left:right]

            unit = (
                r"(лет|года|год|месяцев|месяца|месяц|"
                r"дней|дня|день|суток|сутки|сут)"
            )

            # Range: "от двух до пяти лет" / "от 2 до 5 лет".
            range_match = re.search(
                rf"(?:лишени\w*\s+свобод\w*.*?)?"
                rf"\bот\s+({number_expr})\s+\bдо\s+({number_expr})\s*{unit}",
                prison_window,
                re.I,
            )
            if range_match:
                low_days = cls._calc_duration_value_days(
                    range_match.group(1),
                    range_match.group(3),
                )
                high_days = cls._calc_duration_value_days(
                    range_match.group(2),
                    range_match.group(3),
                )
                if low_days is not None and high_days is not None:
                    prison_min, prison_max = low_days, high_days

            # Maximum: "до трех лет".
            if prison_min is None:
                max_match = re.search(
                    rf"(?:лишени\w*\s+свобод\w*.*?)?"
                    rf"(?:до|не\s+более)\s+({number_expr})\s*{unit}",
                    prison_window,
                    re.I,
                )
                if max_match:
                    max_days = cls._calc_duration_value_days(
                        max_match.group(1),
                        max_match.group(2),
                    )
                    if max_days is not None:
                        prison_min, prison_max = 0, max_days

            # Exact: "на срок трех лет" / "на 3 года".
            if prison_min is None:
                exact_match = re.search(
                    rf"лишени\w*\s+свобод\w*"
                    rf".*?(?:на\s+срок\s+|сроком\s+|на\s+)?"
                    rf"({number_expr})\s*{unit}",
                    prison_window,
                    re.I,
                )
                if exact_match:
                    value = cls._calc_duration_value_days(
                        exact_match.group(1),
                        exact_match.group(2),
                    )
                    if value is not None:
                        prison_min = prison_max = value

        # -------- Administrative arrest --------
        arrest_phrase = re.search(
            r"административн\w*\s+арест\w*",
            lower,
            re.I,
        )
        if arrest_phrase:
            left = max(0, arrest_phrase.start() - 120)
            right = min(len(normalized), arrest_phrase.end() + 280)
            arrest_window = normalized[left:right]

            arrest_unit = (
                r"(суток|сутки|сут|дней|дня|день|"
                r"часов|часа|час|месяцев|месяца|месяц)"
            )

            # Range: "от пяти до пятнадцати суток".
            arrest_range = re.search(
                rf"(?:административн\w*\s+арест\w*.*?)?"
                rf"\bот\s+({number_expr})\s+\bдо\s+({number_expr})\s*"
                rf"{arrest_unit}",
                arrest_window,
                re.I,
            )
            if arrest_range:
                low_days = cls._calc_duration_value_days(
                    arrest_range.group(1),
                    arrest_range.group(3),
                )
                high_days = cls._calc_duration_value_days(
                    arrest_range.group(2),
                    arrest_range.group(3),
                )
                if low_days is not None and high_days is not None:
                    arrest_min, arrest_max = low_days, high_days

            # Maximum: "до пятнадцати суток".
            if arrest_min is None:
                arrest_max_match = re.search(
                    rf"(?:административн\w*\s+арест\w*.*?)?"
                    rf"(?:до|не\s+более)\s+({number_expr})\s*"
                    rf"{arrest_unit}",
                    arrest_window,
                    re.I,
                )
                if arrest_max_match:
                    max_days = cls._calc_duration_value_days(
                        arrest_max_match.group(1),
                        arrest_max_match.group(2),
                    )
                    if max_days is not None:
                        arrest_min, arrest_max = 0, max_days

            # Exact: "административного ареста на срок пятнадцати суток".
            if arrest_min is None:
                arrest_exact = re.search(
                    rf"административн\w*\s+арест\w*"
                    rf".*?(?:на\s+срок\s+|сроком\s+|на\s+)?"
                    rf"({number_expr})\s*{arrest_unit}",
                    arrest_window,
                    re.I,
                )
                if arrest_exact:
                    value = cls._calc_duration_value_days(
                        arrest_exact.group(1),
                        arrest_exact.group(2),
                    )
                    if value is not None:
                        arrest_min = arrest_max = value

        return {
            "clause": normalized,
            "fine_min": fine_min,
            "fine_max": fine_max,
            "prison_min_days": prison_min,
            "prison_max_days": prison_max,
            "arrest_min_days": arrest_min,
            "arrest_max_days": arrest_max,
            "alternative": alternative,
            "recognized": any(
                value is not None
                for value in (
                    fine_min,
                    fine_max,
                    prison_min,
                    prison_max,
                    arrest_min,
                    arrest_max,
                )
            ),
        }

    def create_penalty_calculator_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("Калькулятор наказаний")
        title.setObjectName("pageTitle")
        self.calc_open_overlay_button = QPushButton("↗ Открыть отдельно")
        self.calc_open_overlay_button.setObjectName("primary")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.calc_open_overlay_button)
        root.addLayout(title_row)

        description = QLabel(
            "Складывает штрафы и сроки лишения свободы по выбранным статьям. "
            "Значения берутся только из текста локальной базы законодательства."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        root.addWidget(description)

        warning = QLabel(
            "⚠ Если статья содержит альтернативу — например «штраф либо "
            "административный арест» или «штраф либо лишение свободы» — DeiLaw "
            "сначала попросит выбрать вид наказания. Для штрафа с диапазоном "
            "после этого нужно выбрать точную сумму. "
            "Если наказания разделены «или / либо», статья будет помечена как альтернативная: "
            "штраф и срок показаны как возможные варианты, а не как два одновременных наказания."
        )
        warning.setObjectName("muted")
        warning.setWordWrap(True)
        root.addWidget(warning)

        search_row = QHBoxLayout()
        self.calc_article_input = QLineEdit()
        self.calc_article_input.setPlaceholderText(
            "Статья или ситуация: 9.8 КоАП, 63.1 УК РФ, побег от ДПС..."
        )
        self.calc_add_button = QPushButton("+ Добавить")
        self.calc_add_button.setObjectName("primary")
        search_row.addWidget(self.calc_article_input, stretch=1)
        search_row.addWidget(self.calc_add_button)
        root.addLayout(search_row)

        self.calc_suggestion_model = QStringListModel(self)
        self.calc_completer = QCompleter(
            self.calc_suggestion_model,
            self.calc_article_input,
        )
        self.calc_completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.calc_completer.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self.calc_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.calc_completer.setMaxVisibleItems(10)
        self.calc_article_input.setCompleter(self.calc_completer)

        self.calc_suggestion_timer = QTimer(self)
        self.calc_suggestion_timer.setSingleShot(True)
        self.calc_suggestion_timer.setInterval(220)
        self.calc_suggestion_timer.timeout.connect(
            self.run_penalty_calculator_suggestions
        )

        summary = QHBoxLayout()

        fine_card = QFrame()
        fine_card.setObjectName("card")
        fine_layout = QVBoxLayout(fine_card)
        fine_title = QLabel("💰 Штрафы")
        fine_title.setObjectName("sectionTitle")
        self.calc_fine_total = QLabel("0 ₽")
        self.calc_fine_total.setObjectName("pageTitle")
        self.calc_fine_total.setWordWrap(True)
        fine_layout.addWidget(fine_title)
        fine_layout.addWidget(self.calc_fine_total)

        prison_card = QFrame()
        prison_card.setObjectName("card")
        prison_layout = QVBoxLayout(prison_card)
        prison_title = QLabel("⛓ Лишение свободы")
        prison_title.setObjectName("sectionTitle")
        self.calc_prison_total = QLabel("0 дней")
        self.calc_prison_total.setObjectName("pageTitle")
        self.calc_prison_total.setWordWrap(True)
        prison_layout.addWidget(prison_title)
        prison_layout.addWidget(self.calc_prison_total)

        count_card = QFrame()
        count_card.setObjectName("card")
        count_layout = QVBoxLayout(count_card)
        count_title = QLabel("📚 Выбрано")
        count_title.setObjectName("sectionTitle")
        self.calc_count_total = QLabel("0 статей")
        self.calc_count_total.setObjectName("pageTitle")
        count_layout.addWidget(count_title)
        count_layout.addWidget(self.calc_count_total)

        arrest_card = QFrame()
        arrest_card.setObjectName("card")
        arrest_layout = QVBoxLayout(arrest_card)
        arrest_title = QLabel("🚔 Административный арест")
        arrest_title.setObjectName("sectionTitle")
        self.calc_arrest_total = QLabel("0 дней")
        self.calc_arrest_total.setObjectName("pageTitle")
        self.calc_arrest_total.setWordWrap(True)
        arrest_layout.addWidget(arrest_title)
        arrest_layout.addWidget(self.calc_arrest_total)

        summary.addWidget(fine_card, stretch=1)
        summary.addWidget(prison_card, stretch=1)
        summary.addWidget(arrest_card, stretch=1)
        summary.addWidget(count_card, stretch=1)
        root.addLayout(summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        selected_title = QLabel("Выбранные статьи")
        selected_title.setObjectName("sectionTitle")
        self.calc_articles_list = QListWidget()
        self.calc_articles_list.setWordWrap(True)
        self.calc_articles_list.setSpacing(4)
        left_layout.addWidget(selected_title)
        left_layout.addWidget(self.calc_articles_list)

        controls = QHBoxLayout()
        self.calc_remove_button = QPushButton("− Удалить")
        self.calc_clear_button = QPushButton("Очистить")
        self.calc_copy_button = QPushButton("Копировать итог")
        controls.addWidget(self.calc_remove_button)
        controls.addWidget(self.calc_clear_button)
        controls.addStretch()
        controls.addWidget(self.calc_copy_button)
        left_layout.addLayout(controls)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        detail_title = QLabel("Источник и распознанное наказание")
        detail_title.setObjectName("sectionTitle")
        self.calc_details = QTextBrowser()
        right_layout.addWidget(detail_title)
        right_layout.addWidget(self.calc_details)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([500, 650])
        root.addWidget(splitter, stretch=1)

        self.calc_status = QLabel(
            "Добавьте одну или несколько статей. Дубли не добавляются."
        )
        self.calc_status.setObjectName("muted")
        self.calc_status.setWordWrap(True)
        root.addWidget(self.calc_status)

        self.penalty_calc_entries = []

        self.calc_open_overlay_button.clicked.connect(
            self.show_calculator_overlay
        )
        self.calc_article_input.textChanged.connect(
            self.schedule_penalty_calculator_suggestions
        )
        self.calc_completer.activated[str].connect(
            self.on_penalty_calculator_suggestion_activated
        )
        self.calc_article_input.returnPressed.connect(
            self.add_penalty_calculator_article
        )
        self.calc_add_button.clicked.connect(
            self.add_penalty_calculator_article
        )
        self.calc_remove_button.clicked.connect(
            self.remove_penalty_calculator_article
        )
        self.calc_clear_button.clicked.connect(
            self.clear_penalty_calculator
        )
        self.calc_copy_button.clicked.connect(
            self.copy_penalty_calculator_total
        )
        self.calc_articles_list.currentRowChanged.connect(
            self.show_penalty_calculator_entry
        )

        self.refresh_penalty_calculator()
        return page

    def schedule_penalty_calculator_suggestions(self, text):
        query = (text or "").strip()
        self._pending_calc_suggestion_query = query
        self.calc_suggestion_timer.stop()

        if len(query) < 2:
            self.calc_suggestion_model.setStringList([])
            return

        self.calc_suggestion_timer.start()

    def run_penalty_calculator_suggestions(self):
        query = str(
            getattr(self, "_pending_calc_suggestion_query", "") or ""
        ).strip()
        if not query or query != self.calc_article_input.text().strip():
            return

        try:
            suggestions = self.smart_text_search.suggest(
                query,
                limit=10,
                history=self.search_history,
            )
        except Exception:
            suggestions = []

        if query != self.calc_article_input.text().strip():
            return

        self.calc_suggestion_model.setStringList(suggestions)
        if suggestions:
            self.calc_completer.setCompletionPrefix("")
            self.calc_completer.complete()

    def on_penalty_calculator_suggestion_activated(self, suggestion):
        suggestion = str(suggestion or "").strip()
        if not suggestion:
            return
        self.calc_article_input.setText(suggestion)
        self.calc_article_input.setCursorPosition(len(suggestion))

    def _penalty_calculator_article_label(self, article):
        number = str(
            self._memo_result_value(article, "article_number", "") or ""
        ).strip()
        law = str(
            self._memo_result_value(article, "law_title", "") or ""
        ).strip()
        title = str(
            self._memo_result_value(article, "article_title", "") or ""
        ).strip()

        short = self.memo_law_short_name(law)
        label = f"{number} {short}".strip()
        if title:
            label += f" — {title}"
        return label

    def _show_penalty_calculator_choices(self, articles):
        menu = QMenu(self)
        for article in list(articles)[:10]:
            action = menu.addAction(
                self._penalty_calculator_article_label(article)
            )
            action.triggered.connect(
                lambda checked=False, row=article:
                self.commit_penalty_calculator_article(row)
            )

        self.penalty_calc_choice_menu = menu
        point = self.calc_article_input.mapToGlobal(
            self.calc_article_input.rect().bottomLeft()
        )
        menu.popup(point)

    def add_penalty_calculator_article(self):
        query = self.calc_article_input.text().strip()
        if not query:
            self.calc_status.setText(
                "Введите статью или описание ситуации."
            )
            return

        self.calc_suggestion_timer.stop()

        exact = self._smart_article_search(query)
        if exact:
            self.commit_penalty_calculator_article(exact[0])
            return

        self.calc_status.setText("Ищу подходящие статьи…")
        QApplication.processEvents()

        try:
            results = list(self.smart_text_search.search(query, 10))
        except Exception:
            results = []

        if not results:
            self.calc_status.setText(
                "Подходящие статьи не найдены. Проверьте запрос или обновите базу."
            )
            return

        if len(results) == 1:
            self.commit_penalty_calculator_article(results[0])
            return

        self.calc_status.setText(
            "Выберите нужную статью из найденных вариантов."
        )
        self._show_penalty_calculator_choices(results)

    def ask_penalty_calculator_fine_amount(
        self,
        fine_min,
        fine_max,
        article_label="",
        parent=None,
    ):
        """Ask for the exact fine when the article contains a range.

        Example:
            source: 15 000–30 000 ₽
            UI:     user enters any value from 15 000 to 30 000

        Returns the chosen integer, or None if the user cancels.
        """
        try:
            minimum = int(fine_min)
            maximum = int(fine_max)
        except (TypeError, ValueError):
            return None

        if minimum > maximum:
            minimum, maximum = maximum, minimum

        if minimum == maximum:
            return minimum

        if parent is None:
            parent = self

        title = "Выберите размер штрафа"
        article_line = (
            f"{article_label}\n\n" if article_label else ""
        )
        label = (
            article_line
            + "В статье указан диапазон штрафа.\n"
            + "Введите точную сумму, которая применяется в этой ситуации:\n\n"
            + f"Минимум: {self._format_calc_money(minimum)}\n"
            + f"Максимум: {self._format_calc_money(maximum)}"
        )

        value, ok = QInputDialog.getInt(
            parent,
            title,
            label,
            minimum,
            minimum,
            maximum,
            1,
        )

        if not ok:
            return None

        return int(value)

    def ask_penalty_calculator_alternative_type(
        self,
        article_label,
        fine_min,
        fine_max,
        prison_min,
        prison_max,
        arrest_min=None,
        arrest_max=None,
        parent=None,
    ):
        """Ask which explicit alternative sanction is actually applied."""
        if parent is None:
            parent = self

        options = []

        if fine_min is not None or fine_max is not None:
            low = fine_min if fine_min is not None else fine_max
            high = fine_max if fine_max is not None else fine_min
            if low == high:
                value_text = self._format_calc_money(low)
            else:
                value_text = (
                    f"{self._format_calc_money(low)} – "
                    f"{self._format_calc_money(high)}"
                )
            options.append(("fine", f"💰 Штраф: {value_text}"))

        if prison_min is not None or prison_max is not None:
            low = prison_min if prison_min is not None else prison_max
            high = prison_max if prison_max is not None else prison_min
            if low == high:
                value_text = self._format_calc_duration(low)
            else:
                value_text = (
                    f"{self._format_calc_duration(low)} – "
                    f"{self._format_calc_duration(high)}"
                )
            options.append(
                ("prison", f"⛓ Лишение свободы: {value_text}")
            )

        if arrest_min is not None or arrest_max is not None:
            low = arrest_min if arrest_min is not None else arrest_max
            high = arrest_max if arrest_max is not None else arrest_min
            if low == high:
                value_text = self._format_calc_duration(low)
            else:
                value_text = (
                    f"{self._format_calc_duration(low)} – "
                    f"{self._format_calc_duration(high)}"
                )
            options.append(
                ("arrest", f"🚔 Административный арест: {value_text}")
            )

        if len(options) <= 1:
            return options[0][0] if options else None

        dialog = QMessageBox(parent)
        dialog.setWindowTitle("Выберите наказание")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(
            f"{article_label}\n\n"
            "В статье предусмотрены альтернативные наказания."
        )
        dialog.setInformativeText(
            "Выберите, какое наказание применяется в этой ситуации:\n\n"
            + "\n".join(label for _, label in options)
            + "\n\nВ общий итог попадёт только выбранный вариант."
        )

        button_map = {}
        for kind, label in options:
            if kind == "fine":
                caption = "💰 Выбрать штраф"
            elif kind == "prison":
                caption = "⛓ Выбрать лишение свободы"
            else:
                caption = "🚔 Выбрать административный арест"

            button = dialog.addButton(
                caption,
                QMessageBox.ButtonRole.AcceptRole,
            )
            button_map[button] = kind

        dialog.addButton(
            "Отмена",
            QMessageBox.ButtonRole.RejectRole,
        )
        dialog.exec()

        return button_map.get(dialog.clickedButton())

    def commit_penalty_calculator_article(self, article, dialog_parent=None):
        number = str(
            self._memo_result_value(article, "article_number", "") or ""
        ).strip()
        law = str(
            self._memo_result_value(article, "law_title", "") or ""
        ).strip()
        content = str(
            self._memo_result_value(article, "content", "") or ""
        )
        title = str(
            self._memo_result_value(article, "article_title", "") or ""
        ).strip()
        url = str(
            self._memo_result_value(article, "url", "") or ""
        ).strip()

        if not number or not law:
            self.calc_status.setText(
                "Не удалось определить статью."
            )
            return

        duplicate = any(
            entry["article_number"] == number
            and entry["law_title"] == law
            for entry in self.penalty_calc_entries
        )
        if duplicate:
            self.calc_status.setText(
                "Эта статья уже участвует в расчёте."
            )
            return

        parsed = self._parse_penalty_for_calculator(content)

        fine_min = parsed.get("fine_min")
        fine_max = parsed.get("fine_max")
        prison_min = parsed.get("prison_min_days")
        prison_max = parsed.get("prison_max_days")
        arrest_min = parsed.get("arrest_min_days")
        arrest_max = parsed.get("arrest_max_days")

        has_fine = fine_min is not None or fine_max is not None
        has_prison = prison_min is not None or prison_max is not None
        has_arrest = arrest_min is not None or arrest_max is not None
        selected_penalty_type = None
        selected_fine_amount = None

        article_label = self._penalty_calculator_article_label(
            {
                "article_number": number,
                "law_title": law,
                "article_title": title,
            }
        )

        # If the source explicitly says «штраф ... или/либо лишение свободы»,
        # ask which sanction is actually applied.  We never add both to the
        # total in this case.
        if (
            parsed.get("alternative")
            and sum((has_fine, has_prison, has_arrest)) >= 2
        ):
            selected_penalty_type = (
                self.ask_penalty_calculator_alternative_type(
                    article_label,
                    fine_min,
                    fine_max,
                    prison_min,
                    prison_max,
                    arrest_min,
                    arrest_max,
                    parent=dialog_parent,
                )
            )

            if selected_penalty_type is None:
                if dialog_parent is not None and hasattr(
                    self,
                    "calculator_overlay_status",
                ):
                    self.calculator_overlay_status.setText(
                        "Добавление отменено: наказание не выбрано."
                    )
                self.calc_status.setText(
                    "Добавление отменено: наказание не выбрано."
                )
                return

        # A fine range requires an exact amount only when the fine is really
        # being applied.  If imprisonment was chosen, no fine prompt appears.
        fine_is_active = (
            selected_penalty_type in (None, "fine")
        )
        if (
            fine_is_active
            and fine_min is not None
            and fine_max is not None
            and int(fine_min) != int(fine_max)
        ):
            selected_fine_amount = (
                self.ask_penalty_calculator_fine_amount(
                    fine_min,
                    fine_max,
                    article_label=article_label,
                    parent=dialog_parent,
                )
            )

            if selected_fine_amount is None:
                if dialog_parent is not None and hasattr(
                    self,
                    "calculator_overlay_status",
                ):
                    self.calculator_overlay_status.setText(
                        "Добавление отменено: сумма штрафа не выбрана."
                    )
                self.calc_status.setText(
                    "Добавление отменено: сумма штрафа не выбрана."
                )
                return

        entry = {
            "article_number": number,
            "law_title": law,
            "article_title": title,
            "content": content,
            "url": url,
            "selected_penalty_type": selected_penalty_type,
            "selected_fine_amount": selected_fine_amount,
            **parsed,
        }
        self.penalty_calc_entries.append(entry)

        self.calc_article_input.clear()
        self.refresh_penalty_calculator()
        self.save_profile_calculator_state()
        self.calc_articles_list.setCurrentRow(
            len(self.penalty_calc_entries) - 1
        )

        if parsed["recognized"]:
            if selected_penalty_type == "fine":
                choice_text = " • выбран штраф"
            elif selected_penalty_type == "prison":
                choice_text = " • выбрано лишение свободы"
            elif selected_penalty_type == "arrest":
                choice_text = " • выбран административный арест"
            else:
                choice_text = ""

            self.calc_status.setText(
                f"Добавлено: "
                f"{self._penalty_calculator_article_label(entry)}"
                f"{choice_text}"
            )
        else:
            self.calc_status.setText(
                "Статья добавлена, но числовое наказание автоматически "
                "не распознано. Проверьте источник справа."
            )

    def refresh_penalty_calculator(self):
        current = self.calc_articles_list.currentRow()
        self.calc_articles_list.clear()

        fine_min_total = 0
        fine_max_total = 0
        fine_count = 0

        prison_min_total = 0
        prison_max_total = 0
        prison_count = 0

        arrest_min_total = 0
        arrest_max_total = 0
        arrest_count = 0

        for index, entry in enumerate(self.penalty_calc_entries):
            fine_min = entry.get("fine_min")
            fine_max = entry.get("fine_max")
            prison_min = entry.get("prison_min_days")
            prison_max = entry.get("prison_max_days")
            arrest_min = entry.get("arrest_min_days")
            arrest_max = entry.get("arrest_max_days")

            lines = [self._penalty_calculator_article_label(entry)]
            selected_type = entry.get("selected_penalty_type")
            fine_is_active = selected_type in (None, "fine")
            prison_is_active = selected_type in (None, "prison")
            arrest_is_active = selected_type in (None, "arrest")

            if selected_type == "fine":
                lines.append("✓ Выбрано наказание: штраф")
            elif selected_type == "prison":
                lines.append("✓ Выбрано наказание: лишение свободы")
            elif selected_type == "arrest":
                lines.append("✓ Выбрано наказание: административный арест")

            if fine_is_active and (fine_min is not None or fine_max is not None):
                low = fine_min if fine_min is not None else fine_max
                high = fine_max if fine_max is not None else fine_min
                selected_fine = entry.get("selected_fine_amount")

                fine_count += 1

                if selected_fine is not None:
                    fine_min_total += int(selected_fine)
                    fine_max_total += int(selected_fine)
                    if low != high:
                        lines.append(
                            "💰 "
                            f"{self._format_calc_money(selected_fine)} "
                            f"(выбрано из "
                            f"{self._format_calc_money(low)} – "
                            f"{self._format_calc_money(high)})"
                        )
                    else:
                        lines.append(
                            f"💰 {self._format_calc_money(selected_fine)}"
                        )
                else:
                    fine_min_total += int(low or 0)
                    fine_max_total += int(high or 0)
                    if low == high:
                        lines.append(
                            f"💰 {self._format_calc_money(low)}"
                        )
                    else:
                        lines.append(
                            "💰 "
                            f"{self._format_calc_money(low)} – "
                            f"{self._format_calc_money(high)}"
                        )

            if prison_is_active and (
                prison_min is not None or prison_max is not None
            ):
                low = prison_min if prison_min is not None else prison_max
                high = prison_max if prison_max is not None else prison_min
                prison_count += 1
                prison_min_total += int(low or 0)
                prison_max_total += int(high or 0)
                if low == high:
                    lines.append(
                        f"⛓ {self._format_calc_duration(low)}"
                    )
                else:
                    lines.append(
                        "⛓ "
                        f"{self._format_calc_duration(low)} – "
                        f"{self._format_calc_duration(high)}"
                    )

            if arrest_is_active and (
                arrest_min is not None or arrest_max is not None
            ):
                low = arrest_min if arrest_min is not None else arrest_max
                high = arrest_max if arrest_max is not None else arrest_min
                arrest_count += 1
                arrest_min_total += int(low or 0)
                arrest_max_total += int(high or 0)
                if low == high:
                    lines.append(
                        f"🚔 {self._format_calc_duration(low)}"
                    )
                else:
                    lines.append(
                        "🚔 "
                        f"{self._format_calc_duration(low)} – "
                        f"{self._format_calc_duration(high)}"
                    )

            if entry.get("alternative") and selected_type is None:
                lines.append("↔ альтернативное наказание: «или / либо»")

            if not entry.get("recognized"):
                lines.append("⚠ числовая санкция не распознана")

            item = QListWidgetItem("\n".join(lines))
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(entry.get("clause") or entry.get("content") or "")
            self.calc_articles_list.addItem(item)

        if fine_count:
            if fine_min_total == fine_max_total:
                fine_text = self._format_calc_money(fine_min_total)
            else:
                fine_text = (
                    f"{self._format_calc_money(fine_min_total)} – "
                    f"{self._format_calc_money(fine_max_total)}"
                )
        else:
            fine_text = "0 ₽"

        if prison_count:
            if prison_min_total == prison_max_total:
                prison_text = self._format_calc_duration(prison_min_total)
            else:
                prison_text = (
                    f"{self._format_calc_duration(prison_min_total)} – "
                    f"{self._format_calc_duration(prison_max_total)}"
                )
        else:
            prison_text = "0 дней"

        if arrest_count:
            if arrest_min_total == arrest_max_total:
                arrest_text = self._format_calc_duration(arrest_min_total)
            else:
                arrest_text = (
                    f"{self._format_calc_duration(arrest_min_total)} – "
                    f"{self._format_calc_duration(arrest_max_total)}"
                )
        else:
            arrest_text = "0 дней"

        self.calc_fine_total.setText(fine_text)
        self.calc_prison_total.setText(prison_text)
        self.calc_arrest_total.setText(arrest_text)

        count = len(self.penalty_calc_entries)
        if count % 10 == 1 and count % 100 != 11:
            word = "статья"
        elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
            word = "статьи"
        else:
            word = "статей"
        self.calc_count_total.setText(f"{count} {word}")

        if count:
            current = max(0, min(current, count - 1))
            self.calc_articles_list.setCurrentRow(current)
        else:
            self.calc_details.clear()

        # The F9 overlay and the normal Calculator page share one calculation
        # state, so changes made in either place appear in the other instantly.
        self.refresh_penalty_calculator_overlay()

    def show_penalty_calculator_entry(self, row):
        if row < 0 or row >= len(self.penalty_calc_entries):
            self.calc_details.clear()
            return

        entry = self.penalty_calc_entries[row]
        label = self._penalty_calculator_article_label(entry)
        clause = entry.get("clause") or "Автоматически не найдено."
        content = entry.get("content") or ""

        fine_min = entry.get("fine_min")
        fine_max = entry.get("fine_max")
        prison_min = entry.get("prison_min_days")
        prison_max = entry.get("prison_max_days")
        arrest_min = entry.get("arrest_min_days")
        arrest_max = entry.get("arrest_max_days")

        detected = []
        selected_type = entry.get("selected_penalty_type")
        fine_is_active = selected_type in (None, "fine")
        prison_is_active = selected_type in (None, "prison")
        arrest_is_active = selected_type in (None, "arrest")

        if selected_type == "fine":
            detected.append("ВЫБРАНО: штраф")
        elif selected_type == "prison":
            detected.append("ВЫБРАНО: лишение свободы")
        elif selected_type == "arrest":
            detected.append("ВЫБРАНО: административный арест")

        if fine_min is not None or fine_max is not None:
            low = fine_min if fine_min is not None else fine_max
            high = fine_max if fine_max is not None else fine_min
            selected_fine = entry.get("selected_fine_amount")

            if selected_fine is not None and low != high:
                detected.append(
                    "Штраф по статье: "
                    f"{self._format_calc_money(low)} – "
                    f"{self._format_calc_money(high)}"
                )
                detected.append(
                    "Выбранный штраф: "
                    f"{self._format_calc_money(selected_fine)}"
                )
            elif selected_fine is not None:
                detected.append(
                    f"Штраф: {self._format_calc_money(selected_fine)}"
                )
            elif low == high:
                detected.append(
                    f"Штраф: {self._format_calc_money(low)}"
                )
            else:
                detected.append(
                    "Штраф: "
                    f"{self._format_calc_money(low)} – "
                    f"{self._format_calc_money(high)}"
                )

            if not fine_is_active:
                detected.append("↳ штраф не включён в итог")

        if prison_min is not None or prison_max is not None:
            low = prison_min if prison_min is not None else prison_max
            high = prison_max if prison_max is not None else prison_min
            if low == high:
                detected.append(
                    f"Лишение свободы: {self._format_calc_duration(low)}"
                )
            else:
                detected.append(
                    "Лишение свободы: "
                    f"{self._format_calc_duration(low)} – "
                    f"{self._format_calc_duration(high)}"
                )

            if not prison_is_active:
                detected.append("↳ срок не включён в итог")

        if arrest_min is not None or arrest_max is not None:
            low = arrest_min if arrest_min is not None else arrest_max
            high = arrest_max if arrest_max is not None else arrest_min
            if low == high:
                detected.append(
                    f"Административный арест: "
                    f"{self._format_calc_duration(low)}"
                )
            else:
                detected.append(
                    "Административный арест: "
                    f"{self._format_calc_duration(low)} – "
                    f"{self._format_calc_duration(high)}"
                )

            if not arrest_is_active:
                detected.append(
                    "↳ административный арест не включён в итог"
                )

        if entry.get("alternative"):
            if selected_type == "fine":
                detected.append(
                    "Альтернативная санкция: в итог включён только штраф."
                )
            elif selected_type == "prison":
                detected.append(
                    "Альтернативная санкция: в итог включено только "
                    "лишение свободы."
                )
            elif selected_type == "arrest":
                detected.append(
                    "Альтернативная санкция: в итог включён только "
                    "административный арест."
                )
            else:
                detected.append(
                    "Тип: альтернативное наказание — применяется один из "
                    "вариантов, указанных через «или / либо»."
                )

        detected_text = "\n".join(detected) if detected else (
            "Числовое наказание не распознано автоматически."
        )

        self.calc_details.setPlainText(
            f"{label}\n\n"
            f"РАСПОЗНАНО\n{detected_text}\n\n"
            f"ФРАГМЕНТ САНКЦИИ\n{clause}\n\n"
            f"ПОЛНЫЙ ТЕКСТ СТАТЬИ\n{content}"
        )

    def save_profile_calculator_state(self):
        if hasattr(self, "profile_store"):
            self.profile_store.save_runtime(
                memo_columns=self.memo_columns,
                calculator_entries=self.penalty_calc_entries,
                name=self.active_profile,
            )

    def remove_penalty_calculator_article(self):
        row = self.calc_articles_list.currentRow()
        if row < 0 or row >= len(self.penalty_calc_entries):
            return
        self.penalty_calc_entries.pop(row)
        self.refresh_penalty_calculator()
        self.save_profile_calculator_state()
        self.calc_status.setText("Статья удалена из расчёта.")

    def clear_penalty_calculator(self):
        self.penalty_calc_entries = []
        self.refresh_penalty_calculator()
        self.save_profile_calculator_state()
        self.calc_status.setText("Расчёт очищен.")

    def copy_penalty_calculator_total(self):
        count = len(self.penalty_calc_entries)
        if not count:
            self.calc_status.setText("Сначала добавьте статьи.")
            return

        lines = [
            "DeiLaw — расчёт наказаний",
            f"Штрафы: {self.calc_fine_total.text()}",
            f"Лишение свободы: {self.calc_prison_total.text()}",
            f"Административный арест: {self.calc_arrest_total.text()}",
            "",
            "Статьи:",
        ]
        for entry in self.penalty_calc_entries:
            suffix = ""
            selected_type = entry.get("selected_penalty_type")
            if selected_type == "fine":
                suffix = " — выбран штраф"
            elif selected_type == "prison":
                suffix = " — выбрано лишение свободы"
            elif selected_type == "arrest":
                suffix = " — выбран административный арест"

            lines.append(
                "• "
                + self._penalty_calculator_article_label(entry)
                + suffix
            )

        QApplication.clipboard().setText("\n".join(lines))
        self.calc_status.setText("Итог скопирован в буфер обмена.")

    def create_memo_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("RP Quick Memo")
        title.setObjectName("pageTitle")
        description = QLabel(
            "Настраиваемая памятка. Добавляйте столбцы и статьи, "
            "а отдельное окно можно держать поверх игры."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(description)

        self.memo_add_column_button = QPushButton("+ Столбец")
        self.memo_overlay_button = QPushButton("↗ Открыть отдельно")
        self.memo_overlay_button.setObjectName("primary")
        header.addLayout(title_box, stretch=1)
        header.addWidget(self.memo_add_column_button)
        header.addWidget(self.memo_overlay_button)

        add_row = QHBoxLayout()
        self.memo_article_input = QLineEdit()
        self.memo_article_input.setPlaceholderText(
            "Добавить: 9.8 КоАП, 63.2 УК РФ, 15.3 ПДД..."
        )
        self.memo_add_button = QPushButton("+ Добавить статью")

        # The Memo input uses the same live suggestion engine as the main
        # Search page. It can suggest exact article numbers, document names,
        # synonyms and natural-language situations from the local database.
        self.memo_suggestion_model = QStringListModel(self)
        self.memo_completer = QCompleter(
            self.memo_suggestion_model,
            self.memo_article_input,
        )
        self.memo_completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.memo_completer.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self.memo_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.memo_completer.setMaxVisibleItems(10)
        self.memo_article_input.setCompleter(self.memo_completer)

        add_row.addWidget(self.memo_article_input, stretch=1)
        add_row.addWidget(self.memo_add_button)

        self.memo_scroll = QScrollArea()
        self.memo_scroll.setWidgetResizable(True)
        self.memo_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.memo_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.memo_board = QWidget()
        self.memo_board_layout = QHBoxLayout(self.memo_board)
        self.memo_board_layout.setContentsMargins(0, 0, 0, 0)
        self.memo_board_layout.setSpacing(12)
        self.memo_scroll.setWidget(self.memo_board)

        self.memo_status = QLabel(
            "Двойной клик по статье — полный текст. "
            "Контекстное меню карточки — перенос или удаление."
        )
        self.memo_status.setObjectName("muted")

        self.memo_content = QTextBrowser()
        self.memo_content.setMinimumHeight(90)

        root.addLayout(header)
        root.addLayout(add_row)

        # Вертикальный разделитель:
        # верх — доска памятки, низ — полная расшифровка статьи.
        self.memo_main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.memo_main_splitter.setChildrenCollapsible(False)
        self.memo_main_splitter.setHandleWidth(8)

        self.memo_top_panel = QWidget()
        memo_top_layout = QVBoxLayout(self.memo_top_panel)
        memo_top_layout.setContentsMargins(0, 0, 0, 0)
        memo_top_layout.setSpacing(6)
        memo_top_layout.addWidget(self.memo_scroll)
        memo_top_layout.addWidget(self.memo_status)

        self.memo_details_panel = QWidget()
        memo_details_layout = QVBoxLayout(self.memo_details_panel)
        memo_details_layout.setContentsMargins(0, 0, 0, 0)
        memo_details_layout.setSpacing(6)

        details_header = QLabel("Полная расшифровка статьи")
        details_header.setObjectName("sectionTitle")
        memo_details_layout.addWidget(details_header)
        memo_details_layout.addWidget(self.memo_content)

        self.memo_main_splitter.addWidget(self.memo_top_panel)
        self.memo_main_splitter.addWidget(self.memo_details_panel)

        # Начальное соотношение. После открытия пользователь может
        # свободно двигать границу мышкой вверх/вниз.
        self.memo_main_splitter.setStretchFactor(0, 3)
        self.memo_main_splitter.setStretchFactor(1, 1)
        saved_main_sizes = self.app_settings.get("memo_main_sizes", [650, 220])
        if (
            self.app_settings.get("remember_memo_layout", True)
            and isinstance(saved_main_sizes, list)
            and len(saved_main_sizes) == 2
        ):
            self.memo_main_splitter.setSizes(saved_main_sizes)
        else:
            self.memo_main_splitter.setSizes([650, 220])

        self.memo_main_splitter.splitterMoved.connect(
            self.save_memo_layout_state
        )

        root.addWidget(self.memo_main_splitter, stretch=1)

        self.memo_add_button.clicked.connect(self.add_memo_article)
        self.memo_article_input.returnPressed.connect(self.add_memo_article)
        # Debounce Memo suggestions: database-backed suggestion generation is
        # intentionally delayed until the user pauses typing. This prevents
        # repeated full article scans on every key press.
        self.memo_suggestion_timer = QTimer(self)
        self.memo_suggestion_timer.setSingleShot(True)
        self.memo_suggestion_timer.setInterval(220)
        self.memo_suggestion_timer.timeout.connect(
            self.run_memo_search_suggestions
        )

        self.memo_article_input.textChanged.connect(
            self.schedule_memo_search_suggestions
        )
        self.memo_completer.activated[str].connect(
            self.on_memo_search_suggestion_activated
        )
        self.memo_add_column_button.clicked.connect(self.add_memo_column)
        self.memo_overlay_button.clicked.connect(self.show_memo_overlay)

        self.refresh_memo_board()
        return page

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self.clear_layout(child_layout)

    def refresh_memo_board(self):
        if not hasattr(self, "memo_board_layout"):
            return

        self.clear_layout(self.memo_board_layout)
        self.memo_lists = []

        # Horizontal splitter = mouse-resizable column widths.
        self.memo_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.memo_splitter.setChildrenCollapsible(False)
        self.memo_splitter.setHandleWidth(7)

        for column_index, column in enumerate(self.memo_columns):
            frame = QFrame()
            frame.setObjectName("card")
            frame.setMinimumWidth(220)

            outer = QVBoxLayout(frame)
            outer.setContentsMargins(10, 10, 10, 10)
            outer.setSpacing(8)

            header = QHBoxLayout()
            name = QLabel(column["name"])
            name.setObjectName("sectionTitle")
            rename = QPushButton("✏")
            rename.setObjectName("memoIconButton")
            rename.setFixedSize(46, 42)
            delete = QPushButton("✕")
            delete.setObjectName("memoIconButton")
            delete.setFixedSize(46, 42)
            rename.clicked.connect(lambda checked=False, i=column_index: self.rename_memo_column(i))
            delete.clicked.connect(lambda checked=False, i=column_index: self.delete_memo_column(i))
            header.addWidget(name)
            header.addStretch()
            header.addWidget(rename)
            header.addWidget(delete)
            outer.addLayout(header)

            # Vertical splitter = split one column into top/bottom sections.
            vertical = QSplitter(Qt.Orientation.Vertical)
            vertical.setObjectName(f"memoSectionSplitter_{column_index}")
            vertical.setChildrenCollapsible(False)
            vertical.setHandleWidth(7)

            for section_index, section in enumerate(column.get("sections", [])):
                section_frame = QFrame()
                section_layout = QVBoxLayout(section_frame)
                section_layout.setContentsMargins(4, 4, 4, 4)

                sec_header = QHBoxLayout()

                # Первый раздел использует название столбца.
                if section_index > 0:
                    sec_name = QLabel(section.get("name") or "Раздел")
                    sec_name.setStyleSheet("font-weight: 700;")
                    sec_rename = QPushButton("✏")
                    sec_rename.setObjectName("memoIconButton")
                    sec_rename.setFixedSize(44, 40)
                    sec_rename.setToolTip("Переименовать раздел")
                    sec_delete = QPushButton("✕")
                    sec_delete.setObjectName("memoIconButton")
                    sec_delete.setFixedSize(44, 40)
                    sec_delete.setToolTip("Удалить раздел")
                    sec_rename.clicked.connect(
                        lambda checked=False, c=column_index, s=section_index:
                        self.rename_memo_section(c, s)
                    )
                    sec_delete.clicked.connect(
                        lambda checked=False, c=column_index, s=section_index:
                        self.delete_memo_section(c, s)
                    )
                    sec_header.addWidget(sec_name)
                    sec_header.addStretch()
                    sec_header.addWidget(sec_rename)
                    sec_header.addWidget(sec_delete)

                lst = QListWidget()
                lst.setMinimumHeight(110)
                lst.setWordWrap(True)
                lst.setTextElideMode(Qt.TextElideMode.ElideNone)
                lst.setHorizontalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                )
                lst.setResizeMode(QListWidget.ResizeMode.Adjust)
                lst.setSpacing(4)
                lst.itemDoubleClicked.connect(
                    lambda item, c=column_index, s=section_index:
                    self.open_memo_item(c, item)
                )
                lst.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                lst.customContextMenuRequested.connect(
                    lambda pos, c=column_index, s=section_index, l=lst:
                    self.memo_item_context_menu(c, s, l, pos)
                )

                for article_index, ref in enumerate(section.get("articles", [])):
                    article = self.find_exact_article(
                        ref.get("article_number", ""), ref.get("law_title", "")
                    )
                    if article:
                        short = self.memo_law_short_name(article["law_title"])
                        description = self.memo_card_description(article)
                        penalty = (
                            self.extract_article_penalty(article["content"])
                            if self.app_settings.get("show_penalties", True) and short != "ПДД"
                            else ""
                        )
                        label = f"{article['article_number']} {short}\n{description}"
                        if penalty:
                            label += f"\n⚖ Наказание: {penalty}"
                    else:
                        label = f"⚠ {ref.get('article_number', '?')}\nСтатья не найдена"
                    item = QListWidgetItem(label)
                    item.setData(Qt.ItemDataRole.UserRole, {
                        "column": column_index, "section": section_index,
                        "article": article_index, "ref": ref
                    })
                    item.setToolTip(label)
                    lst.addItem(item)

                if section_index > 0:
                    section_layout.addLayout(sec_header)
                section_layout.addWidget(lst)
                vertical.addWidget(section_frame)

            outer.addWidget(vertical, stretch=1)

            split_button = QPushButton("↕ Разделить")
            split_button.setToolTip("Добавить ещё один раздел снизу в этом столбце")
            split_button.clicked.connect(
                lambda checked=False, i=column_index: self.split_memo_column(i)
            )
            outer.addWidget(split_button)
            self.memo_splitter.addWidget(frame)

        self.memo_board_layout.addWidget(self.memo_splitter)

        if self.app_settings.get("remember_memo_layout", True):
            column_sizes = self.app_settings.get("memo_column_sizes", [])
            if isinstance(column_sizes, list) and len(column_sizes) == self.memo_splitter.count():
                self.memo_splitter.setSizes(column_sizes)

            section_sizes = self.app_settings.get("memo_section_sizes", {})
            for i in range(self.memo_splitter.count()):
                frame = self.memo_splitter.widget(i)
                if frame is None:
                    continue
                vertical = frame.findChild(
                    QSplitter, f"memoSectionSplitter_{i}"
                )
                sizes = section_sizes.get(str(i), [])
                if vertical is not None and isinstance(sizes, list) and len(sizes) == vertical.count():
                    vertical.setSizes(sizes)
                if vertical is not None:
                    vertical.splitterMoved.connect(
                        self.save_memo_layout_state
                    )

        self.memo_splitter.splitterMoved.connect(
            self.save_memo_layout_state
        )
        self.refresh_memo_overlay_if_open()
        self.install_button_sounds()


    def split_memo_column(self, column_index):
        value, ok = QInputDialog.getText(
            self, "Разделить столбец", "Название нового раздела:"
        )
        value = value.strip()
        if ok and value:
            self.memo_columns[column_index].setdefault("sections", []).append(
                {"name": value, "articles": []}
            )
            self.save_memo_config()
            self.refresh_memo_board()

    def rename_memo_section(self, column_index, section_index):
        section = self.memo_columns[column_index]["sections"][section_index]
        value, ok = QInputDialog.getText(
            self, "Название раздела", "Новое название:", text=section["name"]
        )
        value = value.strip()
        if ok and value:
            section["name"] = value
            self.save_memo_config()
            self.refresh_memo_board()

    def delete_memo_section(self, column_index, section_index):
        sections = self.memo_columns[column_index].get("sections", [])
        if len(sections) <= 1:
            self.memo_status.setText(
                "Нельзя удалить последний раздел столбца. Удалите сам столбец."
            )
            return

        section = sections[section_index]
        count = len(section.get("articles", []))
        if count and self.app_settings.get("confirm_delete_column", True):
            answer = QMessageBox.question(
                self,
                "Удалить раздел",
                f"В разделе «{section.get('name', 'Раздел')}» находится "
                f"статей: {count}. Удалить раздел вместе с ними?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        removed_name = section.get("name", "Раздел")
        sections.pop(section_index)
        self.save_memo_config()
        self.refresh_memo_board()
        self.memo_status.setText(f"Раздел «{removed_name}» удалён.")

    def find_exact_article(self, article_number, law_title):
        target = law_title.lower().replace("ё", "е")
        for law in self.database.get_laws():
            current = law["title"].lower().replace("ё", "е")
            if current != target:
                continue
            for article in self.database.get_articles_by_law(law["id"]):
                if str(article["article_number"]).strip() == str(article_number).strip():
                    return {
                        "article_number": article["article_number"],
                        "article_title": article["title"] or "",
                        "content": article["content"] or "",
                        "law_title": law["title"],
                        "url": law["url"],
                    }
        return None

    @staticmethod
    def _memo_result_value(row, key, default=""):
        """Read a value from dict-like search results or sqlite3.Row safely."""
        if row is None:
            return default

        if isinstance(row, dict):
            value = row.get(key, default)
            return default if value is None else value

        try:
            value = row[key]
            return default if value is None else value
        except Exception:
            return default

    def schedule_memo_search_suggestions(self, text):
        """Queue Memo suggestions after the user pauses typing."""
        query = (text or "").strip()
        self._pending_memo_suggestion_query = query

        timer = getattr(self, "memo_suggestion_timer", None)
        if timer is None:
            self.update_memo_search_suggestions(query)
            return

        timer.stop()

        if not query:
            self.memo_suggestion_model.setStringList([])
            self.memo_status.setText(
                "Двойной клик по статье — полный текст. "
                "Контекстное меню карточки — перенос или удаление."
            )
            return

        if len(query) < 2:
            self.memo_suggestion_model.setStringList([])
            self.memo_status.setText(
                "Продолжайте ввод — появятся варианты статьи или ситуации…"
            )
            return

        self.memo_status.setText("Ищу подходящие варианты…")
        timer.start()

    def run_memo_search_suggestions(self):
        query = str(
            getattr(self, "_pending_memo_suggestion_query", "") or ""
        ).strip()

        # The text may have changed again while the timer was waiting.
        if query != self.memo_article_input.text().strip():
            return

        self.update_memo_search_suggestions(query)

    def update_memo_search_suggestions(self, text):
        """Use the same suggestion source as the main Search page.

        Important: do not validate every suggestion with another database scan.
        The old implementation could scan the whole legislation database dozens
        of times for a single keystroke and made the UI feel frozen.
        """
        query = (text or "").strip()

        if not query:
            self.memo_suggestion_model.setStringList([])
            return

        if len(query) < 2:
            self.memo_suggestion_model.setStringList([])
            return

        try:
            suggestions = self.smart_text_search.suggest(
                query,
                limit=10,
                history=self.search_history,
            )
        except Exception:
            suggestions = []

        # Ignore a stale result if the user has already typed something else.
        if query != self.memo_article_input.text().strip():
            return

        self.memo_suggestion_model.setStringList(suggestions)

        if suggestions:
            self.memo_status.setText(
                f"Умные подсказки • вариантов: {len(suggestions)} • "
                "выберите вариант или нажмите Enter"
            )
            self.memo_completer.setCompletionPrefix("")
            self.memo_completer.complete()
        else:
            self.memo_status.setText(
                "Подходящих вариантов пока нет. Продолжайте ввод или нажмите Enter."
            )

    def on_memo_search_suggestion_activated(self, suggestion):
        """Put the selected smart suggestion into the Memo add field."""
        suggestion = str(suggestion or "").strip()
        if not suggestion:
            return

        self.memo_article_input.setText(suggestion)
        self.memo_article_input.setCursorPosition(len(suggestion))
        self.memo_status.setText(
            "Вариант выбран. Нажмите Enter или «+ Добавить статью»."
        )

    def _memo_article_label(self, article):
        short = self.memo_law_short_name(
            self._memo_result_value(article, "law_title", "")
        )
        number = str(
            self._memo_result_value(article, "article_number", "") or ""
        ).strip()
        title = str(
            self._memo_result_value(article, "article_title", "") or ""
        ).strip()

        label = f"{number} {short}".strip()
        if title:
            label += f" — {title}"
        return label or "Статья"

    def _show_memo_article_choice_menu(self, articles):
        """Show article choices without blocking the Qt event loop."""
        if not articles:
            return

        menu = QMenu(self)
        menu.setTitle("Выберите статью")

        for article in articles[:10]:
            action = menu.addAction(self._memo_article_label(article))
            action.triggered.connect(
                lambda checked=False, row=article:
                self._continue_memo_article_add(row)
            )

        self.memo_article_choice_menu = menu
        self.memo_status.setText(
            f"Найдено вариантов: {min(len(articles), 10)}. "
            "Выберите нужную статью."
        )

        point = self.memo_article_input.mapToGlobal(
            self.memo_article_input.rect().bottomLeft()
        )
        menu.popup(point)

    def _continue_memo_article_add(self, article):
        targets = []
        labels = []

        for ci, column in enumerate(self.memo_columns):
            for si, section in enumerate(column.get("sections", [])):
                labels.append(
                    f"{column['name']} → {section.get('name') or 'Раздел'}"
                )
                targets.append((ci, si))

        if not targets:
            self.memo_status.setText(
                "Сначала создайте хотя бы один столбец/раздел памятки."
            )
            return

        # No need to ask when there is only one possible destination.
        if len(targets) == 1:
            ci, si = targets[0]
            self._commit_memo_article(article, ci, si)
            return

        menu = QMenu(self)
        menu.setTitle("Добавить в раздел")

        for label, (ci, si) in zip(labels, targets):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, c=ci, s=si, row=article:
                self._commit_memo_article(row, c, s)
            )

        self.memo_target_choice_menu = menu
        self.memo_status.setText("Теперь выберите раздел памятки.")

        point = self.memo_add_button.mapToGlobal(
            self.memo_add_button.rect().bottomLeft()
        )
        menu.popup(point)

    def _commit_memo_article(self, article, column_index, section_index):
        number = str(
            self._memo_result_value(article, "article_number", "") or ""
        ).strip()
        law_title = str(
            self._memo_result_value(article, "law_title", "") or ""
        ).strip()

        if not number or not law_title:
            self.memo_status.setText(
                "Не удалось определить номер статьи или документ."
            )
            return

        ref = {
            "article_number": number,
            "law_title": law_title,
        }

        articles = self.memo_columns[column_index]["sections"][
            section_index
        ].setdefault("articles", [])

        duplicate = any(
            str(item.get("article_number", "")).strip() == number
            and str(item.get("law_title", "")).strip() == law_title
            for item in articles
        )

        if not duplicate:
            articles.append(ref)
            self.save_memo_config()
            self.refresh_memo_board()
            self.memo_status.setText(
                f"Добавлено: {self._memo_article_label(article)}"
            )
        else:
            self.memo_status.setText(
                "Эта статья уже есть в выбранном разделе."
            )

        self.memo_article_input.clear()
        self.memo_article_input.setFocus()

    def add_memo_article(self, target_column=None, target_section=None):
        """Resolve and add an article without modal selection dialogs.

        Exact queries are added immediately. Natural-language queries open a
        lightweight QMenu under the input instead of QInputDialog.getItem(),
        so the main window remains responsive.
        """
        query = self.memo_article_input.text().strip()
        if not query:
            self.memo_status.setText(
                "Введите статью или ситуацию, например: 9.8 КоАП."
            )
            return

        # Stop a pending live-suggestion refresh before resolving the request.
        timer = getattr(self, "memo_suggestion_timer", None)
        if timer is not None:
            timer.stop()

        results = self._smart_article_search(query)

        if results:
            article = results[0]
            self._continue_memo_article_add(article)
            return

        self.memo_status.setText("Ищу подходящие статьи…")
        QApplication.processEvents()

        try:
            smart_results = list(
                self.smart_text_search.search(query, 10)
            )
        except Exception:
            smart_results = []

        if not smart_results:
            self.memo_status.setText(
                "Статья не найдена. Попробуйте номер статьи или описание ситуации."
            )
            return

        self._show_memo_article_choice_menu(smart_results)

    def add_memo_column(self):
        value, ok = QInputDialog.getText(self, "Новый столбец", "Название:")
        value = value.strip()
        if ok and value:
            self.memo_columns.append({
                "name": value,
                "sections": [{"name": value, "articles": []}]
            })
            self.save_memo_config()
            self.refresh_memo_board()

    def rename_memo_column(self, index):
        value, ok = QInputDialog.getText(
            self, "Название столбца", "Новое название:",
            text=self.memo_columns[index]["name"]
        )
        value = value.strip()
        if ok and value:
            self.memo_columns[index]["name"] = value
            sections = self.memo_columns[index].get("sections", [])
            if sections:
                sections[0]["name"] = value
            self.save_memo_config()
            self.refresh_memo_board()

    def delete_memo_column(self, index):
        if len(self.memo_columns) <= 1:
            return
        count = sum(
            len(s.get("articles", []))
            for s in self.memo_columns[index].get("sections", [])
        )
        if count and self.app_settings.get("confirm_delete_column", True):
            answer = QMessageBox.question(
                self, "Удалить столбец",
                f"В столбце находится статей: {count}. Удалить?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.memo_columns.pop(index)
        self.save_memo_config()
        self.refresh_memo_board()

    def memo_item_context_menu(self, column_index, section_index, list_widget, pos):
        item = list_widget.itemAt(pos)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(list_widget)
        open_action = menu.addAction("Открыть")
        move_menu = menu.addMenu("Переместить в")
        actions = {}
        for ci, column in enumerate(self.memo_columns):
            for si, section in enumerate(column.get("sections", [])):
                if (ci, si) == (column_index, section_index):
                    continue
                action = move_menu.addAction(f"{column['name']} → {section['name']}")
                actions[action] = (ci, si)
        menu.addSeparator()
        remove_action = menu.addAction("Удалить")
        chosen = menu.exec(list_widget.mapToGlobal(pos))
        if chosen == open_action:
            self.open_memo_item(column_index, item)
        elif chosen == remove_action:
            self.remove_memo_item(column_index, section_index, data["article"])
        elif chosen in actions:
            self.move_memo_item(
                column_index, section_index, data["article"], *actions[chosen]
            )

    def move_memo_item(self, sc, ss, ai, tc, ts):
        ref = self.memo_columns[sc]["sections"][ss]["articles"].pop(ai)
        target = self.memo_columns[tc]["sections"][ts].setdefault("articles", [])
        if ref not in target:
            target.append(ref)
        self.save_memo_config()
        self.refresh_memo_board()

    def remove_memo_item(self, column_index, section_index, article_index):
        articles = self.memo_columns[column_index]["sections"][section_index]["articles"]
        if 0 <= article_index < len(articles):
            articles.pop(article_index)
            self.save_memo_config()
            self.refresh_memo_board()

    def open_memo_item(self, column_index, item):
        if not self.app_settings.get("double_click_opens_article", True):
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        ref = data.get("ref", {})
        article = self.find_exact_article(
            ref.get("article_number", ""),
            ref.get("law_title", ""),
        )
        if not article:
            self.memo_content.setPlainText("Статья не найдена в локальной базе.")
            return

        short = self.memo_law_short_name(article["law_title"])
        penalty = (self.extract_article_penalty(article["content"]) if self.app_settings.get("show_penalties", True) else "")
        output = (
            f"{article['article_number']} {short}\n"
            f"{self.memo_summary(article)}\n\n"
            f"{article['law_title']}\n\n"
            f"{article['content']}"
        )
        if penalty:
            output += f"\n\n⚖ НАКАЗАНИЕ\n{penalty}"
        self.memo_content.setPlainText(output)

    def hide_memo_overlay(self):
        if self.memo_overlay is not None:
            self.memo_overlay.hide()

    def show_memo_overlay(self, auto_fit=False):
        if self.memo_overlay is None:
            self.memo_overlay = QDialog(None)
            self.memo_overlay.setObjectName("memoOverlayWindow")
            self.memo_overlay.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground,
                True,
            )
            self.memo_overlay.setWindowTitle("DeiLaw — RP Quick Memo")
            self.memo_overlay.installEventFilter(self)
            self.memo_overlay.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.memo_overlay.resize(
                int(self.app_settings.get("overlay_width", 1250)),
                int(self.app_settings.get("overlay_height", 650)),
            )
            self.memo_overlay.setWindowOpacity(1.0)
            self.apply_overlay_background_opacity()
            self.memo_overlay.setMinimumSize(760, 420)
            self.memo_overlay.installEventFilter(self)
            flags = (
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
            )
            if self.app_settings.get("memo_always_on_top", True):
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.memo_overlay.setWindowFlags(flags)
            self.memo_overlay.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground, True
            )

            layout = QVBoxLayout(self.memo_overlay)
            top = QHBoxLayout()
            title = QLabel("RP Quick Memo")
            title.setObjectName("pageTitle")
            close = QPushButton("Скрыть")
            close.clicked.connect(self.memo_overlay.hide)
            top.addWidget(title)
            top.addStretch()
            top.addWidget(close)

            self.memo_overlay_scroll = QScrollArea()
            self.memo_overlay_scroll.setObjectName("memoOverlayScroll")
            self.memo_overlay_scroll.setAutoFillBackground(False)
            self.memo_overlay_scroll.viewport().setAutoFillBackground(False)
            self.memo_overlay_scroll.setWidgetResizable(True)
            self.memo_overlay_board = QWidget()
            self.memo_overlay_board.setObjectName("memoOverlayBoard")
            self.memo_overlay_board.setAutoFillBackground(False)
            self.memo_overlay_layout = QHBoxLayout(self.memo_overlay_board)
            self.memo_overlay_layout.setSpacing(12)
            self.memo_overlay_scroll.setWidget(self.memo_overlay_board)

            layout.addLayout(top)
            layout.addWidget(self.memo_overlay_scroll, stretch=1)

            if self.app_settings.get("remember_memo_layout", True):
                geometry = self.app_settings.get("overlay_geometry", "")
                if geometry:
                    try:
                        self.memo_overlay.restoreGeometry(
                            QByteArray.fromBase64(geometry.encode("ascii"))
                        )
                    except Exception:
                        pass

        self.build_memo_overlay()

        # Use the configured "Окно по бинду" size. If the user previously
        # resized/moved the memo manually and layout remembering is enabled,
        # the saved geometry is already restored above. Otherwise use the
        # configured width/height and center it on the active monitor.
        if not (
            self.app_settings.get("remember_memo_layout", True)
            and self.app_settings.get("overlay_geometry", "")
        ):
            self.position_memo_overlay_from_settings()

        self.memo_overlay.show()
        self.memo_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self.apply_overlay_background_opacity()
        QTimer.singleShot(0, self.apply_overlay_background_opacity)
        QTimer.singleShot(30, self.apply_overlay_background_opacity)
        self.apply_overlay_click_through()
        self.memo_overlay.raise_()

    def position_memo_overlay_from_settings(self):
        """Apply configured Quick-window size and center F8 on active monitor."""
        if self.memo_overlay is None:
            return

        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            try:
                screen = self.screen()
            except Exception:
                screen = None
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        area = screen.availableGeometry()

        requested_width = int(
            self.app_settings.get("overlay_width", 1250)
        )
        requested_height = int(
            self.app_settings.get("overlay_height", 650)
        )

        width = min(
            max(760, requested_width),
            max(760, area.width() - 40),
        )
        height = min(
            max(420, requested_height),
            max(420, area.height() - 40),
        )

        self.memo_overlay.setWindowState(
            Qt.WindowState.WindowNoState
        )
        self.memo_overlay.resize(width, height)
        self.memo_overlay.move(
            area.x() + max(0, (area.width() - width) // 2),
            area.y() + max(0, (area.height() - height) // 2),
        )

        QTimer.singleShot(0, self.update_overlay_card_widths)

    def create_overlay_article_card(self, article):
        """Adaptive card for the hotkey overlay."""
        short = self.memo_law_short_name(article["law_title"])
        description = self.memo_card_description(article)
        penalty = (
            self.extract_article_penalty(article["content"])
            if self.app_settings.get("show_penalties", True) and short != "ПДД"
            else ""
        )

        parts = []
        if self.app_settings.get("show_article_code", True):
            parts.append(f"{article['article_number']} {short}")
        if self.app_settings.get("show_article_summary", True) and description:
            parts.append(description)
        if penalty:
            parts.append(f"⚖ Наказание: {penalty}")

        if not parts:
            parts.append(f"{article['article_number']}")

        card = QLabel("\n".join(parts))
        card.setObjectName("memoOverlayArticleCard")
        card.setWordWrap(True)
        card.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        card.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum
        )
        card.setMinimumWidth(0)
        card.setMinimumHeight(
            int(self.app_settings.get("memo_card_min_height", 72))
        )
        card.setMargin(10)
        card.setToolTip(article["content"])
        font = card.font()
        font.setPointSize(
            int(self.app_settings.get("memo_card_font_size", 14))
        )
        card.setFont(font)
        return card

    def build_memo_overlay(self):
        if self.memo_overlay is None:
            return
        self.clear_layout(self.memo_overlay_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        for column in self.memo_columns:
            frame = QFrame()
            frame.setObjectName("card")
            frame.setMinimumWidth(180)
            frame.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding
            )
            outer = QVBoxLayout(frame)
            title = QLabel(column["name"])
            title.setObjectName("sectionTitle")
            outer.addWidget(title)

            vertical = QSplitter(Qt.Orientation.Vertical)
            vertical.setObjectName(f"overlaySectionSplitter_{splitter.count()}")
            vertical.setChildrenCollapsible(False)
            vertical.setHandleWidth(7)

            for section_index, section in enumerate(column.get("sections", [])):
                sec = QFrame()
                lay = QVBoxLayout(sec)
                if section_index > 0:
                    sec_title = QLabel(section.get("name") or "Раздел")
                    sec_title.setStyleSheet("font-weight: 700;")
                    lay.addWidget(sec_title)

                for ref in section.get("articles", []):
                    article = self.find_exact_article(
                        ref.get("article_number", ""), ref.get("law_title", "")
                    )
                    if not article:
                        continue
                    card = self.create_overlay_article_card(article)
                    lay.addWidget(card)
                lay.addStretch()
                vertical.addWidget(sec)

            outer.addWidget(vertical, stretch=1)
            splitter.addWidget(frame)

        self.memo_overlay_layout.addWidget(splitter)

        count = max(1, splitter.count())
        available = max(600, self.memo_overlay.width() - 50)

        restored = False
        if self.app_settings.get("remember_memo_layout", True):
            saved = self.app_settings.get("overlay_column_sizes", [])
            if isinstance(saved, list) and len(saved) == splitter.count():
                splitter.setSizes(saved)
                restored = True

        if not restored:
            splitter.setSizes([max(180, available // count)] * count)

        splitter.setObjectName("overlayColumnSplitter")
        splitter.splitterMoved.connect(self.save_overlay_layout_state)

        # New frames/cards are created above, so apply their alpha now.
        QTimer.singleShot(0, self.apply_overlay_background_opacity)

        if self.app_settings.get("remember_memo_layout", True):
            section_sizes = self.app_settings.get("overlay_section_sizes", {})
            for i in range(splitter.count()):
                frame = splitter.widget(i)
                if frame is None:
                    continue
                vertical = frame.findChild(
                    QSplitter, f"overlaySectionSplitter_{i}"
                )
                sizes = section_sizes.get(str(i), [])
                if vertical is not None and isinstance(sizes, list) and len(sizes) == vertical.count():
                    vertical.setSizes(sizes)
                if vertical is not None:
                    vertical.splitterMoved.connect(
                        self.save_overlay_layout_state
                    )

        self.update_overlay_card_widths()
        self.apply_overlay_background_opacity()
        self.refresh_button_sounds()


    def refresh_memo_overlay_if_open(self):
        if self.memo_overlay is not None and self.memo_overlay.isVisible():
            self.build_memo_overlay()

    def save_memo_layout_state(self, *args):
        if not self.app_settings.get("remember_memo_layout", True):
            return

        if hasattr(self, "memo_main_splitter"):
            self.app_settings["memo_main_sizes"] = self.memo_main_splitter.sizes()

        if hasattr(self, "memo_splitter"):
            self.app_settings["memo_column_sizes"] = self.memo_splitter.sizes()
            section_sizes = {}
            for i in range(self.memo_splitter.count()):
                frame = self.memo_splitter.widget(i)
                if frame is None:
                    continue
                vertical = frame.findChild(
                    QSplitter, f"memoSectionSplitter_{i}"
                )
                if vertical is not None:
                    section_sizes[str(i)] = vertical.sizes()
            self.app_settings["memo_section_sizes"] = section_sizes

        self.save_app_settings()

    def save_overlay_layout_state(self, *args):
        if (
            not self.app_settings.get("remember_memo_layout", True)
            or self.memo_overlay is None
        ):
            return

        geometry = bytes(self.memo_overlay.saveGeometry().toBase64()).decode("ascii")
        self.app_settings["overlay_geometry"] = geometry

        splitter = self.memo_overlay.findChild(
            QSplitter, "overlayColumnSplitter"
        )
        if splitter is not None:
            self.app_settings["overlay_column_sizes"] = splitter.sizes()
            section_sizes = {}
            for i in range(splitter.count()):
                frame = splitter.widget(i)
                if frame is None:
                    continue
                vertical = frame.findChild(
                    QSplitter, f"overlaySectionSplitter_{i}"
                )
                if vertical is not None:
                    section_sizes[str(i)] = vertical.sizes()
            self.app_settings["overlay_section_sizes"] = section_sizes

        self.save_app_settings()

    def eventFilter(self, obj, event):
        if hasattr(self, "rp_input") and obj is self.rp_input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self.analyze_rp_with_ai()
                    return True

        if self.memo_overlay is not None and obj is self.memo_overlay:
            if event.type() == QEvent.Type.MouseButtonPress:
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and not self.app_settings.get("overlay_click_through", False)
                ):
                    self.memo_drag_position = (
                        event.globalPosition().toPoint()
                        - self.memo_overlay.frameGeometry().topLeft()
                    )
            elif event.type() == QEvent.Type.MouseMove:
                if (
                    self.memo_drag_position is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                    and not self.app_settings.get("overlay_click_through", False)
                ):
                    self.memo_overlay.move(
                        event.globalPosition().toPoint()
                        - self.memo_drag_position
                    )
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.memo_drag_position = None

        if self.memo_overlay is not None and obj is self.memo_overlay:
            if event.type() == QEvent.Type.Resize:
                self.update_overlay_card_widths()
                self.save_overlay_layout_state()
            elif event.type() == QEvent.Type.Move:
                self.save_overlay_layout_state()

        if self.search_overlay is not None and obj is self.search_overlay:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.search_overlay_drag_position = (
                        event.globalPosition().toPoint()
                        - self.search_overlay.frameGeometry().topLeft()
                    )
            elif event.type() == QEvent.Type.MouseMove:
                if (
                    self.search_overlay_drag_position is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                ):
                    self.search_overlay.move(
                        event.globalPosition().toPoint()
                        - self.search_overlay_drag_position
                    )
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.search_overlay_drag_position = None
            elif event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
                self.save_search_overlay_geometry()

        if (
            self.calculator_overlay is not None
            and obj is self.calculator_overlay
        ):
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.calculator_overlay_drag_position = (
                        event.globalPosition().toPoint()
                        - self.calculator_overlay.frameGeometry().topLeft()
                    )
            elif event.type() == QEvent.Type.MouseMove:
                if (
                    self.calculator_overlay_drag_position is not None
                    and event.buttons() & Qt.MouseButton.LeftButton
                ):
                    self.calculator_overlay.move(
                        event.globalPosition().toPoint()
                        - self.calculator_overlay_drag_position
                    )
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.calculator_overlay_drag_position = None
            elif event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
                self.save_calculator_overlay_geometry()

        return super().eventFilter(obj, event)

    def update_overlay_card_widths(self):
        """Пересчитать перенос текста карточек при изменении размеров overlay."""
        if self.memo_overlay is None:
            return

        for card in self.memo_overlay.findChildren(
            QLabel, "memoOverlayArticleCard"
        ):
            parent = card.parentWidget()
            if parent is None:
                continue

            available = max(120, parent.contentsRect().width() - 24)
            card.setMaximumWidth(available)
            card.setMinimumWidth(0)

            # Для wordWrap QLabel высота зависит от доступной ширины.
            card.adjustSize()
            card.updateGeometry()

        if hasattr(self, "memo_overlay_board"):
            self.memo_overlay_board.updateGeometry()

    # =========================================================
    # COMMUNITY / REVIEWS / BUG REPORTS
    # =========================================================

    def _run_community_task(
        self,
        callback,
        *,
        args=(),
        kwargs=None,
        on_success=None,
        on_error=None,
    ):
        worker = CommunityTaskWorker(
            callback,
            *tuple(args),
            parent=self,
            **dict(kwargs or {}),
        )
        self.community_workers.append(worker)

        if on_success is not None:
            worker.completed.connect(on_success)
        if on_error is not None:
            worker.failed.connect(on_error)

        def cleanup():
            try:
                self.community_workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()

        worker.finished.connect(cleanup)
        worker.start()
        return worker

    @staticmethod
    def _community_date(value):
        """Display Supabase timestamps in Moscow time (MSK, UTC+3)."""
        text = str(value or "").strip()
        if not text:
            return "—"
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            msk = timezone(timedelta(hours=3), name="MSK")
            return dt.astimezone(msk).strftime("%d.%m.%Y %H:%M МСК")
        except Exception:
            return text[:16]

    @staticmethod
    def _stars_text(rating):
        try:
            value = max(1, min(5, int(rating)))
        except Exception:
            value = 1
        return "★" * value + "☆" * (5 - value)

    @staticmethod
    def _review_public_id(review):
        """Stable short public tag derived only from the review row UUID."""
        raw = "".join(
            ch for ch in str((review or {}).get("id") or "")
            if ch.isalnum()
        )
        return raw[-6:].upper() if raw else "------"

    def create_community_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()

        title = QLabel("Отзывы DeiLaw")
        title.setObjectName("pageTitle")
        description = QLabel(
            "Публичные отзывы пользователей о DeiLaw, общая оценка программы "
            "и возможность оставить собственный отзыв."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)

        title_box.addWidget(title)
        title_box.addWidget(description)
        header.addLayout(title_box, stretch=1)

        self.community_refresh_button = QPushButton("↻ Обновить")
        self.community_refresh_button.clicked.connect(
            self.refresh_community_reviews
        )
        header.addWidget(
            self.community_refresh_button,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        layout.addLayout(header)

        summary_card = QFrame()
        summary_card.setObjectName("card")
        summary_layout = QHBoxLayout(summary_card)
        summary_layout.setContentsMargins(18, 14, 18, 14)
        summary_layout.setSpacing(18)

        self.community_rating_label = QLabel("☆☆☆☆☆  — / 5")
        self.community_rating_label.setObjectName("sectionTitle")

        self.community_count_label = QLabel("Отзывов пока нет")
        self.community_count_label.setObjectName("muted")

        summary_text = QVBoxLayout()
        summary_text.addWidget(self.community_rating_label)
        summary_text.addWidget(self.community_count_label)
        summary_layout.addLayout(summary_text, stretch=1)

        self.community_review_button = QPushButton("⭐ Оставить отзыв")
        self.community_review_button.setObjectName("primary")
        self.community_review_button.clicked.connect(
            self.show_review_dialog
        )

        self.community_suggestion_button = QPushButton("💡 Предложить идею")
        self.community_suggestion_button.clicked.connect(
            self.show_suggestion_dialog
        )

        self.community_my_suggestions_button = QPushButton("📋 Мои предложения")
        self.community_my_suggestions_button.clicked.connect(
            self.show_my_suggestions
        )

        summary_layout.addWidget(self.community_review_button)
        summary_layout.addWidget(self.community_suggestion_button)
        summary_layout.addWidget(self.community_my_suggestions_button)
        layout.addWidget(summary_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        left = QFrame()
        left.setObjectName("card")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 14)

        reviews_title = QLabel("Отзывы пользователей")
        reviews_title.setObjectName("sectionTitle")
        left_layout.addWidget(reviews_title)

        self.community_reviews_list = QListWidget()
        self.community_reviews_list.setWordWrap(True)
        self.community_reviews_list.setSpacing(4)
        self.community_reviews_list.currentRowChanged.connect(
            self.show_community_review
        )
        left_layout.addWidget(self.community_reviews_list, stretch=1)

        right = QFrame()
        right.setObjectName("card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)

        detail_title = QLabel("Отзыв")
        detail_title.setObjectName("sectionTitle")
        right_layout.addWidget(detail_title)

        self.community_review_details = QTextBrowser()
        self.community_review_details.setPlainText(
            "Выберите отзыв слева."
        )
        right_layout.addWidget(
            self.community_review_details,
            stretch=1,
        )

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([430, 760])
        layout.addWidget(splitter, stretch=1)

        self.community_status_label = QLabel(
            "Отзывы загружаются с сервера DeiLaw."
        )
        self.community_status_label.setObjectName("muted")
        self.community_status_label.setWordWrap(True)
        layout.addWidget(self.community_status_label)

        QTimer.singleShot(1200, self.refresh_community_reviews)
        return page

    def refresh_community_reviews(self):
        if not hasattr(self, "community_reviews_list"):
            return

        self.community_status_label.setText(
            "Загружаю отзывы…"
        )
        self.community_refresh_button.setEnabled(False)

        def loaded(rows):
            self.community_refresh_button.setEnabled(True)
            self.community_reviews = list(rows or [])
            self.community_reviews_list.clear()
            self.community_review_details.setPlainText(
                "Выберите отзыв слева."
            )

            ratings = []
            for row in self.community_reviews:
                try:
                    rating = int(row.get("rating") or 0)
                except Exception:
                    rating = 0
                if 1 <= rating <= 5:
                    ratings.append(rating)

                author = str(
                    row.get("author_name") or "Пользователь"
                ).strip()
                version = str(
                    row.get("app_version") or ""
                ).strip()
                review = str(
                    row.get("review_text") or ""
                ).strip()
                first_line = review.replace("\n", " ")
                if len(first_line) > 85:
                    first_line = first_line[:82] + "…"

                public_id = self._review_public_id(row)
                reply_mark = "\n💬 Есть ответ разработчика" if str(
                    row.get("developer_reply") or ""
                ).strip() else ""
                item = QListWidgetItem(
                    f"{self._stars_text(rating)}  {author} #{public_id}\n"
                    f"{first_line}"
                    + (f"\nDeiLaw {version}" if version else "")
                    + reply_mark
                )
                self.community_reviews_list.addItem(item)

            if ratings:
                average = sum(ratings) / len(ratings)
                rounded = max(1, min(5, round(average)))
                self.community_rating_label.setText(
                    f"{self._stars_text(rounded)}  {average:.1f} / 5"
                )
                self.community_count_label.setText(
                    f"Публичных отзывов: {len(ratings)}"
                )
            else:
                self.community_rating_label.setText(
                    "☆☆☆☆☆  — / 5"
                )
                self.community_count_label.setText(
                    "Отзывов пока нет"
                )

            if self.community_reviews:
                self.community_reviews_list.setCurrentRow(0)
                self.community_status_label.setText(
                    "Отзывы доступны всем пользователям DeiLaw."
                )
            else:
                self.community_status_label.setText(
                    "Пока никто не оставил отзыв. Можно стать первым."
                )

        def failed(message):
            self.community_refresh_button.setEnabled(True)
            self.community_status_label.setText(
                f"Не удалось загрузить отзывы: {message}"
            )

        self._run_community_task(
            self.community_client.fetch_reviews,
            on_success=loaded,
            on_error=failed,
        )

    def show_community_review(self, row):
        if (
            row < 0
            or row >= len(getattr(self, "community_reviews", []))
            or not hasattr(self, "community_review_details")
        ):
            return

        item = self.community_reviews[row]
        author = str(item.get("author_name") or "Пользователь")
        review = str(item.get("review_text") or "")
        version = str(item.get("app_version") or "—")
        rating = item.get("rating") or 0
        created = self._community_date(item.get("created_at"))

        public_id = self._review_public_id(item)
        reply = str(item.get("developer_reply") or "").strip()
        reply_at = self._community_date(item.get("developer_reply_at"))
        details = (
            f"{self._stars_text(rating)}\n\n"
            f"{author} #{public_id}\n"
            f"DeiLaw {version} • {created}\n\n"
            f"{review}"
        )
        if reply:
            details += (
                "\n\n━━━━━━━━━━━━━━━━━━━━\n"
                "💬 Ответ разработчика"
                + (f" • {reply_at}" if reply_at != "—" else "")
                + f"\n\n{reply}"
            )
        self.community_review_details.setPlainText(details)

    def show_review_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Оставить отзыв — DeiLaw")
        dialog.resize(620, 470)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        title = QLabel("⭐ Оставить отзыв о DeiLaw")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Оценка и текст будут публично видны другим пользователям. "
            "Имя не обязано быть уникальным: рядом с ним DeiLaw покажет "
            "короткий публичный ID отзыва. На одном Windows-компьютере "
            "хранится один отзыв — повторная отправка обновляет предыдущий. "
            "Для привязки используется анонимный хеш устройства; IP и "
            "MAC-адрес не отправляются."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        author = QLineEdit()
        author.setPlaceholderText("Ваш ник")
        author.setMaxLength(40)
        author.setText(
            str(self.app_settings.get("community_review_author", "") or "")
        )
        layout.addWidget(author)

        rating_state = {"value": 0}
        star_buttons = []
        stars_row = QHBoxLayout()
        stars_row.addWidget(QLabel("Оценка:"))

        def paint_stars():
            current = rating_state["value"]
            for index, button in enumerate(star_buttons, start=1):
                button.setText("★" if index <= current else "☆")
                button.setToolTip(f"{index} из 5")

        for value in range(1, 6):
            button = QPushButton("☆")
            button.setFixedSize(46, 40)
            button.setToolTip(f"{value} из 5")
            button.clicked.connect(
                lambda checked=False, score=value: (
                    rating_state.__setitem__("value", score),
                    paint_stars(),
                )
            )
            star_buttons.append(button)
            stars_row.addWidget(button)

        stars_row.addStretch()
        layout.addLayout(stars_row)

        review = QTextEdit()
        review.setPlaceholderText(
            "Что понравилось? Что стоит улучшить?"
        )
        review.setMaximumHeight(180)
        layout.addWidget(review)

        status = QLabel("")
        status.setObjectName("muted")
        status.setWordWrap(True)
        layout.addWidget(status)

        buttons = QHBoxLayout()
        cancel = QPushButton("Отмена")
        submit = QPushButton("Опубликовать отзыв")
        submit.setObjectName("primary")
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(submit)
        layout.addLayout(buttons)

        cancel.clicked.connect(dialog.reject)

        def send_review():
            name = " ".join(author.text().split()).strip()
            body = review.toPlainText().strip()
            score = rating_state["value"]

            if not name:
                status.setText("Укажите ник.")
                return
            if not 1 <= score <= 5:
                status.setText("Выберите оценку от 1 до 5 звёзд.")
                return
            if len(body) < 3:
                status.setText("Напишите короткий отзыв.")
                return

            submit.setEnabled(False)
            cancel.setEnabled(False)
            status.setText("Публикую отзыв…")

            def sent(_result):
                self.app_settings["community_review_author"] = name
                self.save_app_settings()
                self.play_ui_sound("success")
                self.show_save_toast("Отзыв опубликован")
                dialog.accept()
                self.refresh_community_reviews()

            def failed(message):
                submit.setEnabled(True)
                cancel.setEnabled(True)
                status.setText(
                    f"Не удалось опубликовать отзыв: {message}"
                )

            self._run_community_task(
                self.community_client.submit_review,
                kwargs={
                    "author_name": name,
                    "rating": score,
                    "review_text": body,
                    "app_version": APP_VERSION,
                },
                on_success=sent,
                on_error=failed,
            )

        submit.clicked.connect(send_review)
        dialog.exec()

    @staticmethod
    def _suggestion_status_text(value):
        return {
            "new": "Новое",
            "reviewing": "Рассматривается",
            "planned": "Запланировано",
            "implemented": "Реализовано",
            "rejected": "Отклонено",
        }.get(str(value or "new"), str(value or "—"))

    def show_suggestion_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Предложить идею — DeiLaw")
        dialog.resize(680, 560)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        title_label = QLabel("💡 Предложить идею для DeiLaw")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        hint = QLabel(
            "Предложение увидит разработчик DeiLaw. После отправки его статус "
            "и ответ разработчика можно посмотреть в разделе «Мои предложения»."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        author = QLineEdit()
        author.setPlaceholderText("Ваш ник")
        author.setMaxLength(40)
        author.setText(
            str(self.app_settings.get("community_review_author", "") or "")
        )
        layout.addWidget(author)

        category = QComboBox()
        category.addItems([
            "RP-функционал",
            "Функционал",
            "Интерфейс",
            "AI-помощник",
            "Законы и поиск",
            "Quick-окна",
            "Другое",
        ])
        layout.addWidget(category)

        suggestion_title = QLineEdit()
        suggestion_title.setPlaceholderText("Короткое название идеи")
        suggestion_title.setMaxLength(150)
        layout.addWidget(suggestion_title)

        body = QTextEdit()
        body.setPlaceholderText(
            "Опишите идею: что добавить, как это должно работать и чем это поможет в RP."
        )
        body.setMinimumHeight(190)
        layout.addWidget(body, 1)

        status = QLabel("")
        status.setObjectName("muted")
        status.setWordWrap(True)
        layout.addWidget(status)

        buttons = QHBoxLayout()
        cancel = QPushButton("Отмена")
        submit = QPushButton("Отправить предложение")
        submit.setObjectName("primary")
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(submit)
        layout.addLayout(buttons)

        cancel.clicked.connect(dialog.reject)

        def send():
            name = " ".join(author.text().split()).strip()
            title_value = " ".join(suggestion_title.text().split()).strip()
            text_value = body.toPlainText().strip()
            if not name:
                status.setText("Укажите ник.")
                return
            if len(title_value) < 3:
                status.setText("Название идеи должно быть не короче 3 символов.")
                return
            if len(text_value) < 5:
                status.setText("Опишите предложение немного подробнее.")
                return

            submit.setEnabled(False)
            cancel.setEnabled(False)
            status.setText("Отправляю предложение…")

            def sent(_result):
                self.app_settings["community_review_author"] = name
                self.save_app_settings()
                self.play_ui_sound("success")
                self.show_save_toast("Предложение отправлено")
                dialog.accept()

            def failed(message):
                submit.setEnabled(True)
                cancel.setEnabled(True)
                status.setText(f"Не удалось отправить предложение: {message}")

            self._run_community_task(
                self.community_client.submit_suggestion,
                kwargs={
                    "author_name": name,
                    "category": category.currentText(),
                    "title": title_value,
                    "suggestion_text": text_value,
                    "app_version": APP_VERSION,
                },
                on_success=sent,
                on_error=failed,
            )

        submit.clicked.connect(send)
        dialog.exec()

    def show_my_suggestions(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Мои предложения — DeiLaw")
        dialog.resize(900, 600)

        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("📋 Мои предложения")
        title.setObjectName("pageTitle")
        refresh = QPushButton("↻ Обновить")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(refresh)
        outer.addLayout(head)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        suggestions_list = QListWidget()
        suggestions_list.setWordWrap(True)
        suggestions_list.setSpacing(4)
        details = QTextBrowser()
        details.setPlainText("Выберите предложение слева.")
        splitter.addWidget(suggestions_list)
        splitter.addWidget(details)
        splitter.setSizes([350, 550])
        outer.addWidget(splitter, 1)

        status_label = QLabel("Загружаю предложения…")
        status_label.setObjectName("muted")
        outer.addWidget(status_label)

        state = {"rows": []}

        def show_row(row_index):
            rows = state["rows"]
            if row_index < 0 or row_index >= len(rows):
                details.setPlainText("Выберите предложение слева.")
                return
            item = rows[row_index]
            number = item.get("suggestion_number") or "—"
            created = self._community_date(item.get("created_at"))
            updated = self._community_date(item.get("updated_at"))
            reply = str(item.get("developer_reply") or "").strip()
            reply_at = self._community_date(item.get("developer_reply_at"))
            text = (
                f"Предложение #{number}\\n"
                f"{item.get('title') or 'Без названия'}\\n\\n"
                f"Категория: {item.get('category') or '—'}\\n"
                f"Статус: {self._suggestion_status_text(item.get('status'))}\\n"
                f"Создано: {created}\\n"
                f"Обновлено: {updated}\\n\\n"
                f"{item.get('suggestion_text') or ''}"
            )
            if reply:
                text += (
                    "\\n\\n━━━━━━━━━━━━━━━━━━━━\\n"
                    "💬 Ответ разработчика"
                    + (f" • {reply_at}" if reply_at != "—" else "")
                    + f"\\n\\n{reply}"
                )
            details.setPlainText(text)

        suggestions_list.currentRowChanged.connect(show_row)

        def load():
            refresh.setEnabled(False)
            status_label.setText("Загружаю предложения…")

            def loaded(rows):
                refresh.setEnabled(True)
                state["rows"] = list(rows or [])
                suggestions_list.clear()
                for item in state["rows"]:
                    number = item.get("suggestion_number") or "—"
                    title_value = str(item.get("title") or "Без названия")
                    status_text = self._suggestion_status_text(item.get("status"))
                    reply_mark = " • 💬" if str(item.get("developer_reply") or "").strip() else ""
                    suggestions_list.addItem(
                        f"#{number} • {status_text}{reply_mark}\\n{title_value}"
                    )
                if state["rows"]:
                    suggestions_list.setCurrentRow(0)
                    status_label.setText(
                        f"Ваших предложений: {len(state['rows'])}"
                    )
                else:
                    details.setPlainText("Вы ещё не отправляли предложений.")
                    status_label.setText("Предложений пока нет.")

            def failed(message):
                refresh.setEnabled(True)
                status_label.setText(f"Не удалось загрузить предложения: {message}")

            self._run_community_task(
                self.community_client.fetch_my_suggestions,
                on_success=loaded,
                on_error=failed,
            )

        refresh.clicked.connect(load)
        QTimer.singleShot(100, load)
        dialog.exec()

    def _bug_report_payload(
        self,
        *,
        category,
        title,
        description,
        reproduce_steps,
        expected_result,
        include_logs=True,
    ):
        channel = str(
            self.app_settings.get("update_channel", "stable")
        )
        theme = (
            f"{self.app_settings.get('theme', 'dark')} / "
            f"{self.app_settings.get('visual_theme', 'default')}"
        )

        ai_line = "Cloud AI: Supabase Edge Function / OpenAI • локальные модели не используются"

        return {
            "category": category,
            "title": title,
            "description": description,
            "reproduce_steps": reproduce_steps,
            "expected_result": expected_result,
            "app_version": APP_VERSION,
            "windows_version": platform.platform(),
            "theme": theme,
            "hotkey_search": str(
                self.app_settings.get("search_hotkey", "F7")
            ),
            "hotkey_memo": str(
                self.app_settings.get("memo_hotkey", "F8")
            ),
            "hotkey_calculator": str(
                self.app_settings.get("calculator_hotkey", "F9")
            ),
            "update_channel": channel,
            "ai_status": ai_line,
            "logs": self._recent_log_tail(100) if include_logs else "",
        }

    def show_my_bug_reports(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Репорты — DeiLaw")
        dialog.resize(1080, 720)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()

        title_box = QVBoxLayout()
        title = QLabel("🐞 Репорты")
        title.setObjectName("pageTitle")
        title_box.addWidget(title)

        hint = QLabel(
            "Создавайте новые обращения и продолжайте диалог с разработчиком в одном окне. "
            "Статус и новые сообщения обновляются автоматически каждые 2 секунды."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        title_box.addWidget(hint)

        header.addLayout(title_box, stretch=1)

        new_report_button = QPushButton("＋ Новый репорт")
        new_report_button.setObjectName("primary")
        new_report_button.setToolTip("Сообщить разработчику о новой проблеме")
        header.addWidget(
            new_report_button,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        live_badge = QLabel("● LIVE")
        live_badge.setObjectName("sectionTitle")
        live_badge.setToolTip(
            "Список репортов и чат синхронизируются автоматически"
        )
        header.addWidget(
            live_badge,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        # -------------------------------------------------------
        # Left: reports.
        # -------------------------------------------------------
        reports_card = QFrame()
        reports_card.setObjectName("card")
        reports_layout = QVBoxLayout(reports_card)
        reports_layout.setContentsMargins(12, 12, 12, 12)
        reports_layout.setSpacing(8)

        reports_title = QLabel("Ваши обращения")
        reports_title.setObjectName("sectionTitle")
        reports_layout.addWidget(reports_title)

        reports_list = QListWidget()
        reports_list.setWordWrap(True)
        reports_list.setSpacing(5)
        reports_layout.addWidget(reports_list, stretch=1)

        refresh = QPushButton("↻ Обновить сейчас")
        reports_layout.addWidget(refresh)

        # -------------------------------------------------------
        # Right: report header + real chat.
        # -------------------------------------------------------
        chat_card = QFrame()
        chat_card.setObjectName("card")
        chat_layout_outer = QVBoxLayout(chat_card)
        chat_layout_outer.setContentsMargins(14, 12, 14, 12)
        chat_layout_outer.setSpacing(9)

        report_header = QFrame()
        report_header.setObjectName("card")
        report_header_layout = QVBoxLayout(report_header)
        report_header_layout.setContentsMargins(12, 10, 12, 10)
        report_header_layout.setSpacing(5)

        report_title_label = QLabel("Выберите репорт")
        report_title_label.setObjectName("sectionTitle")
        report_title_label.setWordWrap(True)

        report_status_label = QLabel("")
        report_status_label.setObjectName("muted")
        report_status_label.setWordWrap(True)

        report_meta_label = QLabel("")
        report_meta_label.setObjectName("muted")
        report_meta_label.setWordWrap(True)

        report_header_layout.addWidget(report_title_label)
        report_header_layout.addWidget(report_status_label)
        report_header_layout.addWidget(report_meta_label)

        report_attachments_label = QLabel("📎 Вложения")
        report_attachments_label.setObjectName("muted")
        report_attachments_label.setVisible(False)
        report_header_layout.addWidget(report_attachments_label)

        report_attachments_list = QListWidget()
        report_attachments_list.setMaximumHeight(86)
        report_attachments_list.setVisible(False)
        report_header_layout.addWidget(report_attachments_list)

        download_attachment_button = QPushButton("Скачать выбранное вложение")
        download_attachment_button.setVisible(False)
        report_header_layout.addWidget(download_attachment_button, alignment=Qt.AlignmentFlag.AlignLeft)
        chat_layout_outer.addWidget(report_header)

        chat_scroll = QScrollArea()
        chat_scroll.setWidgetResizable(True)
        chat_scroll.setFrameShape(QFrame.Shape.NoFrame)

        chat_body = QWidget()
        chat_messages_layout = QVBoxLayout(chat_body)
        chat_messages_layout.setContentsMargins(8, 8, 8, 8)
        chat_messages_layout.setSpacing(9)
        chat_messages_layout.addStretch()

        chat_scroll.setWidget(chat_body)
        chat_layout_outer.addWidget(chat_scroll, stretch=1)

        composer_row = QHBoxLayout()
        composer = QTextEdit()
        composer.setPlaceholderText(
            "Напишите сообщение разработчику…"
        )
        composer.setMaximumHeight(82)
        composer.setEnabled(False)

        send_button = QPushButton("Отправить")
        send_button.setObjectName("primary")
        send_button.setMinimumWidth(125)
        send_button.setEnabled(False)

        composer_row.addWidget(composer, stretch=1)
        composer_row.addWidget(send_button)
        chat_layout_outer.addLayout(composer_row)

        splitter.addWidget(reports_card)
        splitter.addWidget(chat_card)
        splitter.setSizes([330, 750])
        layout.addWidget(splitter, stretch=1)

        bottom = QHBoxLayout()
        sync_status = QLabel("Подключение к системе репортов…")
        sync_status.setObjectName("muted")
        sync_status.setWordWrap(True)

        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)

        bottom.addWidget(sync_status, stretch=1)
        bottom.addWidget(close)
        layout.addLayout(bottom)

        data = {
            "rows": [],
            "selected_id": None,
            "messages": [],
            "reports_loading": False,
            "messages_loading": False,
            "report_signature": None,
            "message_signature": None,
            "attachments": [],
            "attachments_loading": False,
        }

        status_names = {
            "new": "🔴 Новый",
            "checking": "🟡 Проверяется",
            "fixed": "🔵 Исправлено",
            "closed": "🟢 Закрыт",
        }

        def find_selected_report():
            selected_id = str(
                data.get("selected_id") or ""
            )
            for item in data["rows"]:
                if str(item.get("id") or "") == selected_id:
                    return item
            return None

        def clear_chat_widgets():
            while chat_messages_layout.count():
                item = chat_messages_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        def add_chat_bubble(
            sender,
            message,
            created_at,
        ):
            sender = str(sender or "user")
            message = str(message or "").strip()
            if not message:
                return

            if sender == "system":
                event = QLabel(
                    f"• {message} •\n"
                    f"{self._community_date(created_at)}"
                )
                event.setObjectName("muted")
                event.setWordWrap(True)
                event.setAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                chat_messages_layout.addWidget(event)
                return

            wrapper = QWidget()
            wrapper_layout = QHBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)

            bubble = QFrame()
            bubble.setMaximumWidth(610)
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(12, 9, 12, 9)
            bubble_layout.setSpacing(4)

            is_user = sender == "user"
            sender_text = "Вы" if is_user else "Разработчик"

            sender_label = QLabel(sender_text)
            sender_label.setStyleSheet(
                "font-weight: 700;"
            )

            message_label = QLabel(message)
            message_label.setWordWrap(True)
            message_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )

            time_label = QLabel(
                self._community_date(created_at)
            )
            time_label.setStyleSheet(
                "font-size: 10px; opacity: 0.72;"
            )

            bubble_layout.addWidget(sender_label)
            bubble_layout.addWidget(message_label)
            bubble_layout.addWidget(time_label)

            light = (
                self.app_settings.get("theme", "dark")
                == "light"
            )
            if is_user:
                bubble.setStyleSheet(
                    "QFrame {"
                    "background-color: #2563eb;"
                    "color: white;"
                    "border-radius: 12px;"
                    "}"
                )
            else:
                if light:
                    bg = "#e9eef5"
                    fg = "#172033"
                    border = "#cbd5e1"
                else:
                    bg = "#252b35"
                    fg = "#f2f5f9"
                    border = "#3b4554"
                bubble.setStyleSheet(
                    "QFrame {"
                    f"background-color: {bg};"
                    f"color: {fg};"
                    f"border: 1px solid {border};"
                    "border-radius: 12px;"
                    "}"
                )

            if is_user:
                wrapper_layout.addStretch()
                wrapper_layout.addWidget(bubble)
            else:
                wrapper_layout.addWidget(bubble)
                wrapper_layout.addStretch()

            chat_messages_layout.addWidget(wrapper)

        def render_chat(report, messages):
            clear_chat_widgets()

            rows = list(messages or [])

            # Old reports may predate bug_report_messages. In that case the
            # original description is still shown as the first user message.
            if not rows:
                description = str(
                    report.get("description") or ""
                ).strip()
                if description:
                    rows.append({
                        "sender": "user",
                        "message": description,
                        "created_at": report.get("created_at"),
                    })

            # Legacy developer_reply remains supported. If it has not already
            # been converted into a message by the Supabase trigger, show it.
            legacy_reply = str(
                report.get("developer_reply") or ""
            ).strip()
            if legacy_reply:
                exists = any(
                    str(row.get("sender") or "") == "developer"
                    and str(row.get("message") or "").strip()
                    == legacy_reply
                    for row in rows
                )
                if not exists:
                    rows.append({
                        "sender": "developer",
                        "message": legacy_reply,
                        "created_at": report.get("updated_at"),
                    })

            if not rows:
                empty = QLabel(
                    "Сообщений пока нет."
                )
                empty.setObjectName("muted")
                empty.setAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                chat_messages_layout.addWidget(empty)
            else:
                for message in rows:
                    add_chat_bubble(
                        message.get("sender"),
                        message.get("message"),
                        message.get("created_at"),
                    )

            chat_messages_layout.addStretch()

            QTimer.singleShot(
                0,
                lambda: chat_scroll.verticalScrollBar().setValue(
                    chat_scroll.verticalScrollBar().maximum()
                ),
            )

        def update_report_header(report):
            if report is None:
                report_title_label.setText(
                    "Выберите репорт"
                )
                report_status_label.clear()
                report_meta_label.clear()
                composer.setEnabled(False)
                send_button.setEnabled(False)
                return

            report_number = (
                report.get("report_number") or "—"
            )
            report_status = str(
                report.get("status") or "new"
            )

            report_title_label.setText(
                f"#{report_number} • "
                f"{report.get('title') or 'Без названия'}"
            )
            report_status_label.setText(
                status_names.get(
                    report_status,
                    report_status,
                )
            )
            report_meta_label.setText(
                f"Категория: "
                f"{report.get('category') or '—'} • "
                f"DeiLaw "
                f"{report.get('app_version') or '—'} • "
                f"Создан: "
                f"{self._community_date(report.get('created_at'))}"
            )

            is_closed = report_status == "closed"
            composer.setEnabled(not is_closed)
            send_button.setEnabled(not is_closed)

            if is_closed:
                composer.setPlaceholderText(
                    "Репорт закрыт. Новые сообщения отключены."
                )
            else:
                composer.setPlaceholderText(
                    "Напишите сообщение разработчику…"
                )

        def render_attachments(rows):
            data["attachments"] = list(rows or [])
            report_attachments_list.clear()
            for item in data["attachments"]:
                size = int(item.get("size_bytes") or 0)
                size_text = f"{size / (1024 * 1024):.1f} МБ" if size >= 1024 * 1024 else f"{max(1, size // 1024)} КБ"
                list_item = QListWidgetItem(
                    f"{item.get('original_name') or 'Вложение'} • {size_text}"
                )
                list_item.setData(Qt.ItemDataRole.UserRole, dict(item))
                report_attachments_list.addItem(list_item)
            visible = bool(data["attachments"])
            report_attachments_label.setVisible(visible)
            report_attachments_list.setVisible(visible)
            download_attachment_button.setVisible(visible)

        def load_attachments(silent=False):
            report = find_selected_report()
            if report is None or data["attachments_loading"]:
                return
            report_id = str(report.get("id") or "").strip()
            if not report_id:
                return
            data["attachments_loading"] = True

            def loaded(rows):
                data["attachments_loading"] = False
                if str(data.get("selected_id") or "") != report_id:
                    return
                render_attachments(rows)

            def failed(message):
                data["attachments_loading"] = False
                if not silent:
                    sync_status.setText(f"Не удалось загрузить вложения: {message}")

            self._run_community_task(
                self.community_client.fetch_report_attachments,
                args=(report_id,),
                on_success=loaded,
                on_error=failed,
            )

        def download_selected_attachment():
            item = report_attachments_list.currentItem()
            if item is None:
                return
            meta = dict(item.data(Qt.ItemDataRole.UserRole) or {})
            attachment_id = str(meta.get("id") or "").strip()
            default_name = str(meta.get("original_name") or "attachment")
            if not attachment_id:
                return
            save_path, _ = QFileDialog.getSaveFileName(dialog, "Сохранить вложение", default_name)
            if not save_path:
                return
            download_attachment_button.setEnabled(False)

            def loaded(payload):
                download_attachment_button.setEnabled(True)
                try:
                    Path(save_path).write_bytes(bytes((payload or {}).get("data") or b""))
                    self.show_save_toast("Вложение сохранено")
                except Exception as exc:
                    QMessageBox.warning(self, "Вложение", str(exc))

            def failed(message):
                download_attachment_button.setEnabled(True)
                QMessageBox.warning(self, "Вложение", message)

            self._run_community_task(
                self.community_client.download_report_attachment,
                args=(attachment_id,),
                on_success=loaded,
                on_error=failed,
            )

        download_attachment_button.clicked.connect(download_selected_attachment)
        report_attachments_list.itemDoubleClicked.connect(lambda _item: download_selected_attachment())

        def load_messages(silent=False):
            report = find_selected_report()
            if (
                report is None
                or data["messages_loading"]
            ):
                return

            report_id = str(
                report.get("id") or ""
            ).strip()
            if not report_id:
                return

            data["messages_loading"] = True

            if not silent:
                sync_status.setText(
                    "Загружаю переписку…"
                )

            def loaded(rows):
                data["messages_loading"] = False

                # User may have selected another report while request was
                # running. Do not render messages into the wrong chat.
                if (
                    str(data.get("selected_id") or "")
                    != report_id
                ):
                    return

                rows = list(rows or [])
                if self.community_reply_monitor_initialized:
                    self._process_developer_reply_rows(
                        rows,
                        announce=True,
                    )
                signature = tuple(
                    (
                        str(item.get("id") or ""),
                        str(item.get("sender") or ""),
                        str(item.get("message") or ""),
                        str(item.get("created_at") or ""),
                    )
                    for item in rows
                )

                if (
                    signature != data["message_signature"]
                    or not silent
                ):
                    data["message_signature"] = signature
                    data["messages"] = rows
                    current = find_selected_report()
                    if current is not None:
                        render_chat(
                            current,
                            rows,
                        )

                live_badge.setText("● LIVE")
                sync_status.setText(
                    "● Синхронизация активна • "
                    "чат обновляется каждые 2 секунды"
                )

            def failed(message):
                data["messages_loading"] = False
                live_badge.setText("○ OFFLINE")
                sync_status.setText(
                    "Не удалось обновить переписку: "
                    f"{message}"
                )

            self._run_community_task(
                self.community_client.fetch_report_messages,
                args=(report_id,),
                on_success=loaded,
                on_error=failed,
            )

        def select_report(row):
            rows = data["rows"]
            if row < 0 or row >= len(rows):
                data["selected_id"] = None
                data["message_signature"] = None
                update_report_header(None)
                render_attachments([])
                clear_chat_widgets()
                empty = QLabel(
                    "Выберите репорт слева."
                )
                empty.setObjectName("muted")
                empty.setAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                chat_messages_layout.addWidget(empty)
                chat_messages_layout.addStretch()
                return

            report = rows[row]
            new_id = str(report.get("id") or "")
            changed = (
                new_id
                != str(data.get("selected_id") or "")
            )
            data["selected_id"] = new_id

            if changed:
                data["message_signature"] = None

            update_report_header(report)
            load_attachments(silent=False)
            load_messages(silent=False)

        reports_list.currentRowChanged.connect(
            select_report
        )

        def load_reports(silent=False):
            if data["reports_loading"]:
                return

            data["reports_loading"] = True
            previous_id = str(
                data.get("selected_id") or ""
            )

            if not silent:
                sync_status.setText(
                    "Загружаю репорты…"
                )
                refresh.setEnabled(False)

            def loaded(rows):
                data["reports_loading"] = False
                refresh.setEnabled(True)

                rows = list(rows or [])
                signature = tuple(
                    (
                        str(item.get("id") or ""),
                        str(item.get("status") or ""),
                        str(item.get("updated_at") or ""),
                        str(item.get("developer_reply") or ""),
                    )
                    for item in rows
                )

                data["rows"] = rows

                if (
                    signature != data["report_signature"]
                    or not silent
                ):
                    data["report_signature"] = signature

                    reports_list.blockSignals(True)
                    reports_list.clear()

                    selected_index = -1
                    for index, item in enumerate(rows):
                        report_number = (
                            item.get("report_number") or "—"
                        )
                        report_status = str(
                            item.get("status") or "new"
                        )
                        updated = self._community_date(
                            item.get("updated_at")
                            or item.get("created_at")
                        )

                        reports_list.addItem(
                            f"#{report_number} • "
                            f"{status_names.get(report_status, report_status)}\n"
                            f"{item.get('title') or 'Без названия'}\n"
                            f"Активность: {updated}"
                        )

                        if (
                            str(item.get("id") or "")
                            == previous_id
                        ):
                            selected_index = index

                    if rows:
                        if selected_index < 0:
                            selected_index = 0
                        reports_list.setCurrentRow(
                            selected_index
                        )
                        selected = rows[selected_index]
                        data["selected_id"] = str(
                            selected.get("id") or ""
                        )
                        update_report_header(selected)
                        load_attachments(silent=True)
                    else:
                        data["selected_id"] = None
                        update_report_header(None)

                    reports_list.blockSignals(False)

                    if rows:
                        load_messages(silent=True)
                    else:
                        clear_chat_widgets()
                        empty = QLabel(
                            "С этой установки DeiLaw "
                            "репорты ещё не отправлялись."
                        )
                        empty.setObjectName("muted")
                        empty.setAlignment(
                            Qt.AlignmentFlag.AlignCenter
                        )
                        chat_messages_layout.addWidget(empty)
                        chat_messages_layout.addStretch()

                live_badge.setText("● LIVE")
                sync_status.setText(
                    "● Синхронизация активна • "
                    "репорты и сообщения обновляются каждые 2 секунды"
                )

            def failed(message):
                data["reports_loading"] = False
                refresh.setEnabled(True)
                live_badge.setText("○ OFFLINE")
                sync_status.setText(
                    "Не удалось обновить репорты: "
                    f"{message}"
                )

            self._run_community_task(
                self.community_client.fetch_my_bug_reports,
                on_success=loaded,
                on_error=failed,
            )

        def send_message():
            report = find_selected_report()
            if report is None:
                return

            if str(report.get("status") or "") == "closed":
                return

            message = composer.toPlainText().strip()
            if not message:
                return

            report_id = str(
                report.get("id") or ""
            ).strip()
            if not report_id:
                return

            send_button.setEnabled(False)
            composer.setEnabled(False)
            sync_status.setText(
                "Отправляю сообщение…"
            )

            def sent(_row):
                composer.clear()
                composer.setEnabled(True)
                send_button.setEnabled(True)
                self.play_ui_sound("success")
                load_messages(silent=False)
                load_reports(silent=True)

            def failed(message_text):
                composer.setEnabled(True)
                send_button.setEnabled(True)
                sync_status.setText(
                    "Не удалось отправить сообщение: "
                    f"{message_text}"
                )

            self._run_community_task(
                self.community_client.send_report_message,
                args=(report_id, message),
                on_success=sent,
                on_error=failed,
            )

        def open_new_report():
            self.show_bug_report_dialog()
            # The submit dialog is modal. When it closes, refresh the unified
            # reports window so a successfully submitted report appears here.
            QTimer.singleShot(250, lambda: load_reports(silent=False))

        new_report_button.clicked.connect(open_new_report)
        send_button.clicked.connect(send_message)
        refresh.clicked.connect(
            lambda: load_reports(silent=False)
        )

        live_timer = QTimer(dialog)
        live_timer.setInterval(2000)

        def live_tick():
            if not dialog.isVisible():
                return
            load_reports(silent=True)
            if data.get("selected_id"):
                load_messages(silent=True)
                load_attachments(silent=True)

        live_timer.timeout.connect(live_tick)
        live_timer.start()

        dialog.finished.connect(
            lambda _result: live_timer.stop()
        )

        load_reports(silent=False)
        dialog.exec()

    # =========================================================
    # AHK RP BINDS
    # =========================================================

    def create_ahk_bindings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("AHK бинды для RP")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Создавай игровые бинды для RP-отыгровок и экспортируй готовый "
            "скрипт AutoHotkey v2. Например: /me достал телефон."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, stretch=1)

        self.ahk_export_button = QPushButton("Экспорт .ahk")
        self.ahk_export_button.setObjectName("primary")
        self.ahk_export_button.clicked.connect(self.export_ahk_script)
        header.addWidget(
            self.ahk_export_button,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        layout.addLayout(header)

        options_card = QFrame()
        options_card.setObjectName("card")
        options_layout = QHBoxLayout(options_card)
        options_layout.setContentsMargins(16, 12, 16, 12)
        options_layout.setSpacing(10)

        options_layout.addWidget(QLabel("Клавиша открытия чата"))
        self.ahk_chat_key = QLineEdit()
        self.ahk_chat_key.setMaximumWidth(90)
        self.ahk_chat_key.setMaxLength(20)
        self.ahk_chat_key.setText(
            str(self.ahk_bind_store.data.get("chat_key", "t"))
        )
        self.ahk_chat_key.setToolTip(
            "Обычно в GTA/RMRP чат открывается клавишей T. "
            "Можно указать другую одиночную клавишу."
        )
        options_layout.addWidget(self.ahk_chat_key)

        options_layout.addSpacing(12)
        options_layout.addWidget(QLabel("Пауза открытия чата"))
        self.ahk_open_chat_delay = QSpinBox()
        self.ahk_open_chat_delay.setRange(40, 3000)
        self.ahk_open_chat_delay.setSuffix(" мс")
        self.ahk_open_chat_delay.setValue(
            int(self.ahk_bind_store.data.get("open_chat_delay", 140))
        )
        options_layout.addWidget(self.ahk_open_chat_delay)
        options_layout.addStretch()

        self.ahk_copy_script_button = QPushButton("Копировать скрипт")
        self.ahk_copy_script_button.clicked.connect(self.copy_ahk_script)
        options_layout.addWidget(self.ahk_copy_script_button)
        layout.addWidget(options_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        # Left side: bind list.
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 12, 12, 12)
        list_layout.setSpacing(8)

        list_header = QHBoxLayout()
        list_title = QLabel("RP бинды")
        list_title.setObjectName("sectionTitle")
        list_header.addWidget(list_title)
        list_header.addStretch()
        self.ahk_new_button = QPushButton("+ Новый")
        self.ahk_new_button.clicked.connect(self.new_ahk_binding)
        list_header.addWidget(self.ahk_new_button)
        list_layout.addLayout(list_header)

        self.ahk_bind_list = QListWidget()
        self.ahk_bind_list.setWordWrap(True)
        self.ahk_bind_list.setSpacing(4)
        self.ahk_bind_list.currentRowChanged.connect(
            self.load_selected_ahk_binding
        )
        list_layout.addWidget(self.ahk_bind_list, stretch=1)

        self.ahk_delete_button = QPushButton("Удалить бинд")
        self.ahk_delete_button.clicked.connect(
            self.delete_selected_ahk_binding
        )
        list_layout.addWidget(self.ahk_delete_button)

        # Right side: editor + preview.
        editor_card = QFrame()
        editor_card.setObjectName("card")
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(16, 14, 16, 14)
        editor_layout.setSpacing(9)

        editor_title = QLabel("Редактор бинда")
        editor_title.setObjectName("sectionTitle")
        editor_layout.addWidget(editor_title)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Название"))
        self.ahk_bind_name = QLineEdit()
        self.ahk_bind_name.setPlaceholderText("Например: Достать телефон")
        self.ahk_bind_name.setMaxLength(80)
        name_row.addWidget(self.ahk_bind_name, stretch=1)
        editor_layout.addLayout(name_row)

        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(QLabel("Бинд"))
        hotkey_row.addStretch()
        self.ahk_bind_hotkey = SingleHotkeyEdit()
        self.ahk_bind_hotkey.setMaximumWidth(230)
        hotkey_row.addWidget(self.ahk_bind_hotkey)
        editor_layout.addLayout(hotkey_row)

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Пауза между строками"))
        delay_row.addStretch()
        self.ahk_bind_delay = QSpinBox()
        self.ahk_bind_delay.setRange(0, 10000)
        self.ahk_bind_delay.setSuffix(" мс")
        self.ahk_bind_delay.setValue(350)
        delay_row.addWidget(self.ahk_bind_delay)
        editor_layout.addLayout(delay_row)

        self.ahk_bind_enabled = StatusCheckBox(
            "Включить бинд — работает прямо из DeiLaw и входит в AHK-экспорт"
        )
        self.ahk_bind_enabled.setChecked(True)
        editor_layout.addWidget(self.ahk_bind_enabled)

        commands_label = QLabel("RP-команды — одна команда на строку")
        commands_label.setObjectName("articleHeading")
        editor_layout.addWidget(commands_label)

        self.ahk_bind_commands = QTextEdit()
        self.ahk_bind_commands.setPlaceholderText(
            "/me достал телефон\n"
            "/do Телефон находится в правой руке."
        )
        self.ahk_bind_commands.setMaximumHeight(150)
        editor_layout.addWidget(self.ahk_bind_commands)

        buttons = QHBoxLayout()
        self.ahk_save_button = QPushButton("Сохранить бинд")
        self.ahk_save_button.setObjectName("primary")
        self.ahk_save_button.clicked.connect(self.save_ahk_binding)
        buttons.addWidget(self.ahk_save_button)
        buttons.addStretch()
        editor_layout.addLayout(buttons)

        preview_title = QLabel("Предпросмотр AHK v2")
        preview_title.setObjectName("articleHeading")
        editor_layout.addWidget(preview_title)
        self.ahk_script_preview = QTextBrowser()
        self.ahk_script_preview.setMinimumHeight(170)
        editor_layout.addWidget(self.ahk_script_preview, stretch=1)

        splitter.addWidget(list_card)
        splitter.addWidget(editor_card)
        splitter.setSizes([360, 850])
        layout.addWidget(splitter, stretch=1)

        self.ahk_status_label = QLabel(
            "Сохранённые активные бинды работают глобально прямо из DeiLaw. "
            "AutoHotkey v2 нужен только если вы запускаете экспортированный .ahk отдельно."
        )
        self.ahk_status_label.setObjectName("muted")
        self.ahk_status_label.setWordWrap(True)
        layout.addWidget(self.ahk_status_label)

        self.ahk_chat_key.textChanged.connect(self._on_ahk_options_changed)
        self.ahk_open_chat_delay.valueChanged.connect(
            self._on_ahk_options_changed
        )
        self.ahk_bind_name.textChanged.connect(self.refresh_ahk_preview)
        self.ahk_bind_hotkey.keySequenceChanged.connect(
            lambda _seq: self.refresh_ahk_preview()
        )
        self.ahk_bind_delay.valueChanged.connect(
            lambda _value: self.refresh_ahk_preview()
        )
        self.ahk_bind_enabled.toggled.connect(
            lambda _checked: self.refresh_ahk_preview()
        )
        self.ahk_bind_commands.textChanged.connect(self.refresh_ahk_preview)

        QTimer.singleShot(0, self.refresh_ahk_bindings_page)
        return page

    def _on_ahk_options_changed(self, *_args):
        try:
            self.ahk_bind_store.set_script_options(
                chat_key=self.ahk_chat_key.text().strip() or "t",
                open_chat_delay=self.ahk_open_chat_delay.value(),
            )
        except Exception:
            return
        self.refresh_ahk_preview()

    def refresh_ahk_bindings_page(self, select_id=None):
        if not hasattr(self, "ahk_bind_list"):
            return

        if select_id is None:
            current = self.ahk_bind_list.currentItem()
            if current is not None:
                select_id = current.data(Qt.ItemDataRole.UserRole)
            if not select_id:
                select_id = self.current_ahk_bind_id

        rows = self.ahk_bind_store.bindings()
        self.ahk_bind_list.blockSignals(True)
        self.ahk_bind_list.clear()
        selected_row = -1

        for index, record in enumerate(rows):
            enabled = "●" if record.get("enabled", True) else "○"
            commands = record.get("commands") or []
            first = str(commands[0]) if commands else "Без команд"
            if len(first) > 72:
                first = first[:69] + "…"
            item = QListWidgetItem(
                f"{enabled} {record.get('name') or 'Без названия'}\n"
                f"{record.get('hotkey') or 'Без бинда'} • {first}"
            )
            item.setData(Qt.ItemDataRole.UserRole, record.get("id"))
            self.ahk_bind_list.addItem(item)
            if str(record.get("id")) == str(select_id or ""):
                selected_row = index

        self.ahk_bind_list.blockSignals(False)

        if rows:
            if selected_row < 0:
                selected_row = 0
            self.ahk_bind_list.setCurrentRow(selected_row)
            self.load_selected_ahk_binding(selected_row)
        else:
            self.new_ahk_binding()

        self.refresh_ahk_preview()
        if getattr(self, "ahk_runtime_last_summary", ""):
            self.ahk_status_label.setText(self.ahk_runtime_last_summary)

    def new_ahk_binding(self):
        self.current_ahk_bind_id = None
        if hasattr(self, "ahk_bind_list"):
            self.ahk_bind_list.blockSignals(True)
            self.ahk_bind_list.clearSelection()
            self.ahk_bind_list.setCurrentRow(-1)
            self.ahk_bind_list.blockSignals(False)

        self.ahk_bind_name.clear()
        self.ahk_bind_hotkey.setKeySequence(QKeySequence())
        self.ahk_bind_delay.setValue(350)
        self.ahk_bind_enabled.setChecked(True)
        self.ahk_bind_commands.clear()
        self.ahk_delete_button.setEnabled(False)
        runtime_summary = getattr(self, "ahk_runtime_last_summary", "")
        self.ahk_status_label.setText(
            "Новый бинд: укажи название, клавишу и RP-команды."
            + (f"\n{runtime_summary}" if runtime_summary else "")
        )
        self.refresh_ahk_preview()

    def load_selected_ahk_binding(self, row):
        if row < 0 or row >= self.ahk_bind_list.count():
            return
        item = self.ahk_bind_list.item(row)
        bind_id = item.data(Qt.ItemDataRole.UserRole)
        record = self.ahk_bind_store.get(bind_id)
        if not record:
            return

        self.current_ahk_bind_id = str(record.get("id") or "")
        self.ahk_bind_name.setText(str(record.get("name") or ""))
        self.ahk_bind_hotkey.setKeySequence(
            SingleHotkeyEdit.sequence_from_spec(record.get("hotkey", ""))
        )
        self.ahk_bind_delay.setValue(int(record.get("delay_ms", 350)))
        self.ahk_bind_enabled.setChecked(bool(record.get("enabled", True)))
        self.ahk_bind_commands.setPlainText(
            "\n".join(str(line) for line in record.get("commands", []))
        )
        self.ahk_delete_button.setEnabled(True)
        runtime_summary = getattr(self, "ahk_runtime_last_summary", "")
        self.ahk_status_label.setText(
            f"Редактируется: {record.get('name') or 'без названия'}"
            + (f"\n{runtime_summary}" if runtime_summary else "")
        )
        self.refresh_ahk_preview()

    def save_ahk_binding(self):
        commands = [
            line.strip()
            for line in self.ahk_bind_commands.toPlainText().splitlines()
            if line.strip()
        ]
        hotkey_text = self.ahk_bind_hotkey.hotkey_text().strip()
        chat_key_text = self.ahk_chat_key.text().strip() or "t"
        try:
            macro_key = self.parse_windows_hotkey(hotkey_text)
            chat_key = self.parse_windows_hotkey(chat_key_text)
            if macro_key is not None and chat_key is not None and macro_key == chat_key:
                raise ValueError(
                    "Бинд не может совпадать с клавишей открытия чата. "
                    "Выберите другую клавишу для RP-бинда."
                )

            record = self.ahk_bind_store.upsert(
                bind_id=self.current_ahk_bind_id,
                name=self.ahk_bind_name.text(),
                hotkey=hotkey_text,
                commands=commands,
                delay_ms=self.ahk_bind_delay.value(),
                enabled=self.ahk_bind_enabled.isChecked(),
            )
            self.ahk_bind_store.set_script_options(
                chat_key=self.ahk_chat_key.text().strip() or "t",
                open_chat_delay=self.ahk_open_chat_delay.value(),
            )
            # Validate the generated AHK hotkey immediately.
            self.ahk_bind_store.generate_script()
        except Exception as exc:
            QMessageBox.warning(self, "AHK бинды", str(exc))
            return

        self.current_ahk_bind_id = record["id"]
        self.refresh_ahk_bindings_page(record["id"])
        summary = self.install_ahk_runtime_hotkeys()
        self.show_save_toast("AHK бинд сохранён и активирован")
        self.ahk_status_label.setText(summary)

    def delete_selected_ahk_binding(self):
        bind_id = str(self.current_ahk_bind_id or "")
        if not bind_id:
            return
        record = self.ahk_bind_store.get(bind_id)
        if not record:
            return

        answer = QMessageBox.question(
            self,
            "Удалить AHK бинд",
            f"Удалить бинд «{record.get('name') or 'Без названия'}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.ahk_bind_store.remove(bind_id)
        self.current_ahk_bind_id = None
        self.refresh_ahk_bindings_page()
        summary = self.install_ahk_runtime_hotkeys()
        self.show_save_toast("AHK бинд удалён")
        self.ahk_status_label.setText(summary)

    def _current_ahk_preview_script(self):
        # Preview the whole saved script and, for an unsaved/edited macro,
        # append a compact snippet so the user can see the exact result.
        base = self.ahk_bind_store.generate_script()
        name = self.ahk_bind_name.text().strip()
        hotkey = self.ahk_bind_hotkey.hotkey_text().strip()
        commands = [
            line.strip()
            for line in self.ahk_bind_commands.toPlainText().splitlines()
            if line.strip()
        ]
        if not name and not hotkey and not commands:
            return base

        try:
            ahk_hotkey = self.ahk_bind_store.hotkey_to_ahk(hotkey)
            chat_line = self.ahk_bind_store._chat_send_line(
                self.ahk_chat_key.text().strip() or "t"
            )
        except Exception as exc:
            return base + f"\n; Предпросмотр текущего редактора недоступен: {exc}\n"

        snippet = [
            "",
            "; --- Текущий редактор (предпросмотр) ---",
            f"; {name or 'Без названия'}",
            f"{ahk_hotkey}::",
            "{",
        ]
        for command in commands:
            escaped = self.ahk_bind_store._escape_ahk_string(command)
            snippet.extend([
                f"    {chat_line}",
                f"    Sleep {self.ahk_open_chat_delay.value()}",
                f'    SendText "{escaped}"',
                '    Send "{Enter}"',
            ])
            if self.ahk_bind_delay.value():
                snippet.append(f"    Sleep {self.ahk_bind_delay.value()}")
        snippet.append("}")
        return base.rstrip() + "\n" + "\n".join(snippet) + "\n"

    def refresh_ahk_preview(self, *_args):
        if not hasattr(self, "ahk_script_preview"):
            return
        try:
            self.ahk_bind_store.set_script_options(
                chat_key=self.ahk_chat_key.text().strip() or "t",
                open_chat_delay=self.ahk_open_chat_delay.value(),
            )
            self.ahk_script_preview.setPlainText(
                self._current_ahk_preview_script()
            )
        except Exception as exc:
            self.ahk_script_preview.setPlainText(
                f"Не удалось создать предпросмотр:\n{exc}"
            )

    def copy_ahk_script(self):
        try:
            script = self.ahk_bind_store.generate_script()
        except Exception as exc:
            QMessageBox.warning(self, "AHK бинды", str(exc))
            return
        QApplication.clipboard().setText(script)
        self.show_save_toast("AHK скрипт скопирован")

    def export_ahk_script(self):
        try:
            self.ahk_bind_store.set_script_options(
                chat_key=self.ahk_chat_key.text().strip() or "t",
                open_chat_delay=self.ahk_open_chat_delay.value(),
            )
            script = self.ahk_bind_store.generate_script()
        except Exception as exc:
            QMessageBox.warning(self, "AHK бинды", str(exc))
            return

        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Экспорт AHK биндов",
            str(Path.home() / "DeiLaw_RP_Binds.ahk"),
            "AutoHotkey Script (*.ahk);;Все файлы (*.*)",
        )
        if not path:
            return
        try:
            target = Path(path)
            if target.suffix.lower() != ".ahk":
                target = target.with_suffix(".ahk")
            target.write_text(script, encoding="utf-8-sig")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Экспорт AHK",
                f"Не удалось сохранить файл:\n{exc}",
            )
            return

        self.show_save_toast("AHK скрипт экспортирован")
        self.ahk_status_label.setText(
            f"Сохранено: {target}"
        )

    # =========================================================
    # STATUS PAGE
    # =========================================================

    def create_status_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Состояние DeiLaw")
        title.setObjectName("pageTitle")
        description = QLabel(
            "Сводка по локальной базе, умному поиску, обновлениям и настройкам программы."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(description)
        header.addLayout(title_box, stretch=1)

        refresh_button = QPushButton("↻  Обновить состояние")
        refresh_button.setObjectName("primary")
        refresh_button.clicked.connect(self.refresh_status_page)
        header.addWidget(refresh_button, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        def status_card(card_title):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            card_layout.setSpacing(8)
            heading = QLabel(card_title)
            heading.setObjectName("sectionTitle")
            body = QLabel("Загрузка…")
            body.setObjectName("muted")
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card_layout.addWidget(heading)
            card_layout.addWidget(body)
            return card, body

        first_row = QHBoxLayout()
        db_card, self.status_database_label = status_card("📚  База законодательства")
        search_card, self.status_search_label = status_card("🔎  Умный поиск")
        first_row.addWidget(db_card, stretch=1)
        first_row.addWidget(search_card, stretch=1)
        layout.addLayout(first_row)

        second_row = QHBoxLayout()
        update_card, self.status_update_label = status_card("🔄  Обновления и изменения")
        app_card, self.status_app_label = status_card("⚙  Программа")
        second_row.addWidget(update_card, stretch=1)
        second_row.addWidget(app_card, stretch=1)
        layout.addLayout(second_row)

        ai_card, self.status_ai_label = status_card("🤖  DeiLaw AI и обучение")
        layout.addWidget(ai_card)

        hint = QLabel(
            "Состояние обновляется при открытии этой страницы и после синхронизации законодательства."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def refresh_status_page(self):
        if not hasattr(self, "status_database_label"):
            return

        try:
            stats = self.database.get_stats()
        except Exception:
            stats = {"laws": 0, "articles": 0, "updated_at": None, "changes": 0}

        updated_at = stats.get("updated_at") or "ещё не обновлялась"
        self.status_database_label.setText(
            f"Документов: {stats.get('laws', 0)}\n"
            f"Статей: {stats.get('articles', 0)}\n"
            f"Последняя синхронизация: {updated_at}"
        )

        try:
            lex = self.smart_text_search.lexicon_stats()
        except Exception:
            lex = {}
        self.status_search_label.setText(
            f"История запросов: {len(self.search_history)}\n"
            f"Смысловых групп: {lex.get('keyword_groups', 0)}\n"
            f"Вариантов ключевых слов: {lex.get('keyword_variants', 0)}\n"
            f"Триггерных фраз: {lex.get('trigger_variants', 0)}\n"
            f"Стоп-слов и паразитов: "
            f"{lex.get('stop_words', 0) + lex.get('filler_phrases', 0)}"
        )

        latest = None
        try:
            latest = self.database.get_latest_update_run()
        except Exception:
            pass

        if latest:
            finished = latest["completed_at"] or latest["started_at"] or "—"
            self.status_update_label.setText(
                f"Последняя проверка: {finished}\n"
                f"Документов обновлено: {latest['successful']}\n"
                f"Изменений: {latest['total_changes']} "
                f"(+{latest['added_count']} / ~{latest['modified_count']} / -{latest['removed_count']})\n"
                f"Всего записей истории: {stats.get('changes', 0)}"
            )
        else:
            self.status_update_label.setText(
                "История обновлений пока пуста.\n"
                "После следующей синхронизации DeiLaw начнёт фиксировать изменения статей."
            )

        if hasattr(self, "status_ai_label"):
            self.status_ai_label.setText(
                "Cloud AI: Supabase Edge Function → OpenAI\n"
                "Подбор источников: локально по базе RMRP\n"
                "Ollama / Qwen / embedding-модели: не используются\n"
                "Интернет нужен только для ответа DeiLaw AI"
            )

        memo_count = 0
        try:
            memo_count = sum(
                len(section.get("articles", []))
                for column in self.memo_columns
                for section in column.get("sections", [])
            )
        except Exception:
            pass

        safe_text = "ВКЛЮЧЁН" if self.safe_mode else "выключен"
        favorites_count = len(self.profile_store.favorites(self.active_profile))
        self.status_app_label.setText(
            f"Версия: {APP_VERSION}\n"
            f"Профиль: {self.active_profile} • избранных: {favorites_count}\n"
            f"Безопасный режим: {safe_text}\n"
            "RP-помощник: БЕТА\n"
            f"Быстрый поиск: {self.app_settings.get('search_hotkey', 'F7')}\n"
            f"Quick Memo: {self.app_settings.get('memo_hotkey', 'F8')}\n"
            f"Калькулятор: {self.app_settings.get('calculator_hotkey', 'F9')}\n"
            f"Статей в памятке: {memo_count}\n"
            f"Тема: {'Светлая' if self.app_settings.get('theme') == 'light' else 'Тёмная'}"
            f"\nОбновления программы: {self.program_update_status_text}"
        )
    def notify_unseen_legislation_changes(self):
        try:
            latest = self.database.get_latest_update_run()
        except Exception:
            return
        if not latest:
            return

        run_id = int(latest["id"] or 0)
        total = int(latest["total_changes"] or 0)
        last_seen = int(
            self.app_settings.get("last_seen_law_update_run", 0) or 0
        )
        if run_id <= last_seen:
            return

        self.app_settings["last_seen_law_update_run"] = run_id
        self.save_app_settings()
        if total > 0:
            self.show_save_toast(
                f"Законодательство: {total} изменений"
            )

    def mark_latest_legislation_changes_seen(self):
        try:
            latest = self.database.get_latest_update_run()
            if latest:
                self.app_settings["last_seen_law_update_run"] = int(
                    latest["id"] or 0
                )
                self.save_app_settings()
        except Exception:
            pass

    # =========================================================
    # UPDATE PAGE + CHANGE HISTORY
    # =========================================================

    def create_update_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(16)

        title = QLabel("Обновления Базы")
        title.setObjectName("pageTitle")

        description = QLabel(
            "Синхронизация локальной базы DeiLaw с законодательством форума "
            "RMRP. Здесь обновляются именно законы и статьи, а история версий "
            "самой программы находится во вкладке «Прошлые обновления»."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)

        self.update_status = QLabel(
            "Готово к проверке обновлений базы."
        )
        self.update_status.setObjectName("articleHeading")
        self.update_status.setWordWrap(True)
        layout.addWidget(self.update_status)

        self.update_progress = QProgressBar()
        self.update_progress.setMinimum(0)
        self.update_progress.setMaximum(31)
        self.update_progress.setValue(0)
        self.update_progress.setTextVisible(True)
        layout.addWidget(self.update_progress)

        update_controls = QHBoxLayout()
        self.update_details = QLabel(
            "Нажмите кнопку, чтобы проверить актуальную редакцию "
            "законодательства."
        )
        self.update_details.setObjectName("muted")
        self.update_details.setWordWrap(True)
        update_controls.addWidget(
            self.update_details,
            stretch=1,
        )

        self.open_update_history_button = QPushButton(
            "🕘 Прошлые обновления"
        )
        self.open_update_history_button.clicked.connect(
            lambda: self.switch_page(
                self.update_history_page_index
            )
        )
        update_controls.addWidget(
            self.open_update_history_button
        )

        self.start_update_button = QPushButton(
            "Проверить и обновить"
        )
        self.start_update_button.setObjectName("primary")
        self.start_update_button.setFixedWidth(220)
        update_controls.addWidget(self.start_update_button)
        layout.addLayout(update_controls)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 14, 16, 14)
        log_layout.setSpacing(10)

        log_header = QHBoxLayout()
        log_title = QLabel("Журнал текущего обновления")
        log_title.setObjectName("articleHeading")
        log_header.addWidget(log_title)
        log_header.addStretch()

        clear_log = QPushButton("Очистить журнал")
        clear_log.clicked.connect(
            lambda: self.update_log.clear()
        )
        log_header.addWidget(clear_log)
        log_layout.addLayout(log_header)

        self.update_log = QTextBrowser()
        self.update_log.setPlaceholderText(
            "Здесь появится процесс обновления базы..."
        )
        log_layout.addWidget(self.update_log, stretch=1)

        layout.addWidget(log_card, stretch=1)

        self.start_update_button.clicked.connect(
            self.start_database_update
        )
        return page

    def create_update_history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()

        title = QLabel("Прошлые обновления DeiLaw")
        title.setObjectName("pageTitle")

        description = QLabel(
            "История версий самой программы DeiLaw. Здесь можно посмотреть, "
            "какие версии выходили раньше и что менялось в каждом релизе."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)

        title_box.addWidget(title)
        title_box.addWidget(description)
        header.addLayout(title_box, stretch=1)

        self.program_history_refresh_button = QPushButton(
            "↻ Обновить историю"
        )
        self.program_history_refresh_button.clicked.connect(
            self.refresh_update_history
        )
        header.addWidget(
            self.program_history_refresh_button,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        layout.addLayout(header)

        current_card = QFrame()
        current_card.setObjectName("card")
        current_layout = QHBoxLayout(current_card)
        current_layout.setContentsMargins(16, 12, 16, 12)

        current_title = QLabel("Установленная версия")
        current_title.setObjectName("muted")
        self.program_history_current_version = QLabel(
            f"DeiLaw {APP_VERSION}"
        )
        self.program_history_current_version.setObjectName(
            "sectionTitle"
        )

        current_layout.addWidget(current_title)
        current_layout.addSpacing(12)
        current_layout.addWidget(
            self.program_history_current_version
        )
        current_layout.addStretch()
        layout.addWidget(current_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        releases_card = QFrame()
        releases_card.setObjectName("card")
        releases_layout = QVBoxLayout(releases_card)
        releases_layout.setContentsMargins(12, 12, 12, 12)

        releases_title = QLabel("Версии программы")
        releases_title.setObjectName("sectionTitle")
        releases_layout.addWidget(releases_title)

        self.program_release_list = QListWidget()
        self.program_release_list.setWordWrap(True)
        self.program_release_list.setSpacing(5)
        self.program_release_list.currentRowChanged.connect(
            self.show_program_release
        )
        releases_layout.addWidget(
            self.program_release_list,
            stretch=1,
        )

        details_card = QFrame()
        details_card.setObjectName("card")
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(14, 14, 14, 14)

        detail_header = QHBoxLayout()
        self.program_release_title = QLabel(
            "Выберите версию"
        )
        self.program_release_title.setObjectName(
            "sectionTitle"
        )
        detail_header.addWidget(
            self.program_release_title,
            stretch=1,
        )

        self.program_release_open_button = QPushButton(
            "Открыть релиз"
        )
        self.program_release_open_button.setEnabled(False)
        self.program_release_open_button.clicked.connect(
            self.open_selected_program_release
        )
        detail_header.addWidget(
            self.program_release_open_button
        )
        details_layout.addLayout(detail_header)

        self.program_release_meta = QLabel("")
        self.program_release_meta.setObjectName("muted")
        self.program_release_meta.setWordWrap(True)
        details_layout.addWidget(self.program_release_meta)

        self.program_release_details = QTextBrowser()
        self.program_release_details.setPlainText(
            "История версий загружается с GitHub Releases."
        )
        details_layout.addWidget(
            self.program_release_details,
            stretch=1,
        )

        splitter.addWidget(releases_card)
        splitter.addWidget(details_card)
        splitter.setSizes([390, 900])
        layout.addWidget(splitter, stretch=1)

        self.program_history_status = QLabel(
            "История версий загружается с официального репозитория DeiLaw."
        )
        self.program_history_status.setObjectName("muted")
        self.program_history_status.setWordWrap(True)
        layout.addWidget(self.program_history_status)

        QTimer.singleShot(
            900,
            self.refresh_update_history,
        )
        return page

    def maybe_auto_update_laws_at_startup(self):
        if self.safe_mode:
            return
        if not bool(self.app_settings.get("auto_update_laws_on_startup", True)):
            return
        # First-time users keep the normal onboarding/database setup flow.
        if not bool(self.app_settings.get("onboarding_completed", False)):
            return
        if self.update_worker is not None and self.update_worker.isRunning():
            return

        try:
            interval_hours = max(1, int(self.app_settings.get("law_update_interval_hours", 6) or 6))
        except (TypeError, ValueError):
            interval_hours = 6
        try:
            last_check = int(self.app_settings.get("last_auto_law_update_at", 0) or 0)
        except (TypeError, ValueError):
            last_check = 0

        if last_check and time.time() - last_check < interval_hours * 3600:
            return

        self._auto_law_update_in_progress = True
        self.start_database_update()

    def start_database_update(self):
        if self.update_worker is not None and self.update_worker.isRunning():
            return

        self.start_update_button.setEnabled(False)
        self.update_progress.setValue(0)
        self.update_log.clear()
        self.update_status.setText("Подключение к RMRP...")
        self.update_details.setText("Получаем список законодательства...")

        self.update_worker = UpdateWorker()
        self.update_worker.progress.connect(self.on_update_progress)
        self.update_worker.document_done.connect(self.on_document_updated)
        self.update_worker.error.connect(self.on_update_error)
        self.update_worker.completed.connect(self.on_update_completed)
        self.update_worker.start()

    def on_update_progress(self, current, total, title):
        self.update_progress.setMaximum(total)
        self.update_progress.setValue(current)
        self.update_status.setText(f"Обновление {current}/{total}")
        self.update_details.setText(title)

    def on_document_updated(self, title, articles):
        self.update_log.append(
            f"✓ {title}<br>&nbsp;&nbsp;&nbsp;Статей: {articles}<br>"
        )

    def on_update_error(self, message):
        self.update_log.append(f"<b>✗ Ошибка:</b> {message}<br>")
        # Если произошла общая ошибка до завершения цикла, не оставляем кнопку заблокированной.
        if self.update_worker is not None and not self.update_worker.isRunning():
            self.start_update_button.setEnabled(True)
            self._auto_law_update_in_progress = False

    def on_update_completed(self, successful, failed, articles):
        was_auto_update = bool(self._auto_law_update_in_progress)
        self._auto_law_update_in_progress = False
        if was_auto_update:
            self.app_settings["last_auto_law_update_at"] = int(time.time())
            self.save_app_settings()
        self.play_ui_sound("law_update_complete")
        self.update_progress.setValue(self.update_progress.maximum())
        self.update_status.setText("База законодательства обновлена")

        latest = None
        try:
            latest = self.database.get_latest_update_run()
        except Exception:
            pass

        if latest:
            changes_text = (
                f"Изменений: {latest['total_changes']} "
                f"(+{latest['added_count']} / ~{latest['modified_count']} / -{latest['removed_count']})"
            )
        else:
            changes_text = "Изменения: нет данных"

        self.update_details.setText(
            f"Документов: {successful} | Ошибок: {failed} | "
            f"Статей: {articles} | {changes_text}"
        )
        self.update_log.append(
            "<br><b>============================</b><br>"
            "<b>ОБНОВЛЕНИЕ ЗАВЕРШЕНО</b><br>"
            "<b>============================</b><br>"
            f"Документов: {successful}<br>"
            f"Ошибок: {failed}<br>"
            f"Статей: {articles}<br>"
            f"{changes_text}<br>"
        )
        self.start_update_button.setEnabled(True)
        self.load_laws()
        self.load_stats()
        self.refresh_status_page()

        if latest and int(latest["total_changes"] or 0) > 0:
            total_changes = int(latest["total_changes"] or 0)
            self.show_save_toast(
                f"Законодательство обновлено: {total_changes} изменений"
            )
            self.mark_latest_legislation_changes_seen()

        if articles > 0:
            self.app_settings["initial_database_notice_dismissed"] = True
            self.save_app_settings()


    def refresh_update_history(self):
        """Load previous DeiLaw PROGRAM releases from GitHub."""
        if not hasattr(self, "program_release_list"):
            return

        worker = getattr(
            self,
            "program_release_history_worker",
            None,
        )
        if worker is not None and worker.isRunning():
            return

        self.program_release_list.clear()
        self.program_release_title.setText(
            "Загрузка истории…"
        )
        self.program_release_meta.clear()
        self.program_release_details.setPlainText(
            "Получаю список прошлых версий DeiLaw…"
        )
        self.program_release_open_button.setEnabled(False)
        self.program_history_status.setText(
            "Подключаюсь к GitHub Releases…"
        )
        self.program_history_refresh_button.setEnabled(False)
        self.program_release_history = []
        self.selected_program_release_url = ""

        config = load_update_config("beta")
        worker = ProgramReleaseHistoryWorker(
            config,
            self,
            limit=100,
        )
        self.program_release_history_worker = worker
        worker.completed.connect(
            self.on_program_release_history_loaded
        )
        worker.error.connect(
            self.on_program_release_history_error
        )
        worker.finished.connect(
            self.on_program_release_history_finished
        )
        worker.start()

    def on_program_release_history_finished(self):
        if hasattr(self, "program_history_refresh_button"):
            self.program_history_refresh_button.setEnabled(True)

    def on_program_release_history_error(self, message):
        if not hasattr(self, "program_history_status"):
            return
        self.program_history_status.setText(
            f"Не удалось загрузить историю версий: {message}"
        )
        self.program_release_title.setText(
            "История недоступна"
        )
        self.program_release_details.setPlainText(
            "Проверьте подключение к интернету и повторите попытку."
        )

    @staticmethod
    def _format_program_release_date(value):
        value = str(value or "").strip()
        if not value:
            return "дата не указана"
        try:
            date_part, time_part = value.replace("Z", "").split(
                "T",
                1,
            )
            year, month, day = date_part.split("-")
            return (
                f"{day}.{month}.{year} "
                f"{time_part[:5]}"
            )
        except Exception:
            return value[:19]

    def on_program_release_history_loaded(self, releases):
        if not hasattr(self, "program_release_list"):
            return

        self.program_release_history = list(
            releases or []
        )
        self.program_release_list.clear()

        if not self.program_release_history:
            self.program_history_status.setText(
                "В официальном репозитории DeiLaw пока нет "
                "опубликованных релизов."
            )
            self.program_release_title.setText(
                "Релизы не найдены"
            )
            self.program_release_details.setPlainText(
                "После публикации версий на GitHub они появятся здесь."
            )
            return

        current_found = False

        for release in self.program_release_history:
            version = str(
                release.get("version") or "—"
            )
            is_current = (
                version.strip().lower()
                == str(APP_VERSION).strip().lower()
            )
            current_found = current_found or is_current

            channel = (
                "Beta / Pre-release"
                if release.get("prerelease")
                else "Stable"
            )
            published = self._format_program_release_date(
                release.get("published_at")
            )

            first_line = (
                f"DeiLaw {version}"
                + ("  •  УСТАНОВЛЕНА" if is_current else "")
            )
            item = QListWidgetItem(
                f"{first_line}\n"
                f"{channel} • {published}"
            )
            self.program_release_list.addItem(item)

        self.program_history_status.setText(
            f"Найдено версий: "
            f"{len(self.program_release_history)}. "
            "История берётся из GitHub Releases."
        )

        if self.program_release_history:
            current_index = 0
            for index, release in enumerate(
                self.program_release_history
            ):
                if (
                    str(release.get("version") or "").strip().lower()
                    == str(APP_VERSION).strip().lower()
                ):
                    current_index = index
                    break
            self.program_release_list.setCurrentRow(
                current_index
            )

    def show_program_release(self, row):
        if (
            row < 0
            or row >= len(
                getattr(
                    self,
                    "program_release_history",
                    [],
                )
            )
        ):
            return

        release = self.program_release_history[row]
        version = str(
            release.get("version") or "—"
        )
        name = str(
            release.get("name")
            or f"DeiLaw {version}"
        ).strip()
        published = self._format_program_release_date(
            release.get("published_at")
        )
        channel = (
            "Beta / Pre-release"
            if release.get("prerelease")
            else "Stable"
        )
        current = (
            version.strip().lower()
            == str(APP_VERSION).strip().lower()
        )

        self.program_release_title.setText(name)
        self.program_release_meta.setText(
            f"Версия: {version} • "
            f"{channel} • "
            f"Опубликовано: {published}"
            + (
                " • Сейчас установлена"
                if current
                else ""
            )
        )

        notes = str(
            release.get("notes") or ""
        ).strip()
        if not notes:
            notes = (
                "Для этой версии описание изменений "
                "в GitHub Release не указано."
            )

        # Release notes are shown as text so markdown cannot alter the
        # application UI; bullets/headings remain readable.
        self.program_release_details.setPlainText(notes)

        self.selected_program_release_url = str(
            release.get("url") or ""
        ).strip()
        self.program_release_open_button.setEnabled(
            bool(self.selected_program_release_url)
        )

    def open_selected_program_release(self):
        url = str(
            getattr(
                self,
                "selected_program_release_url",
                "",
            )
            or ""
        ).strip()
        if not url:
            return
        try:
            webbrowser.open(url)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Прошлые обновления DeiLaw",
                f"Не удалось открыть релиз:\n{exc}",
            )

    # =========================================================
    # DATA
    # =========================================================


    def load_stats(self):

        stats = self.database.get_stats()

        self.stats_label.setText(
            f"{stats['laws']} документов\n"
            f"{stats['articles']} статей"
        )

    def load_laws(self):

        self.laws = list(
            self.database.get_laws()
        )

        self.laws_list.clear()

        for law in self.laws:

            item = QListWidgetItem(
                law["title"]
            )

            item.setToolTip(
                law["title"]
            )

            self.laws_list.addItem(item)

    @staticmethod
    def _normalize_outline_article_number(value):
        value = re.sub(r"\s+", "", str(value or "")).strip()
        return value.rstrip(".")

    @staticmethod
    def _clean_outline_line(value):
        value = str(value or "").replace("\xa0", " ").strip()
        value = re.sub(r"^[#>*•·\s]+", "", value).strip()
        value = re.sub(r"\s+", " ", value)
        return value

    def _extract_law_outline(self, law_content):
        """Return article->section mapping and ordered top-level section titles.

        The local database stores the full document text, so the outline can be
        reconstructed without changing the database schema. If a document has
        explicit 'Раздел' headings they are preferred; otherwise 'Глава' is used.
        """
        raw_lines = (law_content or "").splitlines()
        lines = [self._clean_outline_line(line) for line in raw_lines]

        heading_re = re.compile(
            r"^(?P<kind>раздел|глава)\s+"
            r"(?P<num>[IVXLCDMА-ЯA-Z0-9]+(?:[.\-]\d+)*)"
            r"(?:\s*[.):—–-]\s*|\s+)?"
            r"(?P<title>.*)$",
            re.IGNORECASE,
        )
        article_re = re.compile(
            r"^статья\s+(?P<num>\d+(?:[-.]\d+)*)\.?\b",
            re.IGNORECASE,
        )
        subarticle_re = re.compile(
            r"^(?P<num>\d+(?:[.-]\d+)+)\.\s*",
            re.IGNORECASE,
        )

        current_section = None
        current_chapter = None
        article_context = {}
        section_order = []
        chapter_order = []

        for index, line in enumerate(lines):
            if not line:
                continue

            heading = heading_re.match(line)
            if heading:
                kind = heading.group("kind").lower()
                number = heading.group("num").strip()
                tail = heading.group("title").strip(" .:—–-")

                # Many forum documents put the section name on the next line.
                if not tail:
                    for next_index in range(index + 1, min(index + 4, len(lines))):
                        candidate = lines[next_index].strip()
                        if not candidate:
                            continue
                        if heading_re.match(candidate) or article_re.match(candidate):
                            break
                        if len(candidate) <= 120:
                            tail = candidate.strip(" .:—–-")
                        break

                kind_title = "Раздел" if kind == "раздел" else "Глава"
                full_title = f"{kind_title} {number}"
                if tail:
                    full_title += f" — {tail}"

                if kind == "раздел":
                    current_section = full_title
                    current_chapter = None
                    if full_title not in section_order:
                        section_order.append(full_title)
                else:
                    current_chapter = full_title
                    if full_title not in chapter_order:
                        chapter_order.append(full_title)
                continue

            article_match = article_re.match(line)
            if article_match:
                number = self._normalize_outline_article_number(
                    article_match.group("num")
                )
                article_context[number] = {
                    "section": current_section,
                    "chapter": current_chapter,
                }
                continue

            # RMRP documents may contain entries such as 63.1. without 'Статья'.
            sub_match = subarticle_re.match(line)
            if sub_match:
                number = self._normalize_outline_article_number(
                    sub_match.group("num")
                )
                article_context[number] = {
                    "section": current_section,
                    "chapter": current_chapter,
                }

        prefer_sections = bool(section_order)
        ordered = section_order if prefer_sections else chapter_order
        mapping = {}
        for number, context in article_context.items():
            mapping[number] = (
                context.get("section")
                if prefer_sections
                else context.get("chapter")
            )

        return mapping, ordered

    def _clear_law_section_navigation(self):
        self.law_section_rows = {}
        self.law_section_buttons = {}

        if not hasattr(self, "law_sections_layout"):
            return

        while self.law_sections_layout.count():
            item = self.law_sections_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.law_sections_layout.addStretch()
        self.law_sections_scroll.hide()

    @staticmethod
    def _compact_section_button_text(title):
        title = re.sub(r"\s+", " ", title or "").strip()
        if len(title) <= 42:
            return title
        return title[:39].rstrip() + "…"

    def _populate_law_section_navigation(self, ordered_sections):
        self._clear_law_section_navigation()
        if not ordered_sections:
            return

        # Remove the stretch temporarily, add buttons, then restore it.
        stretch_item = self.law_sections_layout.takeAt(0)
        del stretch_item

        for section_title in ordered_sections:
            button = QPushButton(
                self._compact_section_button_text(section_title)
            )
            button.setObjectName("lawSectionButton")
            button.setCheckable(True)
            button.setToolTip(section_title)
            button.clicked.connect(
                lambda checked=False, title=section_title:
                self.jump_to_law_section(title)
            )
            self.law_sections_layout.addWidget(button)
            self.law_section_buttons[section_title] = button

        self.law_sections_layout.addStretch()
        self.law_sections_scroll.show()

    def jump_to_law_section(self, section_title):
        row = self.law_section_rows.get(section_title)
        if row is None:
            return

        # Select the first article in the section and keep its header at the top.
        first_article_row = row + 1
        while first_article_row < self.articles_list.count():
            item = self.articles_list.item(first_article_row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and data.get("type") == "article":
                self.articles_list.setCurrentRow(first_article_row)
                break
            first_article_row += 1

        header_item = self.articles_list.item(row)
        if header_item is not None:
            QTimer.singleShot(
                0,
                lambda item=header_item: self.articles_list.scrollToItem(
                    item, QAbstractItemView.ScrollHint.PositionAtTop
                )
            )

        self._set_active_law_section(section_title)

    def _set_active_law_section(self, section_title):
        for title, button in self.law_section_buttons.items():
            button.blockSignals(True)
            button.setChecked(title == section_title)
            button.blockSignals(False)

    def _article_index_from_law_list_row(self, row):
        if row < 0 or row >= self.articles_list.count():
            return None
        item = self.articles_list.item(row)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("type") != "article":
            return None
        index = data.get("article_index")
        if not isinstance(index, int):
            return None
        if index < 0 or index >= len(self.current_articles):
            return None
        return index

    def load_articles(self, row):

        self.articles_list.clear()
        self.article_content.clear()
        self.current_article_sections = {}
        self._clear_law_section_navigation()

        if row < 0 or row >= len(self.laws):
            return

        law = self.laws[row]

        self.current_articles = list(
            self.database.get_articles_by_law(
                law["id"]
            )
        )

        section_map, section_order = self._extract_law_outline(
            law["content"]
        )

        # Keep only sections that actually contain articles present in the DB.
        used_sections = []
        for article in self.current_articles:
            number = self._normalize_outline_article_number(
                article["article_number"]
            )
            section = section_map.get(number)
            if section and section not in used_sections:
                used_sections.append(section)

        ordered_used_sections = [
            section for section in section_order
            if section in used_sections
        ]
        for section in used_sections:
            if section not in ordered_used_sections:
                ordered_used_sections.append(section)

        self._populate_law_section_navigation(ordered_used_sections)

        last_section = object()

        for article_index, article in enumerate(self.current_articles):
            number = self._normalize_outline_article_number(
                article["article_number"]
            )
            section = section_map.get(number)
            self.current_article_sections[article_index] = section

            if section and section != last_section:
                header = QListWidgetItem(section)
                header.setData(
                    Qt.ItemDataRole.UserRole,
                    {"type": "section", "section": section}
                )
                header.setFlags(Qt.ItemFlag.ItemIsEnabled)
                header_font = header.font()
                header_font.setBold(True)
                header_font.setPointSize(header_font.pointSize() + 1)
                header.setFont(header_font)
                header.setForeground(QColor("#6d8cff"))
                header.setToolTip(section)
                self.articles_list.addItem(header)
                self.law_section_rows[section] = self.articles_list.count() - 1

            text = (
                f"Статья "
                f"{article['article_number']}"
            )

            if article["title"]:
                text += (
                    "\n"
                    + article["title"]
                )

            item = QListWidgetItem(text)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "type": "article",
                    "article_index": article_index,
                    "section": section,
                }
            )
            self.articles_list.addItem(item)
            last_section = section

        self.document_title.setText(
            law["title"]
        )

        # Make the first article immediately available without forcing selection
        # when the list is empty.
        for list_row in range(self.articles_list.count()):
            if self._article_index_from_law_list_row(list_row) is not None:
                self.articles_list.setCurrentRow(list_row)
                break

    def show_article(self, row):

        article_index = self._article_index_from_law_list_row(row)
        if article_index is None:
            return

        article = self.current_articles[article_index]

        heading = (
            f"Статья "
            f"{article['article_number']}"
        )

        if article["title"]:
            heading += (
                "\n"
                + article["title"]
            )

        self.document_title.setText(
            heading
        )

        self.article_content.setPlainText(
            article["content"]
        )

        section = self.current_article_sections.get(article_index)
        self._set_active_law_section(section)

        reference = self._current_law_article_ref()
        self._record_article_view(reference)
        self._update_favorite_buttons()

    # =========================================================
    # SEARCH
    # =========================================================

    def update_search_suggestions(self, text):
        """Показывает варианты запроса прямо во время набора текста."""
        query = (text or "").strip()

        if not query:
            self.search_suggestion_model.setStringList([])
            self.search_results = []
            self.search_list.clear()
            self.search_content.clear()
            self.search_count.setText("Введите запрос")
            return

        if len(query) < 2:
            self.search_suggestion_model.setStringList([])
            self.search_count.setText("Продолжайте ввод — появятся варианты поиска…")
            return

        suggestions = self.smart_text_search.suggest(
            query, limit=10, history=self.search_history
        )
        self.search_suggestion_model.setStringList(suggestions)
        self.search_count.setText(
            f"Умные подсказки • вариантов: {len(suggestions)} • выберите вариант или нажмите Enter"
        )

        completer = getattr(self, "search_completer", None)
        if completer is not None and suggestions:
            # Модель уже содержит только релевантные варианты, поэтому показываем весь список.
            completer.setCompletionPrefix("")
            completer.complete()

    def on_search_suggestion_activated(self, suggestion):
        """Подставляет выбранный вариант и сразу выполняет поиск."""
        if not suggestion:
            return
        self.search_input.setText(suggestion)
        self.search_input.setCursorPosition(len(suggestion))
        self.perform_search()

    def run_search_now(self):
        """Run the main search from the Search button."""
        self.perform_search()

    def handle_search_enter(self):
        if self.app_settings.get("enter_runs_search", True):
            self.run_search_now()

    def _parse_smart_article_query(self, query):
        """Parse exact article queries, preserving sub-article numbers."""
        raw = (query or "").strip().lower().replace("ё", "е")
        if not raw:
            return None

        # Accept: 63.1 УК, 63.1 УК РФ, ст. 63.1 УК, статья 9.8 КоАП.
        # Important: keep the full dotted number instead of reducing it to 63.
        number_match = re.search(
            r"(?<!\d)(\d+(?:\s*\.\s*\d+)*)(?!\d)",
            raw
        )
        if not number_match:
            return None

        article_number = re.sub(r"\s+", "", number_match.group(1))

        normalized = re.sub(r"\s+", " ", raw)
        if re.search(r"\bкоап\b", normalized) or "административ" in normalized:
            law_names = [
                "коап",
                "кодекс об административных",
                "административных правонаруш",
            ]
        elif re.search(r"\bук\b", normalized) or "уголов" in normalized:
            law_names = [
                "ук рф",
                "уголовный кодекс",
                "уголовного кодекса",
            ]
        elif re.search(r"\bпдд\b", normalized) or "правила дорожного движения" in normalized:
            law_names = [
                "пдд",
                "правила дорожного движения",
            ]
        else:
            # Without a code abbreviation this is not an exact smart query;
            # let the normal text search handle it.
            return None

        return article_number, law_names


    def _smart_article_search(self, query):
        parsed = self._parse_smart_article_query(query)
        if not parsed:
            return None

        article_number, law_names = parsed
        matches = []

        for law in self.database.get_laws():
            law_title_normalized = law["title"].lower().replace("ё", "е")
            if not any(name in law_title_normalized for name in law_names):
                continue

            for article in self.database.get_articles_by_law(law["id"]):
                stored_number = str(article["article_number"]).strip()
                stored_number = re.sub(r"\s+", "", stored_number).rstrip(".")
                if stored_number != article_number.rstrip("."):
                    continue

                matches.append({
                    "id": article["id"],
                    "article_number": article["article_number"],
                    "article_title": article["title"] or "",
                    "content": article["content"] or "",
                    "law_title": law["title"],
                    "url": law["url"],
                })

        return matches

    def perform_search(self):

        query = self.search_input.text().strip()

        if not query:
            self.search_results = []
            self.search_list.clear()
            self.search_content.clear()
            self.search_count.setText("Введите запрос")
            return

        self.add_search_history(query)
        smart_results = self._smart_article_search(query)

        if smart_results is not None:
            self.search_results = smart_results
            mode = "Точный поиск"
        else:
            self.search_results = list(
                self.smart_text_search.search(
                    query,
                    int(self.app_settings.get("search_limit", 100)),
                )
            )
            mode = "Умный поиск"

        self.search_list.clear()
        self.search_content.clear()

        self.search_count.setText(
            f"{mode} • Найдено: {len(self.search_results)}"
        )

        for result in self.search_results:
            title = result["article_title"] or ""
            text = (
                f"Статья {result['article_number']}\n"
                f"{result['law_title']}"
            )
            if title:
                text += f"\n{title}"
            self.search_list.addItem(text)

        if self.search_results:
            self.search_list.setCurrentRow(0)
        else:
            if smart_results is not None:
                self.search_content.setPlainText(
                    "Точная статья не найдена.\n\n"
                    "Проверьте номер статьи и сокращение кодекса."
                )
            else:
                self.search_content.setPlainText("Ничего не найдено.")

    def show_search_result(
        self,
        row
    ):

        if row < 0:
            return

        if row >= len(
            self.search_results
        ):
            return

        result = (
            self.search_results[row]
        )

        heading = (
            f"{result['law_title']}\n\n"
            f"Статья "
            f"{result['article_number']}"
        )

        if result["article_title"]:
            heading += (
                "\n"
                + result["article_title"]
            )

        self.search_content.setPlainText(
            heading
            + "\n\n"
            + result["content"]
        )
        self._record_article_view(dict(result))
        self._update_favorite_buttons()

    # =========================================================
    # COMMAND PALETTE (Ctrl+K)
    # =========================================================

    def _command_palette_entries(self):
        entries = [
            ("Поиск статьи или ситуации", "поиск search статья", lambda: self.switch_page(self.search_page_index)),
            ("Открыть Калькулятор", "калькулятор calc f9", lambda: self.switch_page(self.calculator_page_index)),
            ("Открыть Памятку", "памятка memo f8", lambda: self.switch_page(self.memo_page_index)),
            ("Открыть Избранное", "избранное favorites профили", lambda: self.switch_page(self.favorites_page_index)),
            ("Открыть Настройки", "настройки settings", lambda: self.switch_page(self.settings_page_index)),
            ("AHK бинды", "ahk бинды рп отыгровки макросы", lambda: self.switch_page(self.ahk_page_index)),
            ("Состояние DeiLaw", "состояние status диагностика", self._command_open_status_settings),
            ("Открыть Отзывы", "отзывы рейтинг review сообщество", lambda: self.switch_page(self.community_page_index)),
            ("Репорты", "репорт баг ошибка чат support reports", self.show_my_bug_reports),
            ("Оставить отзыв", "отзыв рейтинг звезды review", self.show_review_dialog),
            ("Обновить законодательство", "обновить базу законодательство синхронизация", self._command_update_laws),
            ("Прошлые обновления DeiLaw", "история версии программы релизы прошлые обновления", lambda: self.switch_page(self.update_history_page_index)),
            ("Проверить обновление DeiLaw", "обновление программы update", lambda: self.check_program_update(manual=True)),
        ]
        if self.gibdd_charter_page_index is not None:
            entries.append((
                "Открыть Устав",
                "устав charter",
                lambda: self.switch_page(self.gibdd_charter_page_index),
            ))
        else:
            entries.append((
                "Подключить Устав",
                "устав charter подключить",
                self._command_open_charter_settings,
            ))
        return entries

    def _command_update_laws(self):
        self.switch_page(self.update_page_index)
        self.start_database_update()

    def _command_open_charter_settings(self):
        self.switch_page(self.settings_page_index)
        target = getattr(self, "settings_charter_select_button", None)
        self.ensure_tutorial_target_visible(target)

    def _command_open_status_settings(self):
        self.switch_page(self.settings_page_index)
        self.refresh_status_page()
        target = getattr(self, "settings_status_card", None)
        self.ensure_tutorial_target_visible(target)

    def show_command_palette(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("DeiLaw — быстрые действия")
        dialog.setModal(True)
        dialog.resize(620, 430)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("⌨ Быстрые действия — Ctrl+K")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        command_input = QLineEdit()
        command_input.setPlaceholderText(
            "Например: 63.1 УК, калькулятор, устав, настройки, обновить базу…"
        )
        command_input.setClearButtonEnabled(True)
        layout.addWidget(command_input)

        result_list = QListWidget()
        layout.addWidget(result_list, stretch=1)

        hint = QLabel(
            "Выберите действие или просто введите статью/ситуацию и нажмите Enter."
        )
        hint.setObjectName("muted")
        layout.addWidget(hint)

        entries = self._command_palette_entries()

        def refill(value=""):
            query = str(value or "").strip().casefold()
            result_list.clear()
            for label, keywords, _callback in entries:
                if query and query not in (label + " " + keywords).casefold():
                    continue
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, label)
                result_list.addItem(item)
            if result_list.count():
                result_list.setCurrentRow(0)

        def execute():
            raw = command_input.text().strip()
            current = result_list.currentItem()
            selected_label = (
                current.data(Qt.ItemDataRole.UserRole)
                if current is not None
                else None
            )

            if selected_label and (not raw or result_list.count() == 1):
                for label, _keywords, callback in entries:
                    if label == selected_label:
                        dialog.accept()
                        callback()
                        return

            if raw:
                dialog.accept()
                self.switch_page(self.search_page_index)
                self.search_input.setText(raw)
                self.perform_search()
                return

            if current is not None:
                for label, _keywords, callback in entries:
                    if label == selected_label:
                        dialog.accept()
                        callback()
                        return

        command_input.textChanged.connect(refill)
        command_input.returnPressed.connect(execute)
        result_list.itemDoubleClicked.connect(lambda _item: execute())
        refill()
        command_input.setFocus()
        dialog.exec()

    # =========================================================
    # ACTIONS
    # =========================================================

    def copy_current_article(self):

        row = self.articles_list.currentRow()
        article_index = self._article_index_from_law_list_row(row)
        if article_index is None:
            return

        article = self.current_articles[article_index]

        text = (
            f"Статья "
            f"{article['article_number']}\n\n"
            f"{article['content']}"
        )

        QApplication.clipboard().setText(
            text
        )

    def open_current_law(self):

        law_row = (
            self.laws_list
            .currentRow()
        )

        if law_row < 0:
            return

        webbrowser.open(
            self.laws[law_row]["url"]
        )

    # =========================================================
    # DEVELOPER CONTACTS
    # =========================================================

    def _asset_icon_directories(self):
        """Return possible assets/icons folders for source and packaged layouts."""
        script_dir = Path(__file__).resolve().parent
        candidates = [
            script_dir / "assets" / "icons",
            script_dir.parent / "assets" / "icons",
            Path.cwd() / "assets" / "icons",
        ]

        result = []
        for folder in candidates:
            try:
                folder = folder.resolve()
            except Exception:
                pass
            if folder not in result:
                result.append(folder)
        return result

    def _find_platform_icon(self, platform):
        """Find a social-platform icon in assets/icons with flexible filenames."""
        aliases = {
            "vk": ("vk", "vkontakte", "вк"),
            "steam": ("steam",),
            "telegram": ("telegram", "tg"),
        }.get(platform, (platform,))

        extensions = (".ico", ".png", ".svg", ".webp", ".jpg", ".jpeg")

        # Prefer predictable exact file names first.
        exact_names = []
        for alias in aliases:
            for ext in extensions:
                exact_names.extend((
                    f"{alias}{ext}",
                    f"{alias}_icon{ext}",
                    f"{alias} icon{ext}",
                    f"icon_{alias}{ext}",
                    f"icon {alias}{ext}",
                ))

        for folder in self._asset_icon_directories():
            if not folder.exists():
                continue
            for name in exact_names:
                path = folder / name
                if path.exists():
                    return path

        # Fallback: accept files such as telegram-logo.ico or steam_64.png.
        for folder in self._asset_icon_directories():
            if not folder.exists():
                continue
            try:
                files = list(folder.iterdir())
            except Exception:
                continue
            for path in files:
                if not path.is_file() or path.suffix.lower() not in extensions:
                    continue
                stem = path.stem.lower().replace("-", " ").replace("_", " ")
                words = set(stem.split())
                for alias in aliases:
                    alias_low = alias.lower()
                    if alias_low in words or (len(alias_low) > 2 and alias_low in stem):
                        return path

        return None

    def open_developer_link(self, url):
        """Open one of the developer links in the default browser/client."""
        try:
            webbrowser.open(url)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Связь с разработчиком",
                f"Не удалось открыть ссылку.\n\n{exc}",
            )

    def show_developer_contacts(self):
        """Show VK, Steam and Telegram as large clickable platform icons."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Связь с разработчиком")
        dialog.setModal(True)
        dialog.setMinimumWidth(500)
        dialog.setWindowIcon(self.windowIcon())

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title = QLabel("Связь с разработчиком")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Выберите площадку — ссылка откроется в браузере или установленном приложении.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        row = QHBoxLayout()
        row.setSpacing(14)

        contacts = (
            ("vk", "VK", "https://vk.ru/deiziardzm"),
            ("steam", "Steam", "https://steamcommunity.com/id/DeiZi__/"),
            ("telegram", "Telegram", "https://t.me/DeiZiS"),
        )

        light = self.app_settings.get("theme", "dark") == "light"
        contact_palette = self._visual_theme_overlay_palette(light)

        def contact_hex(key):
            r, g, b = contact_palette[key]
            return f"#{r:02x}{g:02x}{b:02x}"

        button_bg = contact_hex("surface")
        button_hover = contact_hex("button_hover")
        border = contact_hex("border")
        text_color = contact_hex("text")
        accent = contact_hex("primary")
        accent_border = contact_hex("primary_border")

        for key, label, url in contacts:
            button = QToolButton(dialog)
            button.setObjectName("developerPlatformButton")
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIconSize(QSize(58, 58))
            button.setFixedSize(130, 105)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"Открыть {label}")

            icon_path = self._find_platform_icon(key)
            if icon_path is not None:
                button.setIcon(QIcon(str(icon_path)))

            button.setStyleSheet(
                f"""
                QToolButton#developerPlatformButton {{
                    background-color: {button_bg};
                    color: {text_color};
                    border: 1px solid {border};
                    border-radius: 12px;
                    padding: 8px;
                    font-weight: 600;
                }}
                QToolButton#developerPlatformButton:hover {{
                    background-color: {button_hover};
                    border-color: {accent_border};
                }}
                QToolButton#developerPlatformButton:pressed {{
                    padding-top: 10px;
                }}
                """
            )
            button.clicked.connect(
                lambda checked=False, link=url: self.open_developer_link(link)
            )
            row.addWidget(button)

        layout.addLayout(row)


        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)

        # Attach the standard DeiLaw click sound to dynamically created buttons.
        QTimer.singleShot(0, self.install_button_sounds)
        dialog.exec()

    # =========================================================
    # FIRST-RUN TUTORIAL
    # =========================================================

    def _database_has_articles(self):
        try:
            stats = self.database.get_stats()
            return int(stats.get("articles") or 0) > 0
        except Exception:
            return False

    def maybe_show_initial_database_notice(self):
        """After onboarding, explain that a fresh install needs a law DB sync.

        Returns True when the user chooses to open the Update page.
        """
        if self._database_has_articles():
            if not self.app_settings.get(
                "initial_database_notice_dismissed", False
            ):
                self.app_settings["initial_database_notice_dismissed"] = True
                self.save_app_settings()
            return False

        if self.app_settings.get("initial_database_notice_dismissed", False):
            return False

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Первый запуск DeiLaw")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("Сначала обновите базу законодательства")
        dialog.setInformativeText(
            "Обучение завершено. На новом компьютере локальная база DeiLaw "
            "ещё пустая.\n\n"
            "Перед использованием поиска, памятки и RP-помощника откройте "
            "вкладку «Обновление» и нажмите «Проверить и обновить».\n\n"
            "После успешного обновления DeiLaw загрузит актуальные документы "
            "и статьи RMRP."
        )

        update_button = dialog.addButton(
            "Перейти в Обновление",
            QMessageBox.ButtonRole.AcceptRole,
        )
        later_button = dialog.addButton(
            "Позже",
            QMessageBox.ButtonRole.RejectRole,
        )
        dialog.setDefaultButton(update_button)
        dialog.exec()

        if dialog.clickedButton() is update_button:

            if self.update_page_index is not None:
                self.switch_page(self.update_page_index)

            if hasattr(self, "update_status"):
                self.update_status.setText(
                    "Первый запуск: обновите локальную базу законодательства"
                )
            if hasattr(self, "update_details"):
                self.update_details.setText(
                    "Нажмите «Проверить и обновить». После завершения "
                    "можно пользоваться поиском, памяткой и RP-помощником."
                )
            if hasattr(self, "start_update_button"):
                QTimer.singleShot(0, self.start_update_button.setFocus)
            return True

        # "Позже" (and closing the message with X) is remembered so the notice
        # does not interrupt every launch. The Update page remains available.
        self.app_settings["initial_database_notice_dismissed"] = True
        self.save_app_settings()
        return False

    def run_first_launch_flow(self):
        """Fresh install flow: tutorial first, database notice afterwards."""
        if self.safe_mode:
            return
        # The tutorial is modal and returns only after Finish, Skip, or closing
        # with X. This guarantees that the database prompt never interrupts it.
        self.maybe_show_first_run_tutorial()

        # After any tutorial exit path (or immediately if onboarding had already
        # been completed), show the database reminder for an empty installation.
        QTimer.singleShot(250, self.maybe_show_initial_database_notice)

    def ensure_tutorial_target_visible(self, target):
        """Scroll the active page so the tutorial target is actually visible."""
        if target is None:
            return

        # Settings is the main long scroll page and was the source of the old
        # spotlight bug where the ring could appear near the taskbar.
        settings_scroll = getattr(self, "settings_scroll", None)
        if (
            settings_scroll is not None
            and getattr(self, "settings_page", None) is not None
            and self.pages.currentWidget() is self.settings_page
        ):
            try:
                settings_scroll.ensureWidgetVisible(target, 70, 70)
                QApplication.processEvents()
            except Exception:
                pass

        # Generic fallback for targets inside any other QScrollArea.
        parent = target.parentWidget() if hasattr(target, "parentWidget") else None
        while parent is not None:
            if isinstance(parent, QScrollArea):
                try:
                    parent.ensureWidgetVisible(target, 50, 50)
                    QApplication.processEvents()
                except Exception:
                    pass
                break
            parent = parent.parentWidget()

    def maybe_show_first_run_tutorial(self):
        """Open the walkthrough once, after the first successful launch."""
        if bool(self.app_settings.get("onboarding_completed", False)):
            return
        self.show_onboarding_tutorial(first_run=True)

    def show_onboarding_tutorial(self, first_run=False):
        """Guided spotlight tour: the interface is shown and explained automatically."""
        # This tour deliberately uses a small floating explanation window instead
        # of a full-screen instruction dialog. Each step opens the real page,
        # highlights the real control and places the explanation next to it.
        dialog = QDialog(self)
        dialog.setObjectName("tutorialDialog")
        dialog.setWindowTitle("Обучение DeiLaw")
        dialog.setModal(True)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dialog.resize(560, 430)
        dialog.setMinimumWidth(500)
        dialog.setMaximumWidth(620)
        if not self.windowIcon().isNull():
            dialog.setWindowIcon(self.windowIcon())

        root = QVBoxLayout(dialog)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        progress = QLabel()
        progress.setObjectName("muted")
        root.addWidget(progress)

        title_label = QLabel()
        title_label.setObjectName("pageTitle")
        title_label.setWordWrap(True)
        root.addWidget(title_label)

        arrow_label = QLabel()
        arrow_label.setWordWrap(True)
        arrow_label.setObjectName("tutorialHint")
        root.addWidget(arrow_label)

        body = QLabel()
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(body, stretch=1)

        footer_note = QLabel(
            "Подсвеченный элемент — тот, о котором сейчас идёт речь. "
            "Переключение разделов происходит автоматически."
        )
        footer_note.setObjectName("muted")
        footer_note.setWordWrap(True)
        root.addWidget(footer_note)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        skip_button = QPushButton("Пропустить")
        back_button = QPushButton("Назад")
        next_button = QPushButton("Далее")
        next_button.setObjectName("primary")
        footer.addWidget(skip_button)
        footer.addStretch()
        footer.addWidget(back_button)
        footer.addWidget(next_button)
        root.addLayout(footer)

        tutorial_pages = [
            {
                "title": f"⚖ DeiLaw v{APP_VERSION} — актуальный обзор",
                "text": (
                    "DeiLaw — помощник по законодательству RMRP для быстрого поиска норм и работы госслужащего во время RP.\n\n"
                    "В текущей версии доступны: умный поиск, полная локальная база законов, Устав УГИБДД, RP Quick Memo, "
                    "калькулятор наказаний, Cloud AI с серверной законкой, история обновлений, репорты, отзывы, настройки "
                    "тем/звуков и быстрые окна F7/F8/F9.\n\n"
                    "Обучение можно в любой момент запустить повторно через Настройки."
                ),
                "demo": "status",
                "hint": "Начнём с общего состояния DeiLaw.",
            },
            {
                "title": "🔄 Локальная законка и её обновление",
                "text": (
                    "Обычный поиск, просмотр законов, памятка и калькулятор используют локальную базу data/laws.db. "
                    "Во вкладке «Обновление» DeiLaw загружает актуальные документы RMRP и сохраняет их на компьютере.\n\n"
                    "После обновления новые редакции сразу доступны локальным функциям программы."
                ),
                "demo": "update",
                "hint": "Этой кнопкой обновляется локальная база законодательства.",
            },
            {
                "title": "🔎 Умный поиск по законодательству",
                "text": (
                    "Можно искать точную статью или писать обычными словами.\n\n"
                    "Примеры:\n"
                    "• 63 УК\n"
                    "• 63.3 УК\n"
                    "• 9.8 КоАП\n"
                    "• 2.2 ПДД\n"
                    "• не остановился по требованию сотрудника ГИБДД\n\n"
                    "Для УК и КоАП DeiLaw показывает содержание и наказание, а для других документов — полный текст найденной нормы."
                ),
                "demo": "search",
                "hint": "Вводи номер статьи или описание ситуации.",
            },
            {
                "title": "🕘 История поиска",
                "text": (
                    "Последние запросы сохраняются в истории, поэтому часто используемые статьи и формулировки можно быстро открыть снова.\n\n"
                    "Подсказки появляются во время ввода, но поиск запускается только после выбора варианта или подтверждения запроса."
                ),
                "demo": "search_history",
                "hint": "Здесь открывается история последних запросов.",
            },
            {
                "title": "⚡ F7 — Quick Search",
                "text": (
                    "F7 открывает быстрый поиск поверх игры. Он использует ту же локальную законку, что и основной поиск.\n\n"
                    "Горячую клавишу и глобальный режим Windows можно изменить в Настройках."
                ),
                "demo": "search_overlay",
                "hint": "Quick Search позволяет проверить статью, не сворачивая игру.",
            },
            {
                "title": "📚 Просмотр законов",
                "text": (
                    "Во вкладке «Законы» можно выбрать конкретный документ и читать его целиком. "
                    "Длинные документы разбиваются на главы/разделы и статьи для быстрой навигации."
                ),
                "demo": "laws",
                "hint": "Выбери нормативный документ для просмотра его структуры.",
            },
            {
                "title": "🚓 Устав УГИБДД",
                "text": (
                    "Устав УГИБДД подключается отдельным DOCX-файлом через Настройки. "
                    "После подключения появляется отдельная вкладка с главами и статьями.\n\n"
                    "Если файл переместить или удалить, вкладка временно исчезнет. Сам DOCX DeiLaw не изменяет."
                ),
                "demo": "charter_tab",
                "hint": "Если Устав ещё не подключён, обучение покажет кнопку выбора DOCX.",
            },
            {
                "title": "📌 Персональная памятка",
                "text": (
                    "В памятке можно собрать часто используемые статьи в свои столбцы и разделы. "
                    "Карточки можно переносить, переименовывать разделы и удалять через контекстное меню.\n\n"
                    "На карточках отображаются номер статьи, краткое описание и наказание — в зависимости от настроек."
                ),
                "demo": "memo",
                "hint": "Добавляй сюда статьи, которые нужны постоянно.",
            },
            {
                "title": "🖥 F8 — RP Quick Memo",
                "text": (
                    "F8 показывает памятку отдельным окном поверх игры. Окно можно настроить по размеру, прозрачности и поведению поверх других окон.\n\n"
                    "Повторное нажатие F8 скрывает Quick Memo."
                ),
                "demo": "memo_overlay",
                "hint": "Это быстрый доступ к памятке во время RP.",
            },
            {
                "title": "🧮 Калькулятор наказаний",
                "text": (
                    "Калькулятор позволяет добавить несколько статей и посчитать штрафы, административный арест и сроки лишения свободы.\n\n"
                    "Если в статье есть диапазон или варианты через «или / либо», DeiLaw не выбирает наказание за пользователя — нужный вариант выбирается вручную."
                ),
                "demo": "calculator_page",
                "hint": "Сюда можно добавить статью по номеру или описанию.",
            },
            {
                "title": "🚀 F9 — Quick Calculator",
                "text": (
                    "F9 открывает калькулятор отдельным быстрым окном поверх игры. "
                    "Обычный калькулятор и Quick Calculator используют один список выбранных статей."
                ),
                "demo": "calculator_overlay",
                "hint": "Quick Calculator вызывается по F9.",
            },
            {
                "title": "☁ DeiLaw Cloud AI — юридический помощник",
                "text": (
                    "RP-помощник теперь работает через Cloud AI. Локальная модель Ollama/Qwen больше не требуется.\n\n"
                    "AI получает сам вопрос и самостоятельно ищет нужные нормы в серверной законке DeiLaw. "
                    "Он больше не зависит от того, какие несколько статей успел подобрать локальный поиск."
                ),
                "demo": "ai",
                "hint": "Опиши вопрос или RP-ситуацию обычным языком.",
            },
            {
                "title": "📖 Cloud AI: запрос конкретной статьи",
                "text": (
                    "Если спросить «63 УК», «63.3 УК», «91 УК» или «9.8 КоАП», Cloud AI ищет именно эту статью в серверной законке.\n\n"
                    "В ответе он объясняет смысл статьи и отдельно указывает, что за неё грозит — только по тексту самой нормы."
                ),
                "demo": "ai",
                "hint": "Можно задавать AI точные номера статей.",
            },
            {
                "title": "🚨 Cloud AI: что нарушил гражданин",
                "text": (
                    "Если описать ситуацию и спросить «что человек нарушил?» или «что можно вменить?», DeiLaw разбирает каждый эпизод отдельно.\n\n"
                    "В качестве нарушений гражданину вменяются только статьи УК и КоАП. "
                    "ПДД, ПК, УПК, ФЗ и уставы используются только как основания, обязанности и процессуальные нормы."
                ),
                "demo": "ai_sources",
                "hint": "Источники рядом с ответом позволяют проверить найденные статьи.",
            },
            {
                "title": "👮 Cloud AI: правовое основание",
                "text": (
                    "Для вопросов вроде «на каком основании сотрудник может остановить машину?» или "
                    "«почему гражданин обязан предъявить документы?» AI ищет прямую разрешающую или обязывающую норму.\n\n"
                    "В таком режиме приоритет получают ПК, УПК, ПДД, ФЗ, уставы и другие профильные документы, "
                    "а УК/КоАП указываются только при необходимости как ответственность."
                ),
                "demo": "ai_sources",
                "hint": "AI отделяет основание полномочия от статьи ответственности.",
            },
            {
                "title": "🗄 Серверная законка Cloud AI",
                "text": (
                    "Cloud AI работает с отдельной серверной копией законки в Supabase. "
                    "Перед ответом сервер сам разбирает вопрос, ищет по всей базе и передаёт модели только подходящие статьи.\n\n"
                    "Это уменьшает риск пропуска нормы и не требует отправлять всю законку в OpenAI при каждом запросе."
                ),
                "demo": "ai_sources",
                "hint": "Список источников показывает, какие нормы сервер нашёл для ответа.",
            },
            {
                "title": "🧾 История изменений законодательства",
                "text": (
                    "При обновлении локальной базы DeiLaw сравнивает старую и новую редакции и показывает, какие статьи были добавлены, изменены или удалены.\n\n"
                    "Это удобно для проверки того, что именно поменялось в законке."
                ),
                "demo": "update_history",
                "hint": "Здесь хранится история изменений законодательства.",
            },
            {
                "title": "🐞 Репорты и чат с разработчиком",
                "text": (
                    "В поддержке используется единый раздел «Репорты». Из него можно создать новый баг-репорт, "
                    "посмотреть свои обращения, увидеть их статус и продолжить чат с разработчиком.\n\n"
                    "При новом ответе разработчика DeiLaw может проиграть отдельную голосовую озвучку. "
                    "Старые сообщения повторно не озвучиваются."
                ),
                "demo": "contacts",
                "hint": "Кнопка «Поддержать автора» всегда видна внизу боковой панели. Через раздел связи/поддержки доступны репорты и переписка с разработчиком.",
            },
            {
                "title": "⭐ Отзывы о DeiLaw",
                "text": (
                    "Пользователь может поставить оценку и оставить публичный отзыв. "
                    "Одинаковые имена разрешены — рядом с автором показывается короткий публичный ID, чтобы различать пользователей.\n\n"
                    "Отзыв привязывается к устройству, а исходные системные идентификаторы публично не отображаются.\n\n"
                    "Если DeiLaw тебе понравился и оказался полезным — можешь оставить отзыв. Это полностью добровольно, "
                    "но помогает другим пользователям понять, подходит ли им программа, а разработчику — видеть обратную связь."
                ),
                "demo": "contacts",
                "hint": "Отзывы находятся в разделе обратной связи с разработчиком.",
            },
            {
                "title": "📊 Состояние и диагностика",
                "text": (
                    "Раздел «Состояние» помогает проверить локальную базу, количество документов/статей, "
                    "горячие клавиши, выбранную тему и другие компоненты программы.\n\n"
                    "Если что-то работает необычно, эту страницу удобно проверить первой."
                ),
                "demo": "status",
                "hint": "Здесь собрана диагностика DeiLaw.",
            },
            {
                "title": "⌨ Горячие клавиши F7 / F8 / F9",
                "text": (
                    "В Настройках можно изменить горячие клавиши Quick Search, Quick Memo и Quick Calculator. "
                    "Для каждого действия можно включить глобальный режим Windows.\n\n"
                    "По умолчанию: F7 — поиск, F8 — памятка, F9 — калькулятор."
                ),
                "demo": "settings_hotkeys",
                "hint": "Здесь настраиваются быстрые клавиши.",
            },
            {
                "title": "🎨 Темы, размеры и звуки",
                "text": (
                    "В Настройках можно менять тему интерфейса, размер элементов и параметры быстрых окон. "
                    "Звуки интерфейса также можно отключать.\n\n"
                    "Уведомление об ответе разработчика на репорт настраивается отдельно, если эта опция доступна в текущей сборке."
                ),
                "demo": "settings_display",
                "hint": "Здесь меняется внешний вид DeiLaw и связанные параметры.",
            },
            {
                "title": "✕ Закрытие и сворачивание",
                "text": (
                    "Для кнопки × можно выбрать действие: закрыть DeiLaw полностью, свернуть программу или каждый раз спрашивать.\n\n"
                    "Если DeiLaw остаётся работать в фоне, глобальные горячие клавиши продолжают действовать."
                ),
                "demo": "settings_close",
                "hint": "Настрой здесь поведение кнопки закрытия.",
            },
            {
                "title": "⬆ Обновление самой программы",
                "text": (
                    "Обновление программы и обновление законодательства — разные вещи. "
                    "DeiLaw может отдельно проверять наличие новой версии приложения и предлагать её установку.\n\n"
                    "Ручная проверка версии доступна в Настройках."
                ),
                "demo": "program_update",
                "hint": "Эта кнопка проверяет новую версию самой DeiLaw.",
            },
            {
                "title": "⚙ Остальные настройки",
                "text": (
                    "В Настройках находятся параметры поиска, памятки, Устава УГИБДД, горячих клавиш, звуков, отображения и других функций.\n\n"
                    "Кнопка «Повторить обучение» запускает этот актуальный тур заново."
                ),
                "demo": "settings",
                "hint": "Отсюда обучение можно запустить повторно.",
            },
            {
                "title": "✅ DeiLaw готов к работе",
                "text": (
                    "Для обычной работы периодически обновляй локальную законку. "
                    "Cloud AI использует серверную законку и помогает разбирать вопросы госслужащего по нормам RMRP.\n\n"
                    "Если AI ошибся, сверяй указанные статьи с источниками. Если нашёл баг программы — отправь репорт через поддержку.\n\n"
                    "Если DeiLaw понравился — буду рад, если ты оставишь отзыв. Это не обязательно, "
                    "но такая обратная связь помогает развивать программу дальше."
                ),
                "demo": "contacts",
                "hint": "На этом обучение завершено.",
            },
        ]

        ring = TutorialTargetRing()
        current_index = 0
        tutorial_overlay = {"window": None}
        pending_timer = {"id": 0}
        closing_by_tour = {"value": False}

        def open_page(page_attr):
            page = getattr(self, page_attr, None)
            if page is None:
                return False
            idx = self.pages.indexOf(page)
            if idx < 0:
                return False
            # Direct page switching is intentional: the tour must not trigger
            # beta/settings confirmation dialogs while it is demonstrating UI.
            self.pages.setCurrentIndex(idx)
            self.update_active_nav(idx)
            if idx == getattr(self, "settings_page_index", -1):
                self.refresh_status_page()
            if idx == getattr(self, "update_history_page_index", -1):
                self.refresh_update_history()
            return True

        def hide_demo_overlay():
            overlay = tutorial_overlay.get("window")
            if overlay is not None:
                try:
                    overlay.hide()
                except Exception:
                    pass
            tutorial_overlay["window"] = None

        def cleanup_visuals():
            pending_timer["id"] += 1
            ring.hide()
            hide_demo_overlay()

        def search_page_after_tour():
            page = getattr(self, "search_page", None)
            if page is None:
                return
            idx = self.pages.indexOf(page)
            if idx >= 0:
                self.pages.setCurrentIndex(idx)
                self.update_active_nav(idx)
                try:
                    self.search_input.setFocus()
                except Exception:
                    pass

        def position_dialog(target, hint):
            # The dialog itself acts as the explanation bubble. It is placed
            # next to the highlighted control and shows a directional arrow.
            dialog.adjustSize()
            dialog.resize(560, max(360, min(500, dialog.sizeHint().height())))

            if target is None or not target.isVisible():
                screen = QApplication.screenAt(self.mapToGlobal(self.rect().center()))
                if screen is None:
                    screen = QApplication.primaryScreen()
                area = screen.availableGeometry() if screen is not None else self.geometry()
                x = area.x() + (area.width() - dialog.width()) // 2
                y = area.y() + (area.height() - dialog.height()) // 2
                dialog.move(x, y)
                arrow_label.setText("●  " + hint)
                return

            top_left = target.mapToGlobal(target.rect().topLeft())
            center = target.mapToGlobal(target.rect().center())
            right = top_left.x() + target.width()
            bottom = top_left.y() + target.height()
            screen = QApplication.screenAt(center)
            if screen is None:
                screen = QApplication.primaryScreen()
            area = screen.availableGeometry() if screen is not None else self.geometry()
            gap = 34
            dw, dh = dialog.width(), dialog.height()

            # Prefer the right side, then left, below and above.
            if right + gap + dw <= area.right():
                x = right + gap
                y = center.y() - dh // 2
                arrow = "⬅"
            elif top_left.x() - gap - dw >= area.left():
                x = top_left.x() - gap - dw
                y = center.y() - dh // 2
                arrow = "➡"
            elif bottom + gap + dh <= area.bottom():
                x = center.x() - dw // 2
                y = bottom + gap
                arrow = "⬆"
            else:
                x = center.x() - dw // 2
                y = top_left.y() - gap - dh
                arrow = "⬇"

            x = max(area.left() + 8, min(x, area.right() - dw - 8))
            y = max(area.top() + 8, min(y, area.bottom() - dh - 8))
            dialog.move(x, y)
            arrow_label.setText(f"{arrow}  {hint}")

        def resolve_target(kind):
            """Open the live feature for one step and return the real widget to highlight."""
            hide_demo_overlay()
            self.show()
            self.raise_()

            target = None
            hint_override = None

            if kind == "search":
                open_page("search_page")
                target = getattr(self, "search_input", None)

            elif kind == "search_history":
                open_page("search_page")
                target = getattr(self, "search_history_button", None)

            elif kind == "laws":
                open_page("laws_page")
                target = getattr(self, "laws_list", None)

            elif kind == "favorites":
                open_page("favorites_page")
                target = getattr(self, "favorites_list", None)

            elif kind == "profiles":
                open_page("favorites_page")
                target = getattr(self, "profile_combo", None)

            elif kind == "profile_manage":
                open_page("favorites_page")
                target = getattr(
                    self,
                    "rename_profile_button",
                    None,
                )

            elif kind == "sidebar":
                target = getattr(self, "sidebar_scroll", None)

            elif kind == "support":
                target = getattr(self, "support_button", None)

            elif kind == "charter_settings":
                open_page("settings_page")
                target = getattr(
                    self,
                    "settings_charter_select_button",
                    None,
                )

            elif kind == "charter_tab":
                if getattr(self, "gibdd_charter_page", None) is not None:
                    open_page("gibdd_charter_page")
                    target = getattr(
                        self,
                        "gibdd_chapters_scroll",
                        None,
                    )
                    if target is None or not target.isVisible():
                        target = getattr(
                            self,
                            "gibdd_charter_nav",
                            None,
                        )
                else:
                    open_page("settings_page")
                    target = getattr(
                        self,
                        "settings_charter_select_button",
                        None,
                    )
                    hint_override = (
                        "Устав ещё не подключён. Нажми «Выбрать DOCX» — "
                        "после выбора здесь появится отдельная вкладка."
                    )

            elif kind == "search_overlay":
                self.show_search_overlay()
                tutorial_overlay["window"] = getattr(
                    self,
                    "search_overlay",
                    None,
                )
                target = getattr(
                    self,
                    "search_overlay_input",
                    None,
                )

            elif kind == "memo":
                open_page("memo_page")
                target = getattr(self, "memo_article_input", None)

            elif kind == "memo_overlay":
                self.show_memo_overlay(auto_fit=True)
                tutorial_overlay["window"] = getattr(
                    self,
                    "memo_overlay",
                    None,
                )
                target = getattr(self, "memo_overlay", None)

            elif kind == "calculator_page":
                open_page("calculator_page")
                target = getattr(self, "calc_article_input", None)

            elif kind == "calculator_overlay":
                self.show_calculator_overlay()
                tutorial_overlay["window"] = getattr(
                    self,
                    "calculator_overlay",
                    None,
                )
                target = getattr(
                    self,
                    "calculator_overlay_input",
                    None,
                )

            elif kind == "ai":
                open_page("assistant_page")
                target = getattr(self, "rp_input", None)

            elif kind == "ai_sources":
                open_page("assistant_page")
                target = getattr(self, "rp_results_list", None)

            elif kind == "ai_training":
                open_page("assistant_page")
                target = getattr(
                    self,
                    "rp_training_info_button",
                    None,
                )

            elif kind == "ai_export":
                open_page("assistant_page")
                target = getattr(self, "rp_export_button", None)

            elif kind == "update":
                open_page("update_page")
                target = getattr(self, "start_update_button", None)

            elif kind == "update_history":
                open_page("update_history_page")
                target = getattr(
                    self,
                    "program_release_list",
                    None,
                )

            elif kind == "ahk":
                open_page("ahk_page")
                target = getattr(self, "ahk_bind_list", None)

            elif kind == "settings_status":
                open_page("settings_page")
                self.refresh_status_page()
                target = getattr(self, "settings_status_card", None)

            elif kind == "program_update":
                open_page("settings_page")
                target = getattr(
                    self,
                    "settings_check_program_update_button",
                    None,
                )

            elif kind == "settings_hotkeys":
                open_page("settings_page")
                target = getattr(self, "settings_search_hotkey", None)

            elif kind == "hotkey_diagnostics":
                open_page("settings_page")
                target = getattr(
                    self,
                    "settings_hotkey_diagnostics_button",
                    None,
                )

            elif kind == "bug_report":
                target = getattr(
                    self,
                    "support_button",
                    None,
                )

            elif kind == "community":
                open_page("community_page")
                target = getattr(
                    self,
                    "community_review_button",
                    None,
                )

            elif kind == "update_channel":
                open_page("settings_page")
                target = getattr(self, "settings_update_channel", None)

            elif kind == "backups":
                open_page("settings_page")
                target = getattr(
                    self,
                    "settings_backup_create_button",
                    None,
                )

            elif kind == "settings_display":
                open_page("settings_page")
                target = getattr(self, "settings_theme_switch", None)

            elif kind == "settings_close":
                open_page("settings_page")
                target = getattr(
                    self,
                    "settings_remember_close_choice",
                    None,
                )

            elif kind == "settings":
                open_page("settings_page")
                target = getattr(
                    self,
                    "settings_tutorial_button",
                    None,
                )

            elif kind == "contacts":
                target = getattr(self, "support_button", None)

            return target, hint_override

        def show_step(index):
            nonlocal current_index
            current_index = max(0, min(index, len(tutorial_pages) - 1))
            pending_timer["id"] += 1
            token = pending_timer["id"]
            ring.hide()

            step = tutorial_pages[current_index]
            progress.setText(f"Шаг {current_index + 1} из {len(tutorial_pages)}")
            title_label.setText(step["title"])
            body.setText(step["text"])
            back_button.setEnabled(current_index > 0)
            next_button.setText("Начать работу" if current_index == len(tutorial_pages) - 1 else "Далее")
            arrow_label.setText("●  " + step.get("hint", ""))

            target, hint_override = resolve_target(step.get("demo"))
            hint = hint_override or step.get("hint", "")

            # Give stacked pages and top-level overlays a moment to lay out,
            # then calculate the final global geometry of the real control.
            def finish_step_visuals():
                if token != pending_timer["id"]:
                    return
                QApplication.processEvents()
                self.ensure_tutorial_target_visible(target)
                QApplication.processEvents()
                highlighted = False
                if target is not None:
                    highlighted = ring.highlight(target)
                else:
                    ring.hide()
                position_dialog(target if highlighted else None, hint)
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
                # The ring is top-level as well; raise it first, then keep the
                # explanation bubble above it.
                if target is not None:
                    ring.raise_()
                    dialog.raise_()

            QTimer.singleShot(90, finish_step_visuals)

        def complete_and_close():
            closing_by_tour["value"] = True
            self.app_settings["onboarding_completed"] = True
            self.save_app_settings()
            dialog.accept()

        def skip_tutorial():
            closing_by_tour["value"] = True
            self.app_settings["onboarding_completed"] = True
            self.save_app_settings()
            dialog.reject()

        def go_back():
            if current_index > 0:
                show_step(current_index - 1)

        def go_next():
            if current_index >= len(tutorial_pages) - 1:
                complete_and_close()
            else:
                show_step(current_index + 1)

        back_button.clicked.connect(go_back)
        next_button.clicked.connect(go_next)
        skip_button.clicked.connect(skip_tutorial)

        QTimer.singleShot(0, self.install_button_sounds)
        QTimer.singleShot(0, lambda: show_step(0))
        result = dialog.exec()

        cleanup_visuals()
        ring.close()
        ring.deleteLater()

        # Closing the X on first run behaves like skipping: do not reopen the
        # tutorial on every launch. Most importantly, every exit path leaves the
        # user on the Search page, exactly where normal work starts.
        if first_run and not bool(self.app_settings.get("onboarding_completed", False)):
            self.app_settings["onboarding_completed"] = True
            self.save_app_settings()
        search_page_after_tour()

    def _update_sidebar_responsiveness(self):
        """Adapt sidebar density and width to the current main-window size."""
        sidebar = getattr(self, "sidebar", None)
        layout = getattr(self, "sidebar_layout", None)
        if sidebar is None or layout is None:
            return

        width = max(1, self.width())
        height = max(1, self.height())

        # Width follows the main window but stays within sane desktop limits.
        if width < 1050:
            sidebar_width = 188
        elif width < 1350:
            sidebar_width = 205
        elif width < 1750:
            sidebar_width = 220
        else:
            sidebar_width = 232
        sidebar.setFixedWidth(sidebar_width)

        # Compact vertical rhythm on small-height windows. A scroll area is
        # still available as a safety net when everything cannot fit.
        if height < 680:
            margins = (10, 12, 10, 10)
            spacing = 5
            button_height = 28
            nav_font = 11
            show_support_hint = False
            show_stats = False
        elif height < 820:
            margins = (12, 16, 12, 12)
            spacing = 7
            button_height = 31
            nav_font = 11
            show_support_hint = False
            show_stats = True
        elif height < 980:
            margins = (14, 19, 14, 14)
            spacing = 9
            button_height = 34
            nav_font = 12
            show_support_hint = True
            show_stats = True
        else:
            margins = (18, 24, 18, 20)
            spacing = 12
            button_height = 36
            nav_font = 12
            show_support_hint = True
            show_stats = True

        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)

        for button in getattr(self, "nav_buttons", []):
            if button is None:
                continue
            button.setMinimumHeight(button_height)
            button.setMaximumHeight(button_height + 4)
            font = button.font()
            font.setPointSize(nav_font)
            button.setFont(font)

        support_button = getattr(self, "support_button", None)
        if support_button is not None:
            support_button.setMinimumHeight(button_height + 2)
            support_button.setMaximumHeight(button_height + 6)
            font = support_button.font()
            font.setPointSize(nav_font)
            support_button.setFont(font)

        support_hint = getattr(self, "support_hint_label", None)
        if support_hint is not None:
            support_hint.setVisible(show_support_hint)

        stats = getattr(self, "stats_label", None)
        if stats is not None:
            stats.setVisible(show_stats)

        description = getattr(self, "sidebar_description", None)
        if description is not None:
            description.setVisible(height >= 620)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_sidebar_responsiveness()

    # =========================================================
    # HELPERS
    # =========================================================

    def nav_button(self, text):

        button = QPushButton(text)

        button.setObjectName(
            "navButton"
        )

        button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        return button

    # =========================================================
    # STYLE
    # =========================================================

    def _visual_theme_name(self):
        if getattr(self, "safe_mode", False):
            return "default"
        value = str(
            self.app_settings.get("visual_theme", "default")
            or "default"
        ).strip().lower()
        return value if value in (
            "default",
            "retro",
            "neon",
            "gradient",
            "moscow_night",
            "police_blue",
            "crimson",
            "amoled",
            "terminal",
            "cyber_blue",
            "arctic",
            "carbon",
            "midnight_purple",
            "amber",
            "government",
            "rainy_moscow",
            "hazard",
            "paper",
            "deep_space",
        ) else "default"

    def _visual_theme_overlay_palette(self, light=False):
        """Colors shared by Quick Memo, F7 and F9 for each visual theme."""
        name = self._visual_theme_name()

        palettes = {
            ("default", False): {
                "dialog": (12, 14, 18),
                "surface": (24, 27, 33),
                "button": (30, 34, 42),
                "button_hover": (45, 51, 63),
                "border": (78, 84, 98),
                "text": (248, 249, 252),
                "muted": (169, 178, 199),
                "handle": (105, 112, 130),
                "selected": (68, 91, 160),
                "selected_text": (255, 255, 255),
                "primary": (67, 94, 205),
                "primary_border": (89, 116, 235),
            },
            ("default", True): {
                "dialog": (247, 249, 252),
                "surface": (255, 255, 255),
                "button": (239, 242, 247),
                "button_hover": (226, 231, 239),
                "border": (190, 197, 208),
                "text": (30, 34, 41),
                "muted": (95, 103, 118),
                "handle": (168, 176, 190),
                "selected": (215, 226, 255),
                "selected_text": (25, 39, 76),
                "primary": (79, 107, 237),
                "primary_border": (109, 140, 255),
            },
            ("retro", False): {
                "dialog": (24, 16, 10),
                "surface": (38, 25, 15),
                "button": (49, 32, 18),
                "button_hover": (68, 44, 23),
                "border": (125, 86, 45),
                "text": (255, 232, 188),
                "muted": (198, 165, 115),
                "handle": (143, 102, 56),
                "selected": (98, 63, 25),
                "selected_text": (255, 241, 208),
                "primary": (180, 105, 38),
                "primary_border": (222, 151, 64),
            },
            ("retro", True): {
                "dialog": (255, 248, 232),
                "surface": (255, 253, 245),
                "button": (244, 231, 203),
                "button_hover": (235, 215, 177),
                "border": (190, 151, 96),
                "text": (74, 49, 29),
                "muted": (128, 91, 56),
                "handle": (177, 135, 82),
                "selected": (238, 209, 161),
                "selected_text": (82, 48, 18),
                "primary": (172, 91, 30),
                "primary_border": (197, 116, 43),
            },
            ("neon", False): {
                "dialog": (7, 8, 24),
                "surface": (13, 17, 38),
                "button": (17, 24, 49),
                "button_hover": (24, 37, 67),
                "border": (42, 205, 217),
                "text": (227, 253, 255),
                "muted": (137, 205, 221),
                "handle": (81, 87, 145),
                "selected": (24, 70, 91),
                "selected_text": (235, 255, 255),
                "primary": (151, 48, 214),
                "primary_border": (36, 223, 232),
            },
            ("neon", True): {
                "dialog": (241, 251, 255),
                "surface": (255, 255, 255),
                "button": (230, 246, 251),
                "button_hover": (214, 238, 247),
                "border": (89, 174, 195),
                "text": (25, 48, 61),
                "muted": (72, 113, 132),
                "handle": (116, 157, 178),
                "selected": (207, 239, 246),
                "selected_text": (20, 64, 76),
                "primary": (111, 62, 185),
                "primary_border": (33, 166, 190),
            },
            ("gradient", False): {
                "dialog": (14, 14, 34),
                "surface": (26, 25, 52),
                "button": (35, 34, 69),
                "button_hover": (50, 46, 91),
                "border": (92, 88, 154),
                "text": (247, 245, 255),
                "muted": (181, 174, 214),
                "handle": (105, 99, 163),
                "selected": (65, 59, 130),
                "selected_text": (255, 255, 255),
                "primary": (98, 81, 226),
                "primary_border": (145, 111, 239),
            },
            ("gradient", True): {
                "dialog": (247, 247, 255),
                "surface": (255, 255, 255),
                "button": (238, 237, 251),
                "button_hover": (225, 225, 245),
                "border": (170, 164, 207),
                "text": (43, 40, 66),
                "muted": (101, 96, 132),
                "handle": (151, 146, 189),
                "selected": (225, 220, 250),
                "selected_text": (55, 45, 96),
                "primary": (91, 78, 208),
                "primary_border": (129, 104, 225),
            },
            ("moscow_night", False): {
                "dialog": (8, 13, 21), "surface": (14, 23, 35),
                "button": (20, 32, 47), "button_hover": (28, 46, 67),
                "border": (50, 76, 103), "text": (239, 246, 255),
                "muted": (137, 158, 185), "handle": (75, 101, 130),
                "selected": (28, 72, 119), "selected_text": (255, 255, 255),
                "primary": (34, 111, 194), "primary_border": (65, 151, 239),
            },
            ("moscow_night", True): {
                "dialog": (239, 246, 252), "surface": (250, 253, 255),
                "button": (226, 237, 247), "button_hover": (210, 227, 241),
                "border": (146, 173, 198), "text": (24, 44, 62),
                "muted": (83, 108, 130), "handle": (129, 158, 184),
                "selected": (197, 223, 246), "selected_text": (15, 50, 80),
                "primary": (33, 104, 183), "primary_border": (60, 142, 219),
            },
            ("police_blue", False): {
                "dialog": (7, 15, 28), "surface": (11, 27, 49),
                "button": (16, 39, 69), "button_hover": (22, 53, 91),
                "border": (39, 92, 148), "text": (240, 247, 255),
                "muted": (133, 169, 206), "handle": (75, 121, 169),
                "selected": (22, 74, 129), "selected_text": (255, 255, 255),
                "primary": (25, 105, 220), "primary_border": (64, 151, 255),
            },
            ("police_blue", True): {
                "dialog": (242, 248, 255), "surface": (255, 255, 255),
                "button": (228, 240, 253), "button_hover": (211, 230, 250),
                "border": (132, 171, 213), "text": (22, 47, 75),
                "muted": (76, 113, 150), "handle": (118, 159, 199),
                "selected": (193, 221, 252), "selected_text": (17, 59, 103),
                "primary": (27, 104, 214), "primary_border": (52, 132, 235),
            },
            ("crimson", False): {
                "dialog": (15, 10, 12), "surface": (27, 17, 21),
                "button": (38, 23, 29), "button_hover": (56, 30, 38),
                "border": (104, 42, 54), "text": (252, 241, 243),
                "muted": (190, 141, 151), "handle": (124, 63, 75),
                "selected": (105, 29, 43), "selected_text": (255, 255, 255),
                "primary": (164, 18, 38), "primary_border": (216, 39, 61),
            },
            ("crimson", True): {
                "dialog": (253, 246, 247), "surface": (255, 255, 255),
                "button": (248, 230, 233), "button_hover": (241, 211, 217),
                "border": (196, 133, 145), "text": (63, 29, 35),
                "muted": (125, 79, 88), "handle": (177, 111, 124),
                "selected": (244, 195, 204), "selected_text": (99, 19, 35),
                "primary": (162, 17, 37), "primary_border": (196, 32, 51),
            },
            ("amoled", False): {
                "dialog": (0, 0, 0), "surface": (5, 5, 6),
                "button": (11, 11, 13), "button_hover": (21, 21, 25),
                "border": (43, 43, 49), "text": (250, 250, 252),
                "muted": (150, 150, 158), "handle": (75, 75, 83),
                "selected": (30, 47, 83), "selected_text": (255, 255, 255),
                "primary": (74, 112, 220), "primary_border": (101, 142, 255),
            },
            ("amoled", True): {
                "dialog": (255, 255, 255), "surface": (252, 252, 253),
                "button": (241, 241, 243), "button_hover": (229, 229, 232),
                "border": (188, 188, 194), "text": (18, 18, 21),
                "muted": (95, 95, 102), "handle": (151, 151, 158),
                "selected": (218, 227, 251), "selected_text": (24, 40, 79),
                "primary": (67, 100, 202), "primary_border": (91, 127, 229),
            },
            ("terminal", False): {
                "dialog": (3, 9, 6), "surface": (6, 17, 11),
                "button": (8, 26, 16), "button_hover": (12, 39, 23),
                "border": (31, 112, 65), "text": (202, 255, 220),
                "muted": (116, 189, 141), "handle": (58, 132, 82),
                "selected": (15, 82, 43), "selected_text": (226, 255, 235),
                "primary": (25, 166, 82), "primary_border": (67, 226, 127),
            },
            ("terminal", True): {
                "dialog": (244, 252, 247), "surface": (255, 255, 255),
                "button": (226, 243, 232), "button_hover": (208, 234, 216),
                "border": (117, 170, 136), "text": (26, 66, 40),
                "muted": (75, 126, 91), "handle": (109, 157, 124),
                "selected": (194, 229, 205), "selected_text": (18, 74, 36),
                "primary": (31, 138, 70), "primary_border": (48, 174, 91),
            },
            ("cyber_blue", False): {
                "dialog": (4, 10, 23), "surface": (8, 19, 39),
                "button": (11, 29, 56), "button_hover": (14, 43, 77),
                "border": (21, 120, 168), "text": (226, 249, 255),
                "muted": (116, 187, 211), "handle": (53, 115, 146),
                "selected": (9, 81, 118), "selected_text": (239, 254, 255),
                "primary": (0, 151, 209), "primary_border": (0, 207, 255),
            },
            ("cyber_blue", True): {
                "dialog": (239, 249, 253), "surface": (255, 255, 255),
                "button": (220, 241, 248), "button_hover": (198, 230, 242),
                "border": (97, 178, 204), "text": (19, 60, 75),
                "muted": (73, 126, 145), "handle": (117, 170, 189),
                "selected": (186, 227, 240), "selected_text": (9, 67, 84),
                "primary": (0, 130, 180), "primary_border": (0, 166, 216),
            },
            ("arctic", False): {
                "dialog": (10, 18, 27), "surface": (17, 29, 41),
                "button": (23, 39, 55), "button_hover": (31, 53, 73),
                "border": (77, 118, 151), "text": (239, 249, 255),
                "muted": (151, 182, 201), "handle": (91, 128, 153),
                "selected": (42, 82, 114), "selected_text": (255, 255, 255),
                "primary": (75, 149, 198), "primary_border": (117, 190, 233),
            },
            ("arctic", True): {
                "dialog": (244, 250, 253), "surface": (255, 255, 255),
                "button": (230, 241, 247), "button_hover": (214, 232, 241),
                "border": (156, 189, 207), "text": (31, 57, 72),
                "muted": (89, 121, 139), "handle": (139, 172, 189),
                "selected": (206, 230, 241), "selected_text": (29, 66, 83),
                "primary": (71, 143, 188), "primary_border": (99, 174, 215),
            },
            ("carbon", False): {
                "dialog": (13, 14, 16), "surface": (24, 25, 28),
                "button": (33, 34, 38), "button_hover": (46, 48, 53),
                "border": (76, 79, 87), "text": (238, 239, 241),
                "muted": (154, 157, 164), "handle": (95, 98, 106),
                "selected": (58, 61, 68), "selected_text": (255, 255, 255),
                "primary": (118, 126, 141), "primary_border": (165, 173, 188),
            },
            ("carbon", True): {
                "dialog": (243, 244, 246), "surface": (255, 255, 255),
                "button": (232, 234, 238), "button_hover": (217, 220, 225),
                "border": (171, 175, 182), "text": (42, 44, 49),
                "muted": (104, 108, 115), "handle": (145, 150, 158),
                "selected": (211, 214, 220), "selected_text": (41, 43, 48),
                "primary": (91, 99, 113), "primary_border": (125, 134, 149),
            },
            ("midnight_purple", False): {
                "dialog": (10, 7, 22), "surface": (19, 13, 38),
                "button": (28, 19, 53), "button_hover": (42, 28, 76),
                "border": (95, 63, 143), "text": (247, 239, 255),
                "muted": (183, 153, 214), "handle": (116, 82, 154),
                "selected": (75, 46, 116), "selected_text": (255, 255, 255),
                "primary": (129, 75, 200), "primary_border": (172, 107, 238),
            },
            ("midnight_purple", True): {
                "dialog": (248, 244, 253), "surface": (255, 255, 255),
                "button": (235, 226, 247), "button_hover": (222, 208, 240),
                "border": (180, 155, 207), "text": (63, 44, 82),
                "muted": (116, 91, 140), "handle": (157, 128, 186),
                "selected": (220, 201, 239), "selected_text": (73, 42, 105),
                "primary": (119, 70, 184), "primary_border": (151, 94, 211),
            },
            ("amber", False): {
                "dialog": (15, 11, 5), "surface": (28, 20, 8),
                "button": (42, 29, 10), "button_hover": (60, 41, 13),
                "border": (130, 88, 25), "text": (255, 239, 202),
                "muted": (205, 163, 87), "handle": (147, 103, 39),
                "selected": (103, 64, 15), "selected_text": (255, 247, 224),
                "primary": (201, 123, 17), "primary_border": (245, 168, 45),
            },
            ("amber", True): {
                "dialog": (255, 249, 237), "surface": (255, 255, 255),
                "button": (249, 233, 201), "button_hover": (241, 218, 170),
                "border": (207, 167, 96), "text": (79, 55, 21),
                "muted": (133, 98, 48), "handle": (183, 144, 82),
                "selected": (242, 210, 148), "selected_text": (88, 53, 11),
                "primary": (184, 106, 8), "primary_border": (219, 139, 21),
            },
            ("government", False): {
                "dialog": (8, 16, 29), "surface": (14, 27, 48),
                "button": (20, 38, 65), "button_hover": (28, 51, 84),
                "border": (63, 91, 126), "text": (245, 248, 252),
                "muted": (147, 164, 185), "handle": (83, 106, 134),
                "selected": (34, 65, 105), "selected_text": (255, 255, 255),
                "primary": (37, 74, 128), "primary_border": (177, 45, 55),
            },
            ("government", True): {
                "dialog": (246, 248, 251), "surface": (255, 255, 255),
                "button": (233, 238, 245), "button_hover": (219, 227, 237),
                "border": (162, 175, 193), "text": (35, 48, 65),
                "muted": (96, 109, 126), "handle": (140, 153, 170),
                "selected": (213, 224, 239), "selected_text": (31, 55, 84),
                "primary": (44, 77, 123), "primary_border": (166, 48, 57),
            },
            ("rainy_moscow", False): {
                "dialog": (9, 14, 19), "surface": (15, 25, 32),
                "button": (22, 35, 45), "button_hover": (31, 49, 62),
                "border": (62, 96, 113), "text": (232, 245, 248),
                "muted": (132, 162, 172), "handle": (77, 112, 126),
                "selected": (41, 79, 94), "selected_text": (255, 255, 255),
                "primary": (54, 128, 151), "primary_border": (89, 178, 198),
            },
            ("rainy_moscow", True): {
                "dialog": (241, 247, 249), "surface": (255, 255, 255),
                "button": (225, 237, 240), "button_hover": (210, 227, 232),
                "border": (144, 177, 185), "text": (33, 59, 66),
                "muted": (87, 119, 126), "handle": (128, 161, 169),
                "selected": (198, 224, 230), "selected_text": (28, 68, 76),
                "primary": (49, 121, 143), "primary_border": (78, 156, 175),
            },
            ("hazard", False): {
                "dialog": (9, 9, 7), "surface": (20, 19, 12),
                "button": (32, 30, 16), "button_hover": (48, 44, 19),
                "border": (128, 112, 25), "text": (255, 244, 169),
                "muted": (195, 176, 89), "handle": (145, 128, 44),
                "selected": (97, 84, 17), "selected_text": (255, 248, 187),
                "primary": (202, 177, 20), "primary_border": (255, 222, 39),
            },
            ("hazard", True): {
                "dialog": (255, 252, 234), "surface": (255, 255, 255),
                "button": (248, 239, 188), "button_hover": (239, 225, 154),
                "border": (200, 179, 78), "text": (68, 61, 22),
                "muted": (120, 107, 54), "handle": (173, 155, 72),
                "selected": (235, 218, 132), "selected_text": (69, 58, 9),
                "primary": (179, 148, 5), "primary_border": (211, 178, 12),
            },
            ("paper", False): {
                "dialog": (29, 25, 20), "surface": (40, 34, 27),
                "button": (52, 44, 34), "button_hover": (69, 58, 43),
                "border": (111, 93, 69), "text": (245, 232, 207),
                "muted": (185, 166, 135), "handle": (127, 105, 78),
                "selected": (87, 67, 44), "selected_text": (255, 243, 218),
                "primary": (132, 68, 51), "primary_border": (177, 92, 68),
            },
            ("paper", True): {
                "dialog": (250, 246, 235), "surface": (255, 252, 244),
                "button": (242, 233, 215), "button_hover": (232, 219, 194),
                "border": (185, 164, 128), "text": (56, 46, 34),
                "muted": (114, 96, 72), "handle": (158, 136, 101),
                "selected": (226, 207, 174), "selected_text": (72, 50, 32),
                "primary": (130, 63, 48), "primary_border": (160, 80, 59),
            },
            ("deep_space", False): {
                "dialog": (5, 7, 20), "surface": (10, 14, 34),
                "button": (16, 22, 49), "button_hover": (25, 32, 69),
                "border": (58, 72, 131), "text": (237, 241, 255),
                "muted": (146, 157, 204), "handle": (77, 89, 148),
                "selected": (45, 53, 111), "selected_text": (255, 255, 255),
                "primary": (88, 95, 202), "primary_border": (128, 111, 233),
            },
            ("deep_space", True): {
                "dialog": (245, 246, 253), "surface": (255, 255, 255),
                "button": (231, 233, 247), "button_hover": (217, 220, 240),
                "border": (160, 166, 207), "text": (43, 47, 78),
                "muted": (99, 105, 143), "handle": (139, 145, 185),
                "selected": (207, 211, 239), "selected_text": (49, 51, 101),
                "primary": (82, 86, 182), "primary_border": (112, 103, 212),
            },
        }
        return palettes[(name, bool(light))]

    def _visual_theme_qss(self, light=False):
        """Theme-specific layer appended over the standard dark/light QSS."""
        name = self._visual_theme_name()
        if name == "default":
            return ""

        new_presets = {
            ("moscow_night", False): ("#080d15", "#09111b", "#0e1a28", "#29435d", "#dfeeff", "#819bb5", "#246fc2", "#194b7d"),
            ("moscow_night", True): ("#eff6fc", "#f7fbff", "#ffffff", "#a9c2d8", "#183851", "#607f99", "#236eb5", "#c7dff4"),
            ("police_blue", False): ("#07111f", "#09182b", "#0d2038", "#285b92", "#eaf5ff", "#82a9cf", "#1969dc", "#174c83"),
            ("police_blue", True): ("#f1f7fe", "#ffffff", "#ffffff", "#9bc0e4", "#173b61", "#577fa5", "#1b68d6", "#c6def7"),
            ("crimson", False): ("#0f0a0c", "#110b0e", "#1b1115", "#652b37", "#fff1f3", "#b98690", "#a41226", "#6f2030"),
            ("crimson", True): ("#fdf5f6", "#fffafb", "#ffffff", "#d7a5ae", "#541e29", "#8d6069", "#a21125", "#f1c8cf"),
            ("amoled", False): ("#000000", "#000000", "#050506", "#29292e", "#ffffff", "#8e8e96", "#4a70dc", "#1e2f53"),
            ("amoled", True): ("#ffffff", "#ffffff", "#fcfcfd", "#c7c7cc", "#111113", "#65656c", "#4364ca", "#dce5fb"),
            ("terminal", False): ("#030906", "#04100a", "#06130c", "#1d6a3d", "#6aff9d", "#75bb8c", "#19a652", "#0f522b"),
            ("terminal", True): ("#f3fbf6", "#f9fffb", "#ffffff", "#8ab89a", "#17552d", "#507e60", "#1f8a46", "#c8e8d2"),
            ("cyber_blue", False): ("#040a17", "#07152a", "#0b1e39", "#1578a8", "#e2fbff", "#74bbd3", "#0097d1", "#095176"),
            ("cyber_blue", True): ("#eff9fd", "#f7fdff", "#ffffff", "#74b6cd", "#153c4c", "#507f91", "#0082b4", "#bae3f0"),
            ("arctic", False): ("#0a121b", "#0e1b28", "#142635", "#4d7697", "#eff9ff", "#97b6c9", "#4b95c6", "#2a5272"),
            ("arctic", True): ("#f4fafd", "#fbfdff", "#ffffff", "#9cbfcf", "#1f3948", "#59798b", "#478fbc", "#cee6f1"),
            ("carbon", False): ("#0d0e10", "#111214", "#18191c", "#4c4f57", "#eef0f2", "#9a9da4", "#767e8d", "#3a3d44"),
            ("carbon", True): ("#f3f4f6", "#fafbfc", "#ffffff", "#abadb6", "#2a2c31", "#686c73", "#5b6371", "#d3d6dc"),
            ("midnight_purple", False): ("#0a0716", "#100a22", "#17102e", "#5f3f8f", "#f7efff", "#b799d6", "#814bc8", "#4b2e74"),
            ("midnight_purple", True): ("#f8f4fd", "#fcfaff", "#ffffff", "#b49bcf", "#3f2c52", "#745b8c", "#7746b8", "#dcc9ef"),
            ("amber", False): ("#0f0b05", "#171006", "#211709", "#825819", "#ffefca", "#cda357", "#c97b11", "#67400f"),
            ("amber", True): ("#fff9ed", "#fffcf7", "#ffffff", "#cfa760", "#4f3715", "#856230", "#b86a08", "#f2d294"),
            ("government", False): ("#08101d", "#0b192d", "#0e213b", "#3f5b7e", "#f5f8fc", "#93a4b9", "#254a80", "#224169"),
            ("government", True): ("#f6f8fb", "#ffffff", "#ffffff", "#a2afc1", "#233041", "#606d7e", "#2c4d7b", "#d5e0ef"),
            ("rainy_moscow", False): ("#090e13", "#0d171e", "#0f2028", "#3e6071", "#e8f5f8", "#84a2ac", "#368097", "#294f5e"),
            ("rainy_moscow", True): ("#f1f7f9", "#f8fcfd", "#ffffff", "#90b1b9", "#213b42", "#57777e", "#31798f", "#c6e0e6"),
            ("hazard", False): ("#090907", "#111009", "#18170c", "#807019", "#fff4a9", "#c3b059", "#cab114", "#615411"),
            ("hazard", True): ("#fffcea", "#fffef5", "#ffffff", "#c8b34e", "#443d16", "#786b36", "#b39405", "#ebda84"),
            ("paper", False): ("#1d1914", "#251f19", "#2d261f", "#6f5d45", "#f5e8cf", "#b9a687", "#844433", "#57432c"),
            ("paper", True): ("#faf6eb", "#fffaf1", "#fffdf7", "#b9a480", "#382e22", "#726048", "#823f30", "#e2cfae"),
            ("deep_space", False): ("#050714", "#080b1c", "#0d112b", "#3a4883", "#edf1ff", "#929dcc", "#585fca", "#2d356f"),
            ("deep_space", True): ("#f5f6fd", "#fbfbff", "#ffffff", "#a0a6cf", "#2b2f4e", "#63698f", "#5256b6", "#cfd3ef"),
        }
        cfg = new_presets.get((name, bool(light)))
        if cfg is not None:
            main_bg, sidebar_bg, card_bg, border, title, muted, primary, selected = cfg
            return f"""
                QMainWindow, QDialog {{ background: {main_bg}; }}
                QFrame#sidebar {{
                    background: {sidebar_bg};
                    border-right: 1px solid {border};
                }}
                QFrame#card {{
                    background: {card_bg};
                    border: 1px solid {border};
                }}
                QLabel#logo, QLabel#pageTitle {{ color: {title}; }}
                QLabel#muted {{ color: {muted}; }}
                QPushButton#navButton:hover {{ background: {card_bg}; }}
                QPushButton#navButton:checked {{
                    background: {selected};
                    border: 1px solid {primary};
                    color: {title};
                    font-weight: 700;
                }}
                QProgressBar::chunk {{ background: {primary}; }}
                QSplitter::handle {{ background: {border}; }}
                QSplitter::handle:hover {{ background: {primary}; }}
                QWidget#settingsPage,
                QScrollArea#settingsScroll,
                QWidget#settingsViewport,
                QWidget#settingsContent {{
                    background: {main_bg};
                    border: none;
                }}
                QWidget#settingsContent QFrame#card {{ background: {card_bg}; }}
                QFrame#settingsSeparator {{ background: {border}; }}
                QMenu {{
                    background: {card_bg};
                    border: 1px solid {border};
                }}
                QMenu::item:selected {{ background: {selected}; }}
                QLabel#memoOverlayArticleCard {{
                    background: {card_bg};
                    border: 1px solid {border};
                }}
            """

        if name == "retro":
            if light:
                return """
                    QMainWindow, QDialog {
                        background: qlineargradient(
                            x1:0, y1:0, x2:1, y2:1,
                            stop:0 #fff8e9, stop:0.52 #f5e8c9, stop:1 #e9d3aa
                        );
                    }
                    QFrame#sidebar { background: #f4e5c8; border-right: 1px solid #bd9560; }
                    QFrame#card { background: rgba(255, 251, 240, 235); border: 1px solid #c9a46f; }
                    QLabel#logo, QLabel#pageTitle { color: #5b351d; }
                    QLabel#muted { color: #8b6643; }
                    QPushButton#navButton:hover { background: #ead2a8; }
                    QPushButton#navButton:checked {
                        background: #e6bf7c; border: 1px solid #aa652b; color: #633716;
                    }
                    QPushButton, QToolButton { background: #f8edda; border: 1px solid #c6a174; color: #51351f; }
                    QPushButton:hover, QToolButton:hover { background: #ecd7b4; }
                    QPushButton#primary {
                        background: #ad5f25; border: 1px solid #c67835; color: #fff9ed;
                    }
                    QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                    QSpinBox, QComboBox, QKeySequenceEdit {
                        background: rgba(255, 253, 246, 245); color: #4b321f;
                        border: 1px solid #c7a172;
                        selection-background-color: #efd4a1; selection-color: #593318;
                    }
                    QListWidget::item:hover { background: #f1dfbf; }
                    QListWidget::item:selected { background: #e8c789; color: #5a3519; }
                    QProgressBar::chunk { background: #b86b2b; }
                    QSplitter::handle { background: #c6a16f; }
                    QWidget#settingsPage, QScrollArea#settingsScroll,
                    QWidget#settingsViewport, QWidget#settingsContent {
                        background: #f7ecd5; border: none;
                    }
                    QWidget#settingsContent QFrame#card {
                        background: rgba(255, 251, 240, 235);
                    }
                    QMenu { background: #fff8e8; color: #4b321f; border: 1px solid #c7a172; }
                    QMenu::item:selected { background: #ead0a0; color: #573217; }
                """
            return """
                QMainWindow, QDialog {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:1,
                        stop:0 #120d09, stop:0.52 #24170e, stop:1 #382415
                    );
                }
                QWidget { color: #ffe7b8; }
                QFrame#sidebar { background: #17100b; border-right: 1px solid #664321; }
                QFrame#card { background: rgba(42, 27, 16, 235); border: 1px solid #75502b; }
                QLabel#logo, QLabel#pageTitle { color: #ffd48a; }
                QLabel#muted { color: #c39a64; }
                QPushButton#navButton:hover { background: #352218; }
                QPushButton#navButton:checked {
                    background: #5c3a18; border: 1px solid #d29543; color: #ffe8bd;
                }
                QPushButton, QToolButton { background: #342216; border: 1px solid #674725; color: #fbe0ad; }
                QPushButton:hover, QToolButton:hover { background: #4a301b; }
                QPushButton#primary {
                    background: #ae6728; border: 1px solid #d89c45; color: #fff0cb;
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QSpinBox, QComboBox, QKeySequenceEdit {
                    background: #21170f; color: #ffe5b2; border: 1px solid #674725;
                    selection-background-color: #6c471d; selection-color: #fff4d6;
                }
                QListWidget::item:hover { background: #382619; }
                QListWidget::item:selected { background: #65421c; color: #fff1cf; }
                QProgressBar::chunk { background: #c98032; }
                QSplitter::handle { background: #6e4c2a; }
                QWidget#settingsPage, QScrollArea#settingsScroll,
                QWidget#settingsViewport, QWidget#settingsContent {
                    background: #17100b; border: none;
                }
                QWidget#settingsContent QFrame#card {
                    background: rgba(42, 27, 16, 235);
                }
                QMenu { background: #271a11; color: #ffe5b2; border: 1px solid #674725; }
                QMenu::item:selected { background: #60401d; color: #fff1cf; }
            """

        if name == "neon":
            if light:
                return """
                    QMainWindow, QDialog {
                        background: qlineargradient(
                            x1:0, y1:0, x2:1, y2:1,
                            stop:0 #effcff, stop:0.48 #eef7ff, stop:1 #f8efff
                        );
                    }
                    QFrame#sidebar { background: #f3fbff; border-right: 1px solid #86cad8; }
                    QFrame#card { background: rgba(255,255,255,238); border: 1px solid #8bd0db; }
                    QLabel#logo, QLabel#pageTitle { color: #493371; }
                    QLabel#muted { color: #597b8c; }
                    QPushButton#navButton:hover { background: #dff5fa; }
                    QPushButton#navButton:checked {
                        background: #d6f3f8; border: 1px solid #25a9bd; color: #1e6070;
                    }
                    QPushButton, QToolButton { background: #f6fdff; border: 1px solid #8dcbd7; color: #284b5a; }
                    QPushButton:hover, QToolButton:hover { background: #e2f7fb; }
                    QPushButton#primary {
                        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #653eb3, stop:1 #159eb8);
                        border: 1px solid #29abc0; color: white;
                    }
                    QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                    QSpinBox, QComboBox, QKeySequenceEdit {
                        background: rgba(255,255,255,246); color: #243f50;
                        border: 1px solid #8cc8d6;
                        selection-background-color: #cdf0f5; selection-color: #185566;
                    }
                    QListWidget::item:hover { background: #e3f6fa; }
                    QListWidget::item:selected { background: #cbf0f5; color: #175565; }
                    QProgressBar::chunk {
                        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6841b5, stop:1 #17a7bc);
                    }
                    QSplitter::handle { background: #9cc9d6; }
                    QWidget#settingsPage, QScrollArea#settingsScroll,
                    QWidget#settingsViewport, QWidget#settingsContent {
                        background: #eefaff; border: none;
                    }
                    QWidget#settingsContent QFrame#card { background: rgba(255,255,255,238); }
                    QMenu { background: #f8fdff; color: #243f50; border: 1px solid #8cc8d6; }
                    QMenu::item:selected { background: #cff0f5; color: #175565; }
                """
            return """
                QMainWindow, QDialog {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:1,
                        stop:0 #070817, stop:0.47 #11102f, stop:1 #071d28
                    );
                }
                QWidget { color: #e5fdff; }
                QFrame#sidebar { background: #090a19; border-right: 1px solid #1da5ba; }
                QFrame#card { background: rgba(12, 17, 39, 235); border: 1px solid #1e778c; }
                QLabel#logo, QLabel#pageTitle { color: #dffeff; }
                QLabel#muted { color: #7ec6d4; }
                QPushButton#navButton:hover { background: #131b37; }
                QPushButton#navButton:checked {
                    background: #162f45; border: 1px solid #27d7e2; color: #e8feff;
                }
                QPushButton, QToolButton { background: #111a34; border: 1px solid #275d74; color: #e3fbff; }
                QPushButton:hover, QToolButton:hover { background: #19284a; border-color: #28c4d1; }
                QPushButton#primary {
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #7b2ed0, stop:1 #12b8c8);
                    border: 1px solid #29e2e8; color: white;
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QSpinBox, QComboBox, QKeySequenceEdit {
                    background: #0d1229; color: #e4fcff; border: 1px solid #285c73;
                    selection-background-color: #174c61; selection-color: #efffff;
                }
                QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus,
                QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {
                    border: 1px solid #25d7df;
                }
                QListWidget::item:hover { background: #141e3a; }
                QListWidget::item:selected { background: #174b60; color: #f0ffff; }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #9a35db, stop:1 #18d9dd);
                }
                QSplitter::handle { background: #31396c; }
                QWidget#settingsPage, QScrollArea#settingsScroll,
                QWidget#settingsViewport, QWidget#settingsContent {
                    background: #080a19; border: none;
                }
                QWidget#settingsContent QFrame#card { background: rgba(12,17,39,235); }
                QMenu { background: #0e132b; color: #e5fdff; border: 1px solid #247b8f; }
                QMenu::item:selected { background: #173f56; color: #ecffff; }
            """

        # Gradient
        if light:
            return """
                QMainWindow, QDialog {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:1,
                        stop:0 #eef5ff, stop:0.45 #f5f4ff, stop:1 #faefff
                    );
                }
                QFrame#sidebar {
                    background: qlineargradient(
                        x1:0,y1:0,x2:0,y2:1,
                        stop:0 #f5f8ff, stop:1 #f5effc
                    );
                    border-right: 1px solid #b7acd6;
                }
                QFrame#card { background: rgba(255,255,255,232); border: 1px solid #c4b9df; }
                QLabel#logo, QLabel#pageTitle { color: #433c72; }
                QLabel#muted { color: #777091; }
                QPushButton#navButton:hover { background: #ece7fa; }
                QPushButton#navButton:checked {
                    background: #e2dcf8; border: 1px solid #8477cd; color: #4e438d;
                }
                QPushButton, QToolButton { background: rgba(255,255,255,235); border: 1px solid #c2b7de; color: #443f64; }
                QPushButton:hover, QToolButton:hover { background: #ede9fa; }
                QPushButton#primary {
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6659d4, stop:1 #a366d4);
                    border: none; color: white;
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QSpinBox, QComboBox, QKeySequenceEdit {
                    background: rgba(255,255,255,244); color: #3e3a5c;
                    border: 1px solid #c4b9df;
                    selection-background-color: #dfd9f7; selection-color: #4f4389;
                }
                QListWidget::item:hover { background: #eee9fa; }
                QListWidget::item:selected { background: #dfd8f6; color: #4c4285; }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #655bd4, stop:1 #a56dd4);
                }
                QSplitter::handle { background: #c1b6dd; }
                QWidget#settingsPage, QScrollArea#settingsScroll,
                QWidget#settingsViewport, QWidget#settingsContent {
                    background: #f4f2fc; border: none;
                }
                QWidget#settingsContent QFrame#card { background: rgba(255,255,255,232); }
                QMenu { background: #fbfaff; color: #403b61; border: 1px solid #c4b9df; }
                QMenu::item:selected { background: #e2dcf8; color: #4e438d; }
            """
        return """
            QMainWindow, QDialog {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0b1225, stop:0.45 #17152f, stop:1 #251431
                );
            }
            QWidget { color: #f5f3ff; }
            QFrame#sidebar {
                background: qlineargradient(
                    x1:0,y1:0,x2:0,y2:1,
                    stop:0 #10162a, stop:1 #1c1428
                );
                border-right: 1px solid #4e467d;
            }
            QFrame#card { background: rgba(25,24,50,235); border: 1px solid #4d4776; }
            QLabel#logo, QLabel#pageTitle { color: #f1edff; }
            QLabel#muted { color: #aaa3cc; }
            QPushButton#navButton:hover { background: #262242; }
            QPushButton#navButton:checked {
                background: #3b356d; border: 1px solid #786bea; color: #ffffff;
            }
            QPushButton, QToolButton { background: #24213f; border: 1px solid #48436e; color: #f4f1ff; }
            QPushButton:hover, QToolButton:hover { background: #322d54; }
            QPushButton#primary {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5d55de, stop:1 #a34bc5);
                border: 1px solid #8173ed; color: white;
            }
            QLineEdit, QTextEdit, QTextBrowser, QListWidget,
            QSpinBox, QComboBox, QKeySequenceEdit {
                background: #18172e; color: #f5f3ff; border: 1px solid #4c4675;
                selection-background-color: #49417d; selection-color: #ffffff;
            }
            QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus,
            QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {
                border: 1px solid #8576ed;
            }
            QListWidget::item:hover { background: #282443; }
            QListWidget::item:selected { background: #4a437f; color: #ffffff; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #635add, stop:1 #a950c6);
            }
            QSplitter::handle { background: #544c80; }
            QWidget#settingsPage, QScrollArea#settingsScroll,
            QWidget#settingsViewport, QWidget#settingsContent {
                background: #151329; border: none;
            }
            QWidget#settingsContent QFrame#card { background: rgba(25,24,50,235); }
            QMenu { background: #1c1934; color: #f5f3ff; border: 1px solid #4c4675; }
            QMenu::item:selected { background: #443d76; color: #ffffff; }
        """

    def _visual_theme_font_family(self):
        """System font used by the selected visual theme."""
        if getattr(self, "safe_mode", False):
            return "Segoe UI"
        families = {
            "default": "Segoe UI",
            "retro": "Tahoma",
            "neon": "Consolas",
            "gradient": "Trebuchet MS",
            "moscow_night": "Segoe UI",
            "police_blue": "Segoe UI",
            "crimson": "Segoe UI",
            "amoled": "Segoe UI",
            "terminal": "Consolas",
            "cyber_blue": "Segoe UI",
            "arctic": "Segoe UI",
            "carbon": "Segoe UI",
            "midnight_purple": "Segoe UI",
            "amber": "Segoe UI",
            "government": "Segoe UI",
            "rainy_moscow": "Segoe UI",
            "hazard": "Arial",
            "paper": "Georgia",
            "deep_space": "Segoe UI",
        }
        return families.get(self._visual_theme_name(), "Segoe UI")

    def _visual_theme_component_qss(self, light=False):
        """Change typography and physical control styling per visual theme."""
        name = self._visual_theme_name()

        if name == "paper":
            return """
                QWidget { font-family: "Georgia"; }
                QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {
                    font-family: "Georgia";
                    font-weight: 700;
                }
                QPushButton, QToolButton {
                    border-radius: 5px;
                    padding: 8px 14px;
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit {
                    border-radius: 4px;
                }
                QFrame#card { border-radius: 6px; }
                QMenu { border-radius: 4px; }
            """

        if name == "hazard":
            return """
                QWidget { font-family: "Arial"; }
                QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {
                    font-weight: 800;
                }
                QPushButton, QToolButton {
                    border-radius: 3px;
                    padding: 8px 14px;
                    font-weight: 700;
                }
                QPushButton#primary {
                    color: #111111;
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit {
                    border-radius: 3px;
                }
                QFrame#card { border-radius: 4px; }
            """

        if name == "government":
            return """
                QWidget { font-family: "Segoe UI"; }
                QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {
                    font-weight: 700;
                }
                QPushButton, QToolButton {
                    border-radius: 5px;
                    padding: 9px 14px;
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit {
                    border-radius: 5px;
                }
                QFrame#card { border-radius: 6px; }
                QMenu { border-radius: 5px; }
            """

        if name == "terminal":
            accent = "#30ae5b" if light else "#43e27f"
            return f"""
                QWidget {{ font-family: "Consolas"; }}
                QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {{
                    font-family: "Consolas";
                    font-weight: 700;
                }}
                QPushButton, QToolButton {{
                    font-family: "Consolas";
                    border-radius: 2px;
                    padding: 8px 13px;
                    border: 1px solid {accent};
                }}
                QPushButton#primary {{
                    border-radius: 2px;
                    background: {accent};
                    border: 1px solid {accent};
                }}
                QPushButton#navButton {{ border-radius: 2px; }}
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit {{
                    font-family: "Consolas";
                    border-radius: 2px;
                }}
                QFrame#card, QMenu, QProgressBar {{ border-radius: 3px; }}
            """

        if name == "amoled":
            return """
                QWidget { font-family: "Segoe UI"; }
                QPushButton, QToolButton { border-radius: 6px; padding: 8px 14px; }
                QPushButton#primary { border-radius: 7px; }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit { border-radius: 6px; }
                QFrame#card { border-radius: 8px; }
                QMenu { border-radius: 6px; }
            """

        if name == "crimson":
            return """
                QWidget { font-family: "Segoe UI"; }
                QPushButton, QToolButton { border-radius: 10px; padding: 9px 15px; }
                QPushButton#primary {
                    border-radius: 11px;
                    background: qlineargradient(
                        x1:0,y1:0,x2:1,y2:0,
                        stop:0 #8f1020, stop:1 #c21f36
                    );
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit { border-radius: 10px; }
                QFrame#card { border-radius: 12px; }
                QMenu { border-radius: 8px; }
            """

        if name == "police_blue":
            return """
                QWidget { font-family: "Segoe UI"; }
                QPushButton, QToolButton { border-radius: 8px; padding: 9px 14px; }
                QPushButton#primary {
                    border-radius: 9px;
                    background: qlineargradient(
                        x1:0,y1:0,x2:1,y2:0,
                        stop:0 #1555b8, stop:1 #2787ef
                    );
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit { border-radius: 8px; }
                QFrame#card { border-radius: 10px; }
                QMenu { border-radius: 7px; }
            """

        if name == "moscow_night":
            return """
                QWidget { font-family: "Segoe UI"; }
                QPushButton, QToolButton { border-radius: 10px; padding: 9px 15px; }
                QPushButton#primary {
                    border-radius: 10px;
                    background: qlineargradient(
                        x1:0,y1:0,x2:1,y2:0,
                        stop:0 #1f5f9f, stop:1 #2b8cda
                    );
                }
                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit { border-radius: 9px; }
                QFrame#card { border-radius: 12px; }
                QMenu { border-radius: 8px; }
            """

        if name == "retro":
            if light:
                return """
                    QWidget { font-family: "Tahoma"; }
                    QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {
                        font-family: "Tahoma";
                        font-weight: 700;
                    }

                    QPushButton, QToolButton {
                        font-family: "Tahoma";
                        border-radius: 0px;
                        padding: 7px 13px;
                        background: #c0c0c0;
                        color: #000000;
                        border-top: 2px solid #ffffff;
                        border-left: 2px solid #ffffff;
                        border-right: 2px solid #404040;
                        border-bottom: 2px solid #404040;
                    }
                    QPushButton:hover, QToolButton:hover {
                        background: #d4d0c8;
                    }
                    QPushButton:pressed, QToolButton:pressed {
                        background: #b8b8b8;
                        border-top: 2px solid #404040;
                        border-left: 2px solid #404040;
                        border-right: 2px solid #ffffff;
                        border-bottom: 2px solid #ffffff;
                        padding-top: 9px;
                        padding-left: 15px;
                    }
                    QPushButton#primary {
                        background: #000080;
                        color: #ffffff;
                        border-top: 2px solid #d7d7ff;
                        border-left: 2px solid #d7d7ff;
                        border-right: 2px solid #202040;
                        border-bottom: 2px solid #202040;
                    }
                    QPushButton#primary:hover { background: #1010a0; }
                    QPushButton#navButton {
                        border-radius: 0px;
                        padding: 8px 10px;
                    }
                    QPushButton#navButton:checked {
                        background: #000080;
                        color: #ffffff;
                        border: 1px dotted #ffffff;
                    }

                    QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                    QComboBox, QSpinBox, QKeySequenceEdit {
                        font-family: "Tahoma";
                        border-radius: 0px;
                        background: #ffffff;
                        color: #000000;
                        border-top: 2px solid #404040;
                        border-left: 2px solid #404040;
                        border-right: 2px solid #ffffff;
                        border-bottom: 2px solid #ffffff;
                    }
                    QFrame#card, QProgressBar, QMenu {
                        border-radius: 0px;
                    }
                """

            return """
                QWidget { font-family: "Tahoma"; }
                QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {
                    font-family: "Tahoma";
                    font-weight: 700;
                }

                QPushButton, QToolButton {
                    font-family: "Tahoma";
                    border-radius: 0px;
                    padding: 7px 13px;
                    background: #343434;
                    color: #ffe2a8;
                    border-top: 2px solid #8b744e;
                    border-left: 2px solid #8b744e;
                    border-right: 2px solid #111111;
                    border-bottom: 2px solid #111111;
                }
                QPushButton:hover, QToolButton:hover {
                    background: #454038;
                }
                QPushButton:pressed, QToolButton:pressed {
                    background: #2a2825;
                    border-top: 2px solid #111111;
                    border-left: 2px solid #111111;
                    border-right: 2px solid #8b744e;
                    border-bottom: 2px solid #8b744e;
                    padding-top: 9px;
                    padding-left: 15px;
                }
                QPushButton#primary {
                    background: #6a431b;
                    color: #fff0c8;
                    border-top: 2px solid #d5a45f;
                    border-left: 2px solid #d5a45f;
                    border-right: 2px solid #271506;
                    border-bottom: 2px solid #271506;
                }
                QPushButton#primary:hover { background: #825322; }
                QPushButton#navButton {
                    border-radius: 0px;
                    padding: 8px 10px;
                }
                QPushButton#navButton:checked {
                    background: #72501f;
                    color: #fff2cc;
                    border: 1px dotted #ffd793;
                }

                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit {
                    font-family: "Tahoma";
                    border-radius: 0px;
                    border-top: 2px solid #111111;
                    border-left: 2px solid #111111;
                    border-right: 2px solid #756044;
                    border-bottom: 2px solid #756044;
                }
                QFrame#card, QProgressBar, QMenu {
                    border-radius: 0px;
                }
            """

        if name == "neon":
            if light:
                return """
                    QWidget { font-family: "Consolas"; }
                    QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {
                        font-family: "Consolas";
                        font-weight: 700;
                    }

                    QPushButton, QToolButton {
                        font-family: "Consolas";
                        border-radius: 4px;
                        padding: 8px 14px;
                        border: 1px solid #48b6c8;
                    }
                    QPushButton:hover, QToolButton:hover {
                        border: 2px solid #6d55bd;
                        padding: 7px 13px;
                    }
                    QPushButton:pressed, QToolButton:pressed {
                        background: #d7edf5;
                    }
                    QPushButton#primary {
                        border-radius: 4px;
                        background: qlineargradient(
                            x1:0,y1:0,x2:1,y2:0,
                            stop:0 #7550c7, stop:1 #23aabd
                        );
                        border: 1px solid #31b2c5;
                    }

                    QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                    QComboBox, QSpinBox, QKeySequenceEdit {
                        font-family: "Consolas";
                        border-radius: 4px;
                    }
                    QFrame#card { border-radius: 5px; }
                    QMenu { font-family: "Consolas"; }
                """

            return """
                QWidget { font-family: "Consolas"; }
                QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {
                    font-family: "Consolas";
                    font-weight: 700;
                }

                QPushButton, QToolButton {
                    font-family: "Consolas";
                    border-radius: 4px;
                    padding: 8px 14px;
                    background: #10182f;
                    border: 1px solid #20d7df;
                    color: #e6feff;
                }
                QPushButton:hover, QToolButton:hover {
                    background: #1d2449;
                    border: 2px solid #c044ef;
                    padding: 7px 13px;
                }
                QPushButton:pressed, QToolButton:pressed {
                    background: #251d47;
                    border-color: #20e5ea;
                }
                QPushButton#primary {
                    border-radius: 4px;
                    background: qlineargradient(
                        x1:0,y1:0,x2:1,y2:0,
                        stop:0 #842fd2, stop:1 #0dc4cf
                    );
                    border: 1px solid #24f1ee;
                    color: white;
                }

                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit {
                    font-family: "Consolas";
                    border-radius: 4px;
                }
                QFrame#card { border-radius: 5px; }
                QMenu { font-family: "Consolas"; }
            """

        if name == "gradient":
            return """
                QWidget { font-family: "Trebuchet MS"; }
                QLabel#logo, QLabel#pageTitle, QLabel#sectionTitle {
                    font-family: "Trebuchet MS";
                    font-weight: 700;
                }

                QPushButton, QToolButton {
                    font-family: "Trebuchet MS";
                    border-radius: 14px;
                    padding: 9px 16px;
                }
                QPushButton#primary {
                    border-radius: 16px;
                    background: qlineargradient(
                        x1:0,y1:0,x2:1,y2:0,
                        stop:0 #6259dc, stop:0.52 #7d5cdc, stop:1 #aa5ac8
                    );
                }

                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QComboBox, QSpinBox, QKeySequenceEdit {
                    font-family: "Trebuchet MS";
                    border-radius: 12px;
                }
                QFrame#card { border-radius: 16px; }
                QMenu {
                    font-family: "Trebuchet MS";
                    border-radius: 10px;
                }
            """

        return """
            QWidget { font-family: "Segoe UI"; }
            QPushButton, QToolButton {
                font-family: "Segoe UI";
                border-radius: 8px;
            }
            QLineEdit, QTextEdit, QTextBrowser, QListWidget,
            QComboBox, QSpinBox, QKeySequenceEdit {
                font-family: "Segoe UI";
            }
        """

    def apply_style(self):
        self.install_memo_shortcut()

        base_font = int(self.app_settings.get("program_font_size", 14))
        light = (
            False
            if self.safe_mode
            else self.app_settings.get("theme", "dark") == "light"
        )

        app = QApplication.instance()
        if app is not None:
            app_font = app.font()
            app_font.setFamily(self._visual_theme_font_family())
            app_font.setPointSize(base_font)
            app.setFont(app_font)

        if light:
            style = """
                QMainWindow, QDialog { background: #f4f6f9; }
                QWidget {
                    color: #20242b;
                    font-family: "Segoe UI";
                    font-size: 14px;
                }
                QFrame#sidebar {
                    background: #ffffff;
                    border-right: 1px solid #d9dee7;
                }
                QFrame#card {
                    background: #ffffff;
                    border: 1px solid #dfe3e9;
                    border-radius: 10px;
                }
                QLabel#logo { font-size: 28px; font-weight: 700; color: #171a20; }
                QLabel#pageTitle { font-size: 26px; font-weight: 700; color: #171a20; }
                QLabel#articleHeading { font-size: 19px; font-weight: 600; }
                QLabel#muted { color: #737b88; }

                QPushButton#navButton {
                    text-align: left;
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    padding: 11px;
                    font-size: 14px;
                }
                QPushButton#navButton:hover { background: #eef2f7; }
                QPushButton#navButton:checked {
                    background: #e2e9ff;
                    border: 1px solid #8da2f2;
                    color: #24429a;
                    font-weight: 700;
                }
                QPushButton, QToolButton {
                    background: #ffffff;
                    border: 1px solid #d3d9e2;
                    border-radius: 8px;
                    padding: 10px 14px;
                    color: #20242b;
                }
                QPushButton:hover, QToolButton:hover { background: #edf1f6; }
                QPushButton:disabled { color: #a0a7b2; background: #eceff3; }
                QPushButton#primary {
                    background: #4f6bed;
                    border: none;
                    color: #ffffff;
                    padding-left: 25px;
                    padding-right: 25px;
                }
                QPushButton#primary:hover { background: #6079ef; }
                QPushButton#memoIconButton { font-size: 20px; font-weight: 700; padding: 0px; }
                QScrollArea#lawSectionsScroll { background: transparent; border: none; }
                QWidget#lawSectionsContainer, QWidget#lawArticlesPanel { background: transparent; }
                QPushButton#lawSectionButton {
                    background: #ffffff;
                    border: 1px solid #d3d9e2;
                    border-radius: 8px;
                    padding: 7px 11px;
                    font-weight: 600;
                }
                QPushButton#lawSectionButton:hover { background: #edf1f6; }
                QPushButton#lawSectionButton:checked {
                    background: #e2e9ff;
                    border: 1px solid #6d8cff;
                    color: #24429a;
                }

                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QSpinBox, QComboBox, QKeySequenceEdit {
                    background: #ffffff;
                    color: #20242b;
                    border: 1px solid #d3d9e2;
                    border-radius: 9px;
                    selection-background-color: #dbe5ff;
                    selection-color: #1d315f;
                }
                QLineEdit { padding: 12px; font-size: 15px; }
                QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus,
                QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {
                    border: 1px solid #6d8cff;
                }
                QListWidget { padding: 5px; outline: none; }
                QListWidget::item { padding: 10px; border-radius: 7px; margin: 2px; }
                QListWidget::item:hover { background: #eef2f7; }
                QListWidget::item:selected { background: #dbe5ff; color: #1c315f; }
                QTextEdit, QTextBrowser { padding: 15px; font-size: 15px; }

                QComboBox { padding: 7px 10px; min-height: 24px; }
                QComboBox QAbstractItemView {
                    background: #ffffff;
                    color: #20242b;
                    border: 1px solid #d3d9e2;
                    selection-background-color: #dbe5ff;
                    selection-color: #1c315f;
                }
                QSpinBox, QKeySequenceEdit { padding: 6px 9px; min-height: 30px; }

                QProgressBar {
                    background: #eef1f5;
                    border: 1px solid #d3d9e2;
                    border-radius: 8px;
                    text-align: center;
                    height: 22px;
                }
                QProgressBar::chunk { background: #4f6bed; border-radius: 7px; }
                QSplitter::handle { background: #d8dee7; width: 7px; }
                QSplitter::handle:hover { background: #6f88ee; }

                QLabel#memoOverlayArticleCard {
                    background: #ffffff;
                    border: 1px solid #d3d9e2;
                    border-radius: 7px;
                    padding: 10px;
                }
                QFrame#settingsSeparator {
                    background: #dfe4eb;
                    border: none;
                    min-height: 1px;
                    max-height: 1px;
                    margin-top: 7px;
                    margin-bottom: 7px;
                }
                QWidget#settingsPage,
                QScrollArea#settingsScroll,
                QWidget#settingsViewport,
                QWidget#settingsContent {
                    background: #ffffff;
                    border: none;
                }
                QWidget#settingsContent QLabel { min-height: 0px; background: transparent; }
                QWidget#settingsContent QFrame#card { background: #ffffff; }
                QWidget#settingsContent QCheckBox::indicator {
                    width: 18px; height: 18px; border-radius: 5px;
                    border: 1px solid #b64a54; background: #c95761;
                }
                QWidget#settingsContent QCheckBox::indicator:checked {
                    border: 1px solid #32945d; background: #3eae6c;
                }
                QWidget#settingsContent QCheckBox::indicator:unchecked {
                    border: 1px solid #b64a54; background: #c95761;
                }
                QWidget#settingsContent QCheckBox { spacing: 9px; padding-top: 5px; padding-bottom: 5px; }
                ThemeSwitch::indicator { width: 0px; height: 0px; }

                QMenu {
                    background: #ffffff;
                    color: #20242b;
                    border: 1px solid #d3d9e2;
                    padding: 5px;
                }
                QMenu::item { padding: 7px 26px 7px 10px; border-radius: 5px; }
                QMenu::item:selected { background: #dbe5ff; color: #1c315f; }
                QToolTip {
                    background: #ffffff; color: #20242b;
                    border: 1px solid #cfd5de; padding: 5px;
                }
                QScrollBar:vertical, QScrollBar:horizontal { background: transparent; }
                QScrollBar::handle { background: #bcc4d0; border-radius: 5px; min-height: 24px; min-width: 24px; }
                QScrollBar::handle:hover { background: #9da8b8; }
            """
        else:
            style = """
                QMainWindow, QDialog { background: #101114; }
                QWidget { color: #eeeeee; font-family: "Segoe UI"; font-size: 14px; }
                QFrame#sidebar { background: #15171b; border-right: 1px solid #292c33; }
                QFrame#card { background: #17191e; border: 1px solid #292d35; border-radius: 10px; }
                QLabel#logo { font-size: 28px; font-weight: 700; }
                QLabel#pageTitle { font-size: 26px; font-weight: 700; }
                QLabel#articleHeading { font-size: 19px; font-weight: 600; }
                QLabel#muted { color: #92959d; }

                QPushButton#navButton { text-align: left; background: transparent; border: none; border-radius: 8px; padding: 11px; font-size: 14px; }
                QPushButton#navButton:hover { background: #20242c; }
                QPushButton#navButton:checked { background: #33467f; border: 1px solid #506ee8; color: #ffffff; font-weight: 700; }
                QPushButton, QToolButton { background: #24272e; border: 1px solid #343740; border-radius: 8px; padding: 10px 14px; }
                QPushButton:hover, QToolButton:hover { background: #30343d; }
                QPushButton:disabled { color: #666a73; background: #1b1d22; }
                QPushButton#primary { background: #4f6bed; border: none; color: white; padding-left: 25px; padding-right: 25px; }
                QPushButton#primary:hover { background: #6079ef; }
                QPushButton#memoIconButton { font-size: 20px; font-weight: 700; padding: 0px; }
                QScrollArea#lawSectionsScroll { background: transparent; border: none; }
                QWidget#lawSectionsContainer, QWidget#lawArticlesPanel { background: transparent; }
                QPushButton#lawSectionButton {
                    background: #24272e;
                    border: 1px solid #343740;
                    border-radius: 8px;
                    padding: 7px 11px;
                    font-weight: 600;
                }
                QPushButton#lawSectionButton:hover { background: #30343d; }
                QPushButton#lawSectionButton:checked {
                    background: #33467f;
                    border: 1px solid #6d8cff;
                    color: #ffffff;
                }

                QLineEdit, QTextEdit, QTextBrowser, QListWidget,
                QSpinBox, QComboBox, QKeySequenceEdit {
                    background: #181a1f;
                    color: #eeeeee;
                    border: 1px solid #343740;
                    border-radius: 9px;
                    selection-background-color: #3d4f83;
                    selection-color: white;
                }
                QLineEdit { padding: 12px; font-size: 15px; }
                QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus,
                QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus { border: 1px solid #6d8cff; }
                QListWidget { padding: 5px; outline: none; }
                QListWidget::item { padding: 10px; border-radius: 7px; margin: 2px; }
                QListWidget::item:hover { background: #24272e; }
                QListWidget::item:selected { background: #3d4f83; }
                QTextEdit, QTextBrowser { padding: 15px; font-size: 15px; }
                QComboBox { padding: 7px 10px; min-height: 24px; }
                QComboBox QAbstractItemView { background: #181a1f; color: #eeeeee; border: 1px solid #343740; selection-background-color: #3d4f83; }
                QSpinBox, QKeySequenceEdit { padding: 6px 9px; min-height: 30px; }

                QProgressBar { background: #181a1f; border: 1px solid #343740; border-radius: 8px; text-align: center; height: 22px; }
                QProgressBar::chunk { background: #4f6bed; border-radius: 7px; }
                QSplitter::handle { background: #343740; width: 7px; }
                QSplitter::handle:hover { background: #4f6bed; }
                QLabel#memoOverlayArticleCard { background: #181b21; border: 1px solid #343740; border-radius: 7px; padding: 10px; }
                QFrame#settingsSeparator { background: #2b2f38; border: none; min-height: 1px; max-height: 1px; margin-top: 7px; margin-bottom: 7px; }
                QWidget#settingsPage,
                QScrollArea#settingsScroll,
                QWidget#settingsViewport,
                QWidget#settingsContent {
                    background: #101114;
                    border: none;
                }
                QWidget#settingsContent QLabel { min-height: 0px; background: transparent; }
                QWidget#settingsContent QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid #7f2f36; background: #7a252d; }
                QWidget#settingsContent QCheckBox::indicator:checked { border: 1px solid #3ea86b; background: #2f9e62; }
                QWidget#settingsContent QCheckBox::indicator:unchecked { border: 1px solid #a43b45; background: #8f2d36; }
                QWidget#settingsContent QCheckBox { spacing: 9px; padding-top: 5px; padding-bottom: 5px; }
                ThemeSwitch::indicator { width: 0px; height: 0px; }
                QMenu { background: #1a1d22; color: #eeeeee; border: 1px solid #343740; padding: 5px; }
                QMenu::item { padding: 7px 26px 7px 10px; border-radius: 5px; }
                QMenu::item:selected { background: #33467f; }
                QToolTip { background: #20232a; color: #f4f5f7; border: 1px solid #3a3f49; padding: 5px; }
                QScrollBar:vertical, QScrollBar:horizontal { background: transparent; }
                QScrollBar::handle { background: #555b68; border-radius: 5px; min-height: 24px; min-width: 24px; }
                QScrollBar::handle:hover { background: #6b7280; }
            """

        style += self._visual_theme_qss(light)

        active_palette = self._visual_theme_overlay_palette(light)

        def palette_rgb(key):
            r, g, b = active_palette[key]
            return f"rgb({r}, {g}, {b})"

        theme_text = palette_rgb("text")
        theme_muted = palette_rgb("muted")
        theme_primary = palette_rgb("primary")
        theme_primary_border = palette_rgb("primary_border")
        theme_button = palette_rgb("button")
        theme_button_hover = palette_rgb("button_hover")
        theme_border = palette_rgb("border")
        theme_selected = palette_rgb("selected")
        theme_selected_text = palette_rgb("selected_text")

        # This layer intentionally targets the common controls again so text,
        # buttons and smaller UI elements always change together with the
        # background theme, including widgets created after startup.
        style += f"""
            QLabel, QCheckBox, QRadioButton, QGroupBox {{
                color: {theme_text};
            }}
            QLabel#muted, QLabel#calcOverlayMuted {{
                color: {theme_muted};
            }}
            QLabel#tutorialHint {{
                color: {theme_primary_border};
                font-size: 15px;
                font-weight: 700;
                padding: 4px 0px;
            }}
            QPushButton, QToolButton {{
                color: {theme_text};
                background-color: {theme_button};
                border-color: {theme_border};
            }}
            QPushButton:hover, QToolButton:hover {{
                background-color: {theme_button_hover};
                border-color: {theme_primary_border};
            }}
            QPushButton#primary {{
                background-color: {theme_primary};
                border: 1px solid {theme_primary_border};
                color: white;
            }}
            QPushButton#primary:hover {{
                background-color: {theme_primary_border};
            }}
            QLineEdit, QTextEdit, QTextBrowser, QListWidget,
            QSpinBox, QComboBox, QKeySequenceEdit {{
                color: {theme_text};
                border-color: {theme_border};
            }}
            QListWidget::item:selected {{
                background-color: {theme_selected};
                color: {theme_selected_text};
            }}
        """

        style += self._visual_theme_component_qss(light)

        style = style.replace("font-size: 14px;", f"font-size: {base_font}px;")
        style = style.replace("font-size: 15px;", f"font-size: {base_font + 1}px;")
        style = style.replace("font-size: 19px;", f"font-size: {base_font + 5}px;")
        style = style.replace("font-size: 26px;", f"font-size: {base_font + 12}px;")
        style = style.replace("font-size: 28px;", f"font-size: {base_font + 14}px;")
        self.setStyleSheet(style)

        if self.memo_overlay is not None:
            self.apply_overlay_background_opacity()
        if self.search_overlay is not None:
            self.apply_search_overlay_style()
        if self.calculator_overlay is not None:
            self.apply_calculator_overlay_style()
        if hasattr(self, "ai_chat_layout"):
            self.rebuild_ai_chat()

    def _save_remembered_close_choice(self, action):
        """Persist the choice selected in the X-button dialog."""
        if action not in ("minimize", "exit"):
            return

        self.app_settings["close_behavior"] = action
        self.app_settings["remember_close_choice"] = True
        self.save_app_settings()
        self.refresh_close_behavior_settings_ui()

    def _ask_main_window_close_action(self):
        """Return (action, remember) for an X-button press.

        action is one of: minimize, exit, cancel.
        """
        box = QMessageBox(self)
        box.setWindowTitle("Закрытие DeiLaw")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("Что сделать с DeiLaw?")
        box.setInformativeText(
            "«Свернуть» оставит программу запущенной в панели задач — "
            "глобальные бинды F7, F8 и F9 продолжат работать.\n\n"
            "«Закрыть полностью» завершит работу DeiLaw."
        )

        minimize_btn = box.addButton(
            "Свернуть в трей",
            QMessageBox.ButtonRole.AcceptRole,
        )
        exit_btn = box.addButton(
            "Закрыть полностью",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel_btn = box.addButton(
            "Отмена",
            QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(minimize_btn)

        remember_box = QCheckBox("Запомнить мой выбор")
        box.setCheckBox(remember_box)

        box.exec()
        clicked = box.clickedButton()

        if clicked is minimize_btn:
            return "minimize", remember_box.isChecked()
        if clicked is exit_btn:
            return "exit", remember_box.isChecked()
        return "cancel", False

    def _minimize_from_close_button(self, event):
        """Hide DeiLaw to the system tray without unregistering hotkeys."""
        for overlay_name in (
            "memo_overlay",
            "search_overlay",
            "calculator_overlay",
        ):
            overlay = getattr(self, overlay_name, None)
            if overlay is not None and overlay.isVisible():
                overlay.hide()

        event.ignore()

        if (
            self.system_tray_icon is not None
            and self.system_tray_icon.isVisible()
        ):
            # hide() removes DeiLaw from the taskbar and Alt+Tab while keeping
            # background timers and global F7/F8/F9 hotkeys alive.
            self.hide()

            if not self._tray_hint_shown:
                try:
                    self.system_tray_icon.showMessage(
                        "DeiLaw работает в трее",
                        "Программа скрыта из панели задач. Нажмите на значок "
                        "DeiLaw в системном трее, чтобы открыть её снова.",
                        QSystemTrayIcon.MessageIcon.Information,
                        3500,
                    )
                except Exception:
                    pass
                self._tray_hint_shown = True
        else:
            # Fallback only for systems without an available tray.
            self.showMinimized()

        self.play_ui_sound("close")

    def _confirm_settings_before_full_exit(self):
        """Handle unsaved Settings only when DeiLaw is really exiting."""
        if not (
            hasattr(self, "pages")
            and self.pages.currentIndex() == self.settings_page_index
            and self.settings_dirty
        ):
            return True

        box = QMessageBox(self)
        box.setWindowTitle("Закрыть DeiLaw")
        box.setText("Сохранить изменения настроек перед выходом?")
        save_btn = box.addButton(
            "Сохранить и выйти",
            QMessageBox.ButtonRole.AcceptRole,
        )
        discard_btn = box.addButton(
            "Выйти без сохранения",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel_btn = box.addButton(
            "Отмена",
            QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(save_btn)
        box.exec()

        if box.clickedButton() is cancel_btn:
            return False
        if box.clickedButton() is save_btn:
            self.apply_app_settings()

        return True

    def _perform_full_exit_cleanup(self):
        """Release files/windows/hotkeys immediately before a real exit."""
        self.save_memo_layout_state()
        self.save_overlay_layout_state()
        self.save_search_overlay_geometry()
        self.save_calculator_overlay_geometry()
        self.save_current_profile_runtime()

        self.unregister_global_hotkey()
        self.unregister_search_global_hotkey()
        self.unregister_calculator_global_hotkey()
        self.unregister_ahk_runtime_hotkeys()

        if self.memo_overlay is not None:
            self.memo_overlay.hide()
            self.memo_overlay.deleteLater()
            self.memo_overlay = None
        if self.search_overlay is not None:
            self.search_overlay.hide()
            self.search_overlay.deleteLater()
            self.search_overlay = None
        if self.calculator_overlay is not None:
            self.calculator_overlay.hide()
            self.calculator_overlay.deleteLater()
            self.calculator_overlay = None

        if self.system_tray_icon is not None:
            self.system_tray_icon.hide()
            self.system_tray_icon.deleteLater()
            self.system_tray_icon = None
            self.system_tray_menu = None

        self.database.close()

    def closeEvent(self, event):
        # Updater/internal shutdown must never be converted into "minimize".
        if getattr(self, "_force_full_exit", False):
            action = "exit"
            remember_new_choice = False
        else:
            behavior = str(
                self.app_settings.get("close_behavior", "ask") or "ask"
            ).strip().lower()
            remembered = bool(
                self.app_settings.get("remember_close_choice", False)
            )

            if remembered and behavior in ("minimize", "exit"):
                action = behavior
                remember_new_choice = False
            else:
                action, remember_new_choice = (
                    self._ask_main_window_close_action()
                )

        if action == "cancel":
            event.ignore()
            return

        if action == "minimize":
            if remember_new_choice:
                self._save_remembered_close_choice("minimize")
            self._minimize_from_close_button(event)
            return

        # A real exit may need to deal with unsaved Settings first.
        if not self._confirm_settings_before_full_exit():
            event.ignore()
            return

        # Save the X-dialog choice only after we know the exit was not cancelled
        # by the unsaved-Settings confirmation.
        if remember_new_choice:
            self._save_remembered_close_choice("exit")

        self._perform_full_exit_cleanup()
        event.accept()
