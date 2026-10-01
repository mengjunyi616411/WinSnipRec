"""Screenshot preview window styled like the Windows 11 Snipping Tool editor."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from .. import icons
from ..settings import settings
from ..theme import theme, ui_font
from .widgets import FluentButton, FluentWindow, IconButton, Separator, TitleBar, show_toast


class ImageCanvas(QWidget):
    """Centred, fit-to-window image surface on a neutral backdrop."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        palette = theme.palette
        backdrop = QColor("#1C1C1C") if palette.dark else QColor("#F0F0F0")
        painter.fillRect(self.rect(), backdrop)
        if self._pixmap is None or self._pixmap.isNull():
            return
        available = self.rect().adjusted(18, 18, -18, -18)
        scaled = self._pixmap.scaled(available.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        x = available.left() + (available.width() - scaled.width()) / 2
        y = available.top() + (available.height() - scaled.height()) / 2
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(QRectF(x - 1, y - 1, scaled.width() + 2, scaled.height() + 2), 6, 6)
        painter.drawPixmap(int(x), int(y), scaled)
        painter.end()


class ImagePreviewWindow(FluentWindow):
    """Shows the just-taken screenshot with copy / save actions."""

    closed = Signal()

    def __init__(self, path: str, image: QImage) -> None:
        super().__init__(None, resizable=True)
        self.setWindowTitle("截图工具")
        self.setWindowIcon(icons.app_icon())
        self.set_card_size(720, 520)
        self.setMinimumSize(480 + 40, 360 + 40)
        self._path = path
        self._image = image
        self._pixmap = QPixmap.fromImage(image)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        self.title_bar = TitleBar("截图工具", self)
        self.title_bar.icon_label.setPixmap(icons.app_icon().pixmap(16, 16))
        self.title_bar.caption_buttons["min"].clicked.connect(self.showMinimized)
        self.title_bar.caption_buttons["max"].clicked.connect(self._toggle_max)
        self.title_bar.caption_buttons["close"].clicked.connect(self.close)
        root.addWidget(self.title_bar)

        command = QWidget(self)
        command.setFixedHeight(56)
        layout = QHBoxLayout(command)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        self.save_button = FluentButton("保存", command, variant="accent", icon_name="save",
                                        height=36, font_size=14)
        self.save_button.clicked.connect(self.save_as)
        layout.addWidget(self.save_button)

        self.copy_button = FluentButton("复制", command, variant="standard", icon_name="copy",
                                        height=36, font_size=14)
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        layout.addWidget(self.copy_button)

        layout.addWidget(Separator(command, height=22))

        self.folder_button = FluentButton("在文件夹中显示", command, variant="subtle",
                                          icon_name="folder", height=36, font_size=14)
        self.folder_button.clicked.connect(self.reveal)
        layout.addWidget(self.folder_button)

        layout.addStretch(1)

        self.size_label = QLabel(command)
        self.size_label.setFont(ui_font(12))
        layout.addWidget(self.size_label)

        self.cancel_button = IconButton("close", command, width=40, height=36, tooltip="关闭")
        self.cancel_button.clicked.connect(self.close)
        layout.addWidget(self.cancel_button)
        root.addWidget(command)

        self.canvas = ImageCanvas(self)
        self.canvas.set_pixmap(self._pixmap)
        root.addWidget(self.canvas, 1)

        self.size_label.setText(f"{self._pixmap.width()} × {self._pixmap.height()}")
        self.title_bar.set_title(f"截图工具 — {Path(path).name}")
        self.refresh_theme()

        QShortcut(QKeySequence.StandardKey.Copy, self, self.copy_to_clipboard)
        QShortcut(QKeySequence.StandardKey.Save, self, self.save_as)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_as)
        QShortcut(QKeySequence.StandardKey.Close, self, self.close)

    def refresh_theme(self) -> None:
        self.title_bar.refresh()
        self.size_label.setStyleSheet(f"color: {theme.palette.text_secondary};")
        self.canvas.update()

    def _toggle_max(self) -> None:
        self.toggle_maximized()
        button = self.title_bar.caption_buttons["max"]
        button.kind = "restore" if self.is_maximized() else "max"
        button.update()

    # ------------------------------------------------------------------ #
    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setPixmap(self._pixmap)
        show_toast("已复制到剪贴板", f"{self._pixmap.width()} × {self._pixmap.height()}", "copy",
                   duration=2000)

    def save_as(self) -> None:
        default = self._path
        target, _ = QFileDialog.getSaveFileName(self, "另存为", default, "PNG 图片 (*.png);;JPEG 图片 (*.jpg)")
        if not target:
            return
        try:
            if target.lower().endswith((".jpg", ".jpeg")):
                self._pixmap.save(target, "JPEG", 92)
            else:
                self._pixmap.save(target, "PNG")
        except Exception as exc:
            show_toast("保存失败", str(exc), "info")
            return
        self._path = target
        self.title_bar.set_title(f"截图工具 — {Path(target).name}")
        show_toast("已保存", target, "check")

    def reveal(self) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self._path)])
        except Exception:
            folder = str(Path(self._path).parent)
            try:
                os.startfile(folder)  # noqa: S606
            except Exception as exc:
                show_toast("无法打开文件夹", str(exc), "info")

    def closeEvent(self, event) -> None:  # noqa: N802
        super().closeEvent(event)
        self.closed.emit()
