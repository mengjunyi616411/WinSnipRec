"""检查更新的 Alert 对话框。

点设置里的「检查」会打开这个窗口，而不是只更新那一行的副标题。
原来的副标题状态保留，两边同时显示，所以关掉 Alert 也能看到上次结果。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import __version__
from ..i18n import t as _t
from ..theme import ui_font
from .widgets import FluentButton, FluentWindow


class UpdateAlert(FluentWindow):
    """A small modal-ish window: 尚未检查 -> 检查中… -> 结果。"""

    def __init__(self, on_check, on_open, parent: QWidget | None = None) -> None:
        super().__init__(parent, resizable=False)
        self.setWindowTitle(_t("检查更新"))
        self.set_card_size(480, 320)
        self._on_check = on_check
        self._on_open = on_open
        self._info = None

        margin = self._margin + 20
        layout = QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(8)

        title = QLabel(_t("检查更新"), self)
        title.setFont(ui_font(18, 600))
        layout.addWidget(title)

        self.status = QLabel(_t("尚未检查"), self)
        self.status.setFont(ui_font(15, 600))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.detail = QLabel(f"{_t('当前版本')} {__version__}", self)
        self.detail.setFont(ui_font(12))
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.detail)

        layout.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.check_button = FluentButton(_t("立即检查"), self, variant="accent", height=36)
        self.check_button.clicked.connect(self._trigger)
        row.addWidget(self.check_button)
        self.open_button = FluentButton(_t("打开下载页"), self, height=36)
        self.open_button.clicked.connect(self._open)
        self.open_button.setVisible(False)
        row.addWidget(self.open_button)
        row.addStretch(1)
        close_button = FluentButton(_t("关闭"), self, height=36)
        close_button.clicked.connect(self.close)
        row.addWidget(close_button)
        layout.addLayout(row)

        # 锁死尺寸：QTextEdit/长文案都不该把窗口撑开
        self.resize(self.card_size())
        self.setFixedSize(self.card_size())

    # ------------------------------------------------------------------ #
    def _trigger(self) -> None:
        """点「立即检查」：先把状态改成检查中，再禁用按钮（顺序不能反）。

        原来先 setEnabled(False) 再 set_status()，而 set_status 结尾会把按钮重新
        启用，于是按钮立刻恢复，"看起来没在检查"。
        """
        self.set_status(_t("检查中…"), f"{_t('当前版本')} {__version__}")
        try:
            self.check_button.setEnabled(False)
        except Exception:
            pass
        try:
            self._on_check()
        except Exception as exc:
            self.set_status(_t("检查失败"), f"{type(exc).__name__}: {exc}")

    def _open(self) -> None:
        try:
            if self._info is not None and self._info.url:
                self._on_open(self._info.url)
        except Exception:
            pass

    def set_status(self, text: str, detail: str, info=None) -> None:
        """由设置窗口在检查完成（或失败）时调用。"""
        try:
            self.status.setText(text)
            self.detail.setText(detail)
            self._info = info
            self.check_button.setEnabled(True)
            self.open_button.setVisible(bool(info is not None and info.url))
        except RuntimeError:
            pass
