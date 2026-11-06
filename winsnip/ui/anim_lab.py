"""Developer tools: an animation preview window.

Unlocked by typing the developer phrase into the settings search box. Every
button here replays one of the app's real animations with the current style and
theme, so "this animation feels off" can be checked without hunting for the
place in the UI that triggers it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from .. import __version__, anim
from ..theme import theme, ui_font
from .widgets import FluentButton, FluentComboBox, FluentWindow, ToggleSwitch, show_toast


class AnimLabWindow(FluentWindow):
    """Preview each animation with the current style/theme."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, resizable=False)
        self.setWindowTitle("动画测试")
        self.set_card_size(560, 480)

        margin = self._margin + 20
        layout = QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(10)

        title = QLabel("动画测试", self)
        title.setFont(ui_font(18, 600))
        layout.addWidget(title)

        self.info = QLabel("", self)
        self.info.setFont(ui_font(12))
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        def button(text: str, slot) -> FluentButton:
            b = FluentButton(text, self)
            b.setFixedHeight(38)
            b.clicked.connect(slot)
            layout.addWidget(b)
            return b

        button("播放窗口开启动画", self._play_window)
        button("播放下拉展开动画", self._play_popup)
        button("播放 Toast", self._play_toast)

        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel("开关动画", self)
        label.setFont(ui_font(13))
        row.addWidget(label)
        row.addStretch(1)
        self.toggle = ToggleSwitch(False, self)
        row.addWidget(self.toggle)
        layout.addLayout(row)

        combo_label = QLabel("下拉控件", self)
        combo_label.setFont(ui_font(13))
        layout.addWidget(combo_label)
        self.combo = FluentComboBox(self)
        self.combo.addItems(["跟随系统", "Windows 11", "Windows 10"])
        self.combo.setCurrentIndex(1)
        layout.addWidget(self.combo)

        layout.addStretch(1)

        close = FluentButton("关闭", self)
        close.setFixedHeight(38)
        close.clicked.connect(self.close)
        layout.addWidget(close)

        self._sync_info()

    # ------------------------------------------------------------------ #
    def _sync_info(self) -> None:
        self.info.setText(
            f"版本 {__version__}    风格 {theme.resolved_style}    "
            f"主题 {'深色' if theme.dark else '浅色'}    "
            f"动画 {'开' if anim.animations_enabled() else '关'}"
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        try:
            self._sync_info()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _play_window(self) -> None:
        anim.play_window_open(self, slide=14, duration=anim.DURATION_NORMAL)

    def _play_popup(self) -> None:
        self.combo.showPopup()

    def _play_toast(self) -> None:
        show_toast("动画测试", "这是一条 Toast 提示", "check", duration=2200)


_lab: AnimLabWindow | None = None


def show_anim_lab(parent=None) -> None:
    """Open (or re-focus) the single developer preview window."""
    global _lab
    try:
        if _lab is not None and _lab.isVisible():
            _lab.raise_()
            _lab.activateWindow()
            return
    except RuntimeError:
        _lab = None
    _lab = AnimLabWindow(parent)
    _lab.show()
