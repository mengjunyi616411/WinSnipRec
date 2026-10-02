"""An easter egg: type 廉丰榕 into the settings search box.

Choosing 是 closes it; choosing 否 just asks again, so there is no way out.
The artwork ships in assets/ and is bundled by build_exe.ps1 (--add-data assets;assets).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..i18n import t as _t
from ..theme import theme
from .widgets import FluentButton, FluentWindow, TitleBar

#: The word that opens it.
TRIGGER = "廉丰榕"

ASSET_NAME = "easter_egg.jpg"
IMAGE_MAX_WIDTH = 300
IMAGE_MAX_HEIGHT = 470
CARD_WIDTH = 360
CARD_HEIGHT = 650


def asset_path(name: str) -> Path | None:
    """Locate a file under assets/ in source, frozen and installed layouts."""
    roots: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    roots.append(str(Path(__file__).resolve().parents[2]))     # project root
    roots.append(str(Path(sys.executable).resolve().parent))   # next to the exe
    for root in roots:
        candidate = Path(root) / "assets" / name
        if candidate.is_file():
            return candidate
    return None


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
        self.title_bar.caption_buttons["close"].clicked.connect(self._on_yes)
        root.addWidget(self.title_bar)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 6, 20, 18)
        layout.setSpacing(10)

        self.image_label = QLabel(body)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._load_image()

        self.question = QLabel(_t("你是萝莉控吗？"), body)
        self.question.setObjectName("eggQuestion")
        self.question.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.question.setWordWrap(True)
        layout.addWidget(self.question)

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

        self.refresh_theme()

    # ------------------------------------------------------------------ #
    def _load_image(self) -> None:
        path = asset_path(ASSET_NAME)
        if path is None:
            self.image_label.setText(_t("彩蛋图片缺失"))
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.image_label.setText(_t("彩蛋图片缺失"))
            return
        scaled = pixmap.scaled(IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setFixedSize(scaled.size())

    def answer_is_yes(self) -> bool:
        """Exposed for the tests: has the only accepted answer been given?"""
        return getattr(self, "_answered_yes", False)

    def _on_yes(self) -> None:
        self._answered_yes = True
        self.dismissed.emit()
        self.close()

    def _on_no(self) -> None:
        """There is no no: the question just comes back."""
        self.question.setText(_t("再选一次？"))
        self.no_button.setText(_t("……否"))
        self.no_button.setEnabled(True)

    def refresh_theme(self) -> None:
        palette = theme.palette
        self.title_bar.refresh()
        self.setStyleSheet(f"""
            QLabel#eggQuestion {{
                font-size: 15px; font-weight: 600;
                color: {palette.text_primary};
            }}
        """)


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
