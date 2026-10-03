"""An easter egg: type 廉丰榕 into the settings search box.

Choosing 是 closes it; choosing 否 just asks again, so there is no way out.
The artwork ships in assets/ and is bundled by build_exe.ps1 (--add-data assets;assets).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..i18n import t as _t
from ..theme import theme
from .widgets import FluentButton, FluentWindow, TitleBar

#: The word that opens it.
TRIGGER = "廉丰榕"

#: Pictures live in assets/egg/NN.jpg (build_exe.ps1 already ships assets/).
ASSET_DIR = "egg"
IMAGE_MAX_WIDTH = 300
IMAGE_MAX_HEIGHT = 470
CARD_WIDTH = 360
CARD_HEIGHT = 650


def _asset_roots() -> list[str]:
    """Where assets/ can live: frozen bundle, source tree, or next to the exe."""
    roots: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    roots.append(str(Path(__file__).resolve().parents[2]))     # project root
    roots.append(str(Path(sys.executable).resolve().parent))   # next to the exe
    return roots


def asset_path(name: str) -> Path | None:
    """Locate a FILE under assets/."""
    for root in _asset_roots():
        candidate = Path(root) / "assets" / name
        if candidate.is_file():
            return candidate
    return None


def asset_dir(name: str) -> Path | None:
    """Locate a FOLDER under assets/.

    asset_path() checks is_file(), so looking up the picture folder with it
    always returned None and the gallery loaded zero images.
    """
    for root in _asset_roots():
        candidate = Path(root) / "assets" / name
        if candidate.is_dir():
            return candidate
    return None


def picture_paths() -> list[Path]:
    """Every picture for the gallery, in numbered order."""
    folder = asset_dir(ASSET_DIR)
    if folder is None:
        return []
    return sorted(path for path in folder.iterdir()
                  if path.suffix.lower() in (".jpg", ".jpeg", ".png"))


def triggers(text: str) -> bool:
    """True when the search box contains the magic word."""
    return TRIGGER in (text or "")


class EasterEggWindow(FluentWindow):
    """A picture and a question with only one acceptable answer."""

    dismissed = Signal()

    def __init__(self) -> None:
        super().__init__(resizable=False, open_animation="fade")
        self.setWindowTitle(_t("彩蛋"))
        self.set_card_size(CARD_WIDTH, CARD_HEIGHT)

        root = QVBoxLayout(self)
        root.setContentsMargins(self._margin, self._margin, self._margin, self._margin)
        root.setSpacing(0)

        self.title_bar = TitleBar(_t("彩蛋"), self)
        self.title_bar.caption_buttons["max"].setVisible(False)
        self.title_bar.caption_buttons["min"].setVisible(False)
        # 用户要求去掉关闭按钮：只能通过「否 / 是」离开。
        self.title_bar.caption_buttons["close"].setVisible(False)
        root.addWidget(self.title_bar)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 6, 20, 18)
        layout.setSpacing(10)

        self.image_label = QLabel(body)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._pictures: list[QPixmap] = []
        self._index = 0
        self._load_pictures()
        self._show_current()

        self.question = QLabel(_t("你是萝莉控吗？"), body)
        self.question.setObjectName("eggQuestion")
        self.question.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.question.setWordWrap(True)
        layout.addWidget(self.question)

        # 第几张 / 共几张，让「否」看起来是在翻页而不是没反应。
        self.counter = QLabel("", body)
        self.counter.setObjectName("eggCounter")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.counter)
        # 计数标签刚建好，补一次刷新（_load_pictures 时它还不存在）
        self._show_current()

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(10)
        buttons.addStretch(1)
        self.no_button = FluentButton(_t("否"), body, height=36)
        self.no_button.setMinimumWidth(96)
        self.no_button.clicked.connect(self._on_no)
        self.yes_button = FluentButton(_t("是"), body, variant="accent", height=36)
        self.yes_button.setMinimumWidth(96)
        self.yes_button.clicked.connect(self._on_yes)
        buttons.addWidget(self.no_button)
        buttons.addWidget(self.yes_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        root.addWidget(body, 1)

        # 图片以外的高度（标题栏 + 问题 + 计数 + 按钮 + 边距），换图时窗口按它加图片高度。
        self._chrome_height = max(0, CARD_HEIGHT - IMAGE_MAX_HEIGHT)
        self._show_current()
        self.refresh_theme()

    # ------------------------------------------------------------------ #
    def _load_pictures(self) -> None:
        """Load and pre-scale every picture once, so flipping is instant."""
        for path in picture_paths():
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            self._pictures.append(pixmap.scaled(
                IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        if not self._pictures:
            self.image_label.setText(_t("彩蛋图片缺失"))

    def picture_count(self) -> int:
        """How many pictures the gallery holds (exposed for the tests)."""
        return len(self._pictures)

    def current_index(self) -> int:
        return self._index

    def _show_current(self) -> None:
        if not self._pictures:
            return
        pixmap = self._pictures[self._index]
        self.image_label.setPixmap(pixmap)
        self.image_label.setFixedSize(pixmap.size())
        if getattr(self, "counter", None) is not None:
            self.counter.setText(f"{self._index + 1} / {len(self._pictures)}")
        self._fit_to_picture(pixmap)

    def _fit_to_picture(self, pixmap: QPixmap) -> None:
        """Shrink the card to the picture so横图不上下留白，并保持窗口居中。"""
        chrome = getattr(self, "_chrome_height", None)
        if chrome is None:
            return
        # 延到下一个事件循环：刚 setFixedSize 过的布局还没重算，此时窗口的最小高度
        # 仍是上一张图的高度，直接 resize 会被钳住缩小不了。
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: self._apply_card_height(pixmap.height() + chrome))

    def _apply_card_height(self, height: int) -> None:
        centre = self.frameGeometry().center()
        self.set_card_size(CARD_WIDTH, height)
        self.move(centre.x() - self.width() // 2, centre.y() - self.height() // 2)

    def answer_is_yes(self) -> bool:
        """Exposed for the tests: has the only accepted answer been given?"""
        return getattr(self, "_answered_yes", False)

    def _on_yes(self) -> None:
        self._answered_yes = True
        self.dismissed.emit()
        self.close()
        show_admission()

    def _on_no(self) -> None:
        """There is no no: it just shows the next picture."""
        if self._pictures:
            self._index = (self._index + 1) % len(self._pictures)
            self._show_current()
        self.question.setText(_t("再选一次？"))

    def refresh_theme(self) -> None:
        palette = theme.palette
        self.title_bar.refresh()
        self.setStyleSheet(f"""
            QLabel#eggQuestion {{
                font-size: 15px; font-weight: 600;
                color: {palette.text_primary};
            }}
            QLabel#eggCounter {{
                font-size: 12px;
                color: {palette.text_secondary};
            }}
        """)


class AdmissionWindow(FluentWindow):
    """选「是」之后弹出来的那个窗口。"""

    CARD_WIDTH = 320
    CARD_HEIGHT = 180

    def __init__(self) -> None:
        super().__init__(resizable=False, open_animation="fade")
        self.setWindowTitle(_t("彩蛋"))
        self.set_card_size(self.CARD_WIDTH, self.CARD_HEIGHT)

        root = QVBoxLayout(self)
        root.setContentsMargins(self._margin, self._margin, self._margin, self._margin)
        root.setSpacing(0)

        self.title_bar = TitleBar(_t("彩蛋"), self)
        for key in ("min", "max", "close"):
            self.title_bar.caption_buttons[key].setVisible(False)
        root.addWidget(self.title_bar)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 8, 20, 18)
        layout.setSpacing(16)

        self.message = QLabel(_t("你承认啦！"), body)
        self.message.setObjectName("admissionText")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message, 1)

        self.ok_button = FluentButton(_t("好"), body, variant="accent", height=34)
        self.ok_button.setMinimumWidth(96)
        self.ok_button.clicked.connect(self.close)
        layout.addWidget(self.ok_button, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(body, 1)

        self.refresh_theme()

    def refresh_theme(self) -> None:
        palette = theme.palette
        self.setStyleSheet(f"""
            QLabel#admissionText {{
                font-size: 17px; font-weight: 700;
                color: {palette.text_primary};
            }}
        """)

    def retranslate(self) -> None:
        self.setWindowTitle(_t("彩蛋"))
        self.title_bar.retranslate()
        self.message.setText(_t("你承认啦！"))
        self.ok_button.setText(_t("好"))


#: Kept alive while shown, otherwise Python would collect it immediately.
_ADMISSION: list[AdmissionWindow] = []


def show_admission(parent: QWidget | None = None) -> AdmissionWindow:
    """Pop up 你承认啦！, centred on the parent (or the screen)."""
    window = AdmissionWindow()
    if parent is not None:
        centre = parent.frameGeometry().center()
    else:
        screen = window.screen()
        centre = screen.availableGeometry().center() if screen else QPoint(0, 0)
    window.move(centre.x() - window.width() // 2,
                max(0, centre.y() - window.height() // 2))
    window.destroyed.connect(lambda *_: _ADMISSION.clear())
    _ADMISSION.append(window)
    window.show()
    return window


def show_easter_egg(parent: QWidget | None = None) -> EasterEggWindow | None:
    """Open the easter egg, centred on the parent. Returns None if it is absent."""
    if not _already_open():
        window = EasterEggWindow()
        window.show()
        window.raise_()
        window.activateWindow()
        if parent is not None:
            try:
                centre = parent.frameGeometry().center()
                window.move(centre.x() - window.width() // 2,
                            max(0, centre.y() - window.height() // 2))
            except Exception:
                pass
        _OPEN.append(window)
        window.dismissed.connect(lambda: _forget(window))
        return window
    return None


_OPEN: list[EasterEggWindow] = []


def _already_open() -> bool:
    return any(window.isVisible() for window in _OPEN)


def _forget(window: EasterEggWindow) -> None:
    try:
        _OPEN.remove(window)
    except ValueError:
        pass
    window.deleteLater()


def open_count() -> int:
    """How many easter-egg windows are live (used by the tests)."""
    return len([window for window in _OPEN if window.isVisible()])
