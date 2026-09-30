"""The main window: a faithful recreation of the Windows 11 Snipping Tool."""

from __future__ import annotations

import datetime as _dt
import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import (
    QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .. import anim, icons, winapi
from ..settings import settings
from ..theme import RADIUS_CONTROL, rgba, theme, ui_font
from .control_bar import CountdownOverlay, RecordControlBar
from .overlay import CaptureOverlay
from .preview import ImagePreviewWindow
from .settings_dialog import SettingsWindow
from .widgets import (
    FluentButton, FluentMenu, FluentWindow, IconButton, SegmentedControl, Separator,
    TitleBar, show_toast,
)

SHAPES = [
    ("rectangle", "矩形区域", "add_rect"),
    ("window", "窗口", "window"),
    ("fullscreen", "全屏", "fullscreen"),
    ("freeform", "自由绘制", "freeform"),
]
SHAPE_ICONS = {key: icon for key, _, icon in SHAPES}

LOOPBACK_HINTS = ("stereo mix", "立体声混音", "what u hear", "voicemeeter", "cable output",
                  "loopback", "监视器", "混音")


class HotkeyHint(QWidget):
    """Centred hint text that renders the Windows logo inline.

    Switching mode plays a Fluent content transition: the old text fades out
    while sliding up, then the new text fades in from below.
    """

    TRANSITION_OUT = 0.38          # share of the timeline spent fading the old text
    DURATION = 300

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lines: list[tuple[str, str]] = []
        self._pending: list[tuple[str, str]] | None = None
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.DURATION)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._on_tick)
        self._anim.finished.connect(self._on_finished)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_hint(self, primary: str, secondary: str = "", *, animate: bool = True) -> None:
        lines = [(primary, "primary"), (secondary, "secondary")]
        if lines == self._lines and self._pending is None:
            return
        self.setToolTip(primary)
        if (not animate or not anim.animations_enabled() or not self.isVisible()
                or not self._lines or lines == self._lines):
            self._anim.stop()
            self._lines = lines
            self._pending = None
            self._t = 1.0
            self.update()
            return
        self._pending = lines
        self._anim.stop()
        self._anim.start()

    def transition_progress(self) -> float:
        """0 while the swap starts, 1 when settled (exposed for tests)."""
        return self._t

    def _on_tick(self, value) -> None:
        self._t = float(value)
        if self._pending is not None and self._t >= self.TRANSITION_OUT:
            self._lines = self._pending
            self._pending = None
        self.update()

    def _on_finished(self) -> None:
        if self._pending is not None:
            self._lines = self._pending
            self._pending = None
        self._t = 1.0
        self.update()

    def _phase(self) -> tuple[float, float]:
        """(opacity, vertical offset) for the current point on the timeline."""
        if self._t < self.TRANSITION_OUT:
            k = self._t / self.TRANSITION_OUT
            return max(0.0, 1.0 - k), -6.0 * k
        k = (self._t - self.TRANSITION_OUT) / (1.0 - self.TRANSITION_OUT)
        return min(1.0, k), 8.0 * (1.0 - k)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        opacity, offset = self._phase()
        if opacity <= 0.01:
            painter.end()
            return
        painter.setOpacity(opacity)
        painter.translate(0.0, offset)
        palette = theme.palette
        y = 0
        for text, kind in self._lines:
            if not text:
                y += 22
                continue
            if kind == "primary":
                font = ui_font(14)
                color = QColor(palette.text_primary)
                logo_color = QColor(palette.accent)
                height = 26
            else:
                font = ui_font(12)
                color = QColor(palette.text_secondary)
                logo_color = QColor(palette.text_secondary)
                height = 22
            painter.setFont(font)
            metrics = QFontMetrics(font)
            logo_size = 14 if kind == "primary" else 12
            segments = self._parse(text)
            total = 0
            for segment_kind, value in segments:
                if segment_kind == "logo":
                    total += logo_size
                else:
                    total += metrics.horizontalAdvance(value)
            x = (self.width() - total) / 2.0
            baseline_rect = QRectF(x, y, total, height)
            for segment_kind, value in segments:
                if segment_kind == "logo":
                    self._paint_logo(painter, QRectF(x + 1, y + (height - logo_size) / 2.0,
                                                     logo_size, logo_size), logo_color)
                    x += logo_size
                else:
                    painter.setPen(color)
                    painter.drawText(QRectF(x, y, metrics.horizontalAdvance(value) + 2, height),
                                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                                     value)
                    x += metrics.horizontalAdvance(value)
            y += height + 6
        painter.end()

    @staticmethod
    def _parse(text: str) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        for index, chunk in enumerate(text.split("{win}")):
            if index:
                parts.append(("logo", ""))
            if chunk:
                parts.append(("text", chunk))
        return parts

    @staticmethod
    def _paint_logo(painter: QPainter, rect: QRectF, color: QColor) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        gap = rect.width() * 0.09
        pane = (rect.width() - gap) / 2.0
        painter.drawRect(QRectF(rect.left(), rect.top(), pane, pane))
        painter.drawRect(QRectF(rect.left() + pane + gap, rect.top(), pane, pane))
        painter.drawRect(QRectF(rect.left(), rect.top() + pane + gap, pane, pane))
        painter.drawRect(QRectF(rect.left() + pane + gap, rect.top() + pane + gap, pane, pane))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, 60)


class MainWindow(FluentWindow):
    """Command bar + hint area, mirroring 截图工具 on Windows 11."""

    captureRequested = Signal(str)          # camera | video
    settingsChanged = Signal()

    def __init__(self) -> None:
        super().__init__(None, resizable=True)
        self.setWindowTitle("截图工具")
        self.setWindowIcon(icons.app_icon())
        self.set_card_size(620, 300)
        self.setMinimumSize(620 + 40, 300 + 40)

        self._mode = settings.last_mode
        self._shape = settings.last_shape
        self._overlay: CaptureOverlay | None = None
        self._recorder = None
        self._control_bar: RecordControlBar | None = None
        self._countdown: CountdownOverlay | None = None
        self._preview: ImagePreviewWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._pending_rect: QRect | None = None
        self._hint_mode = "both"
        self._quitting = False

        self._build()
        self.refresh_theme()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        self.title_bar = TitleBar("截图工具", self)
        self.title_bar.icon_label.setPixmap(icons.app_icon().pixmap(16, 16))
        caption = self.title_bar.caption_buttons
        caption["min"].clicked.connect(self.showMinimized)
        caption["max"].clicked.connect(self._toggle_max)
        caption["close"].clicked.connect(self.close)
        root.addWidget(self.title_bar)

        command = QWidget(self)
        command.setFixedHeight(56)
        command_layout = QHBoxLayout(command)
        command_layout.setContentsMargins(16, 0, 16, 0)
        command_layout.setSpacing(10)

        self.new_button = FluentButton("新建", command, variant="standard", icon_name="add",
                                       accent_icon=True, height=36, font_size=14)
        self.new_button.clicked.connect(self.start_capture)
        command_layout.addWidget(self.new_button)

        self.segmented = SegmentedControl([("camera", "截图"), ("video", "录屏")], command,
                                          item_width=48, height=36)
        self.segmented.set_current(0 if self._mode == "camera" else 1, emit=False)
        self.segmented.itemClicked.connect(self._on_mode_clicked)
        command_layout.addWidget(self.segmented)

        self.shape_button = IconButton(SHAPE_ICONS.get(self._shape, "add_rect"), command,
                                       width=64, height=36, with_chevron=True)
        self.shape_button.clicked.connect(self._show_shape_menu)
        command_layout.addWidget(self.shape_button)

        self.audio_button = IconButton("mic_off", command, width=64, height=36, with_chevron=True)
        self.audio_button.clicked.connect(self._show_audio_menu)
        command_layout.addWidget(self.audio_button)

        command_layout.addStretch(1)

        self.more_button = IconButton("more", command, width=40, height=36)
        self.more_button.clicked.connect(self._show_more_menu)
        command_layout.addWidget(self.more_button)
        root.addWidget(command)

        self.content = QWidget(self)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(24, 0, 24, 20)
        content_layout.setSpacing(6)
        content_layout.addStretch(1)
        self.hint = HotkeyHint(self.content)
        content_layout.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignHCenter)
        content_layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        self.folder_button = FluentButton("打开保存文件夹", self.content, variant="hyperlink",
                                          icon_name="folder", height=28, font_size=12)
        self.folder_button.clicked.connect(self.open_output_folder)
        footer.addWidget(self.folder_button)
        footer.addStretch(1)
        content_layout.addLayout(footer)
        root.addWidget(self.content, 1)

        self._build_tray()
        self._update_hint()
        self._update_audio_icon()

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip("截图工具")
        menu = QMenu()
        menu.addAction("新建截图", lambda: self.start_capture("camera"))
        menu.addAction("新建录屏", lambda: self.start_capture("video"))
        menu.addSeparator()
        menu.addAction("设置", self.open_settings)
        menu.addAction("打开保存文件夹", self.open_output_folder)
        menu.addSeparator()
        menu.addAction("退出", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

    # ------------------------------------------------------------------ #
    # Theme
    # ------------------------------------------------------------------ #
    def refresh_theme(self) -> None:
        self.title_bar.refresh()
        palette = theme.palette
        self.content.setStyleSheet(
            f"background-color: {'rgba(255,255,255,0.45)' if not palette.dark else 'rgba(255,255,255,0.03)'};"
        )
        self.hint.update()
        self._update_audio_icon()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)

    # ------------------------------------------------------------------ #
    # Mode / shape / audio
    # ------------------------------------------------------------------ #
    def _on_mode_clicked(self, index: int) -> None:
        self._mode = "camera" if index == 0 else "video"
        settings.last_mode = self._mode
        settings.save()
        self._update_audio_icon()
        self._update_hint()

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self.segmented.set_current(0 if mode == "camera" else 1)
        settings.last_mode = mode
        settings.save()
        self._update_audio_icon()
        self._update_hint()

    def _update_hint(self) -> None:
        if self._mode == "camera":
            spec = settings.hotkey_snip
            primary = f"按 {self._hotkey_display(spec)} 开始截图"
        else:
            spec = settings.hotkey_record
            primary = f"按 {self._hotkey_display(spec)} 开始录屏"
        if self._hint_mode == "capture":
            primary = "拖动以选择区域 · Esc 取消"
        folder = settings.video_dir if self._mode == "video" else settings.image_dir
        secondary = f"{'视频' if self._mode == 'video' else '图片'}将保存到 {folder}"
        self.hint.set_hint(primary, secondary)

    @staticmethod
    def _hotkey_display(spec: str) -> str:
        """'Win+Shift+R' -> '{win} + Shift + R'; the logo is only shown for Win."""
        parts = [p.strip() for p in spec.replace("-", "+").split("+") if p.strip()]
        rendered: list[str] = []
        for part in parts:
            lowered = part.lower()
            if lowered in ("win", "windows", "super", "meta"):
                rendered.append("{win}")
            else:
                rendered.append(pretty(part))
        return " + ".join(rendered) if rendered else spec

    def _update_audio_icon(self) -> None:
        enabled = settings.mic_enabled or settings.system_audio
        self.audio_button.set_icon_name("mic" if settings.mic_enabled else
                                        ("sound" if settings.system_audio else "mic_off"))
        self.audio_button.setEnabled(self._mode == "video")
        self.audio_button.setToolTip("录制声音" if self._mode == "video" else "录屏时可选择声音来源")

    def _show_shape_menu(self) -> None:
        menu = FluentMenu(self, min_width=210)
        for key, label, icon_name in SHAPES:
            enabled = key != "freeform" or self._mode == "camera"
            menu.add_item(label, icon_name=icon_name, checked=(key == self._shape), enabled=enabled,
                          on_activate=lambda k=key: self._set_shape(k))
        menu.popup(self.shape_button.mapToGlobal(QPoint(0, self.shape_button.height() + 6)))

    def _set_shape(self, shape: str) -> None:
        self._shape = shape
        settings.last_shape = shape
        settings.save()
        self.shape_button.set_icon_name(SHAPE_ICONS.get(shape, "add_rect"))

    def _show_audio_menu(self) -> None:
        from ..core.audio import list_microphones

        menu = FluentMenu(self, min_width=250)
        menu.add_item("录制麦克风", icon_name="mic", checked=settings.mic_enabled,
                      on_activate=lambda: self._set_mic_enabled(not settings.mic_enabled))
        menu.add_item("录制系统声音", icon_name="sound", checked=settings.system_audio,
                      on_activate=lambda: self._set_system_audio(not settings.system_audio))
        menu.add_separator()

        devices = list_microphones()
        microphones = [d for d in devices if not _is_loopback(d.name)]
        loopbacks = [d for d in devices if _is_loopback(d.name)]
        if microphones:
            menu.add_header("麦克风设备")
            for device in microphones[:12]:
                menu.add_item(_shorten(device.name), checked=(device.id == settings.mic_device),
                              on_activate=lambda d=device: self._set_mic_device(d.id))
        if loopbacks:
            menu.add_header("系统声音设备（回环）")
            for device in loopbacks[:12]:
                menu.add_item(_shorten(device.name),
                              checked=(device.id == settings.system_audio_device),
                              on_activate=lambda d=device: self._set_loopback_device(d.id))
        if not devices:
            menu.add_item("未找到音频设备", enabled=False)
        menu.popup(self.audio_button.mapToGlobal(QPoint(0, self.audio_button.height() + 6)))

    def _set_mic_enabled(self, enabled: bool) -> None:
        settings.mic_enabled = enabled
        settings.save()
        self._update_audio_icon()
        if enabled and not settings.mic_device:
            from ..core.audio import default_microphone

            device = default_microphone()
            if device:
                settings.mic_device = device.id
                settings.save()
        show_toast("麦克风已" + ("开启" if enabled else "关闭"),
                   "录制时将" + ("采集" if enabled else "不采集") + "麦克风声音", "mic")

    def _set_system_audio(self, enabled: bool) -> None:
        settings.system_audio = enabled
        settings.save()
        self._update_audio_icon()
        if enabled and not settings.system_audio_device:
            from ..core.audio import list_microphones

            loopback = next((d for d in list_microphones() if _is_loopback(d.name)), None)
            if loopback:
                settings.system_audio_device = loopback.id
                settings.save()
            else:
                settings.system_audio = False
                settings.save()
                self._update_audio_icon()
                show_toast("无法录制系统声音",
                           "未找到立体声混音等回环设备。可在“声音设置”中启用“立体声混音”。", "info")
                return
        show_toast("系统声音已" + ("开启" if enabled else "关闭"), "", "sound")

    def _set_mic_device(self, device_id: str) -> None:
        settings.mic_device = device_id
        settings.mic_enabled = True
        settings.save()
        self._update_audio_icon()

    def _set_loopback_device(self, device_id: str) -> None:
        settings.system_audio_device = device_id
        settings.system_audio = True
        settings.save()
        self._update_audio_icon()

    def _show_more_menu(self) -> None:
        from .. import startup

        menu = FluentMenu(self, min_width=230)
        menu.add_header("开始前延迟")
        for value in (0, 3, 5, 10):
            menu.add_item("无延迟" if value == 0 else f"{value} 秒", checked=(settings.countdown == value),
                          on_activate=lambda v=value: self._set_countdown(v))
        menu.add_separator()
        autostart = startup.is_enabled()
        menu.add_item("开机自动启动", icon_name="monitor", checked=autostart,
                      on_activate=self._toggle_autostart)
        menu.add_item("设置", icon_name="settings", on_activate=self.open_settings)
        menu.add_item("打开保存文件夹", icon_name="folder", on_activate=self.open_output_folder)
        menu.add_separator()
        menu.add_item("关于截图工具", icon_name="info", on_activate=self._show_about)
        menu.popup(self.more_button.mapToGlobal(QPoint(0, self.more_button.height() + 6)))

    def _toggle_autostart(self) -> None:
        from .. import startup

        if startup.is_enabled():
            ok, message = startup.disable()
            show_toast("开机自动启动已关闭" if ok else "操作失败",
                       "已从注册表启动项中移除" if ok else message,
                       "info" if ok else "info", duration=4200 if ok else 5200)
        else:
            ok, message = startup.enable()
            show_toast("开机自动启动已开启" if ok else "操作失败",
                       "登录 Windows 后会在通知区域静默运行，可直接用快捷键唤起"
                       if ok else message,
                       "check" if ok else "info", duration=5200)
        if self._settings_window is not None:
            self._settings_window.refresh_theme()

    def _set_countdown(self, value: int) -> None:
        settings.countdown = value
        settings.save()
        show_toast("延迟已设置", "无延迟" if value == 0 else f"{value} 秒后开始", "timer")

    def _show_about(self) -> None:
        from .settings_dialog import AboutWindow

        self._about = AboutWindow()
        self._about.show()

    # ------------------------------------------------------------------ #
    # Capture flow
    # ------------------------------------------------------------------ #
    def start_capture(self, mode: str | None = None) -> None:
        import logging

        mode = mode or self._mode
        self._mode = mode
        self.segmented.set_current(0 if mode == "camera" else 1, emit=False)
        if self._overlay is not None:
            logging.getLogger("winsnip.ui").info(
                "start_capture(%s) ignored: overlay already open", mode)
            try:
                winapi.force_foreground(int(self._overlay.winId()))
            except Exception:
                pass
            return
        if self._recorder is not None:
            # Already recording: a second capture request must not stack an
            # overlay on top of the running recording.
            logging.getLogger("winsnip.ui").info(
                "start_capture(%s) ignored: a recording is in progress", mode)
            show_toast("正在录制中", "按 Ctrl+Alt+Q 停止录制，Ctrl+Alt+P 暂停/继续",
                       "record_ring", duration=2400)
            return
        logging.getLogger("winsnip.ui").info("start_capture(%s)", mode)
        self._backup_visibility()
        self.hide()
        QTimer.singleShot(180, lambda: self._open_overlay(mode))

    def _open_overlay(self, mode: str) -> None:
        import logging

        try:
            self._overlay = CaptureOverlay(mode=mode, shape=self._shape,
                                           confirm=settings.confirm_region)
            self._overlay.finished.connect(self._on_overlay_finished)
            self._overlay.cancelled.connect(self._on_overlay_cancelled)
            self._overlay.destroyed.connect(lambda *_: setattr(self, "_overlay", None))
            self._overlay.start()
            logging.getLogger("winsnip.ui").info("overlay shown for mode=%s", mode)
        except Exception:
            logging.getLogger("winsnip.ui").exception("failed to open the capture overlay")
            self._overlay = None
            show_toast("无法启动捕获", "请查看日志 %APPDATA%\\WinSnipRec\\app.log", "info")
            self._restore_main()

    def _backup_visibility(self) -> None:
        self._was_visible = self.isVisible()

    def _restore_main(self) -> None:
        if getattr(self, "_was_visible", True):
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_overlay_cancelled(self) -> None:
        self._overlay = None
        self._set_shape(self._shape)
        self._restore_main()

    def _on_overlay_finished(self, physical: QRect, shape: str, mode: str) -> None:
        overlay = self._overlay
        self._overlay = None
        self._set_shape(shape)
        if mode == "camera":
            frozen = None
            if overlay is not None:
                try:
                    frozen = overlay.frozen_crop(physical)
                except Exception:
                    frozen = None
            self._capture_screenshot(physical, frozen)
        else:
            self._pending_rect = physical
            if settings.countdown > 0:
                self._start_countdown(physical)
            else:
                self._begin_recording(physical)

    def _start_countdown(self, physical: QRect) -> None:
        from ..core.screen import virtual_rect

        left, top, _, _ = virtual_rect()
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        logical = QRect(
            int((physical.x() - left) / dpr), int((physical.y() - top) / dpr),
            int(physical.width() / dpr), int(physical.height() / dpr),
        )
        self._countdown = CountdownOverlay(logical, settings.countdown)
        self._countdown.finished.connect(lambda: self._begin_recording(physical))
        self._countdown.show()

    def _capture_screenshot(self, physical: QRect, frozen: QImage | None = None) -> None:
        from ..core.screen import ScreenGrabber

        image = frozen
        if image is None or image.isNull():
            grabber = ScreenGrabber()
            try:
                png = grabber.grab_png(
                    (physical.x(), physical.y(), physical.width(), physical.height()))
            finally:
                grabber.close()
            image = QImage()
            image.loadFromData(png, "PNG")
        if image is None or image.isNull():
            show_toast("截图失败", "无法读取屏幕内容", "info")
            self._restore_main()
            return
        if settings.copy_image_to_clipboard:
            QGuiApplication.clipboard().setImage(image)
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H%M%S")
        path = Path(settings.image_dir) / f"截图 {stamp}.png"
        try:
            if not image.save(str(path), "PNG"):
                raise OSError("PNG 编码失败")
        except Exception as exc:
            show_toast("保存失败", str(exc), "info")
        self._preview = ImagePreviewWindow(str(path), image)
        self._preview.closed.connect(self._restore_main)
        self._preview.show()
        if settings.copy_image_to_clipboard:
            show_toast("已复制到剪贴板", f"同时保存到 {path}", "copy")

    def _resolve_audio_devices(self) -> list:
        from ..core.audio import AudioDevice, list_microphones

        selected = []
        if settings.mic_enabled and settings.mic_device:
            selected.append(AudioDevice(settings.mic_device, settings.mic_device))
        if settings.system_audio and settings.system_audio_device:
            selected.append(AudioDevice(settings.system_audio_device, settings.system_audio_device))
        if selected:
            return selected
        if settings.mic_enabled:
            device = next((d for d in list_microphones() if not _is_loopback(d.name)), None)
            if device:
                return [device]
        return []

    def _begin_recording(self, physical: QRect) -> None:
        from ..core.recorder import Recorder

        self._countdown = None
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H%M%S")
        out_path = str(Path(settings.video_dir) / f"屏幕录制 {stamp}.mp4")
        devices = self._resolve_audio_devices()
        recorder = Recorder(
            rect=(physical.x(), physical.y(), physical.width(), physical.height()),
            fps=settings.fps, crf=settings.crf,
            mic=devices[0] if devices else None,
            out_path=out_path,
            capture_cursor=settings.capture_cursor,
        )
        self._recorder = recorder
        recorder.state_changed.connect(self._on_recorder_state)
        recorder.elapsed_changed.connect(self._on_recorder_elapsed)
        recorder.error.connect(self._on_recorder_error)
        recorder.finished.connect(self._on_recorder_finished)

        bar = RecordControlBar(mic_available=self._mic_available(), mic_enabled=bool(devices))
        self._control_bar = bar
        bar.stopRequested.connect(self.stop_recording)
        bar.pauseRequested.connect(self._on_pause_requested)
        bar.discardRequested.connect(self.discard_recording)
        bar.micToggled.connect(self._on_bar_mic_toggled)
        bar.show()
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        logical = QRect(int(physical.x() / dpr), int(physical.y() / dpr),
                        int(physical.width() / dpr), int(physical.height() / dpr))
        bar.place_outside(physical, logical)
        bar.exclude_from_capture()

        self._register_recording_hotkeys()
        recorder.start()
        logging.getLogger("winsnip.ui").info(
            "recording started rect=%s fps=%s audio=%s out=%s",
            (physical.x(), physical.y(), physical.width(), physical.height()),
            settings.fps, [d.name for d in devices], out_path)
        show_toast("录屏已开始", f"{physical.width()}×{physical.height()} · {settings.fps} fps",
                   "record_ring", duration=2200)

    def _mic_available(self) -> bool:
        """True when a microphone could be turned on, even if it is off now."""
        if settings.mic_device:
            return True
        try:
            from ..core.audio import default_microphone

            return default_microphone() is not None
        except Exception:
            return False

    def _on_bar_mic_toggled(self, enabled: bool) -> None:
        recorder = self._recorder
        if recorder is None:
            return
        setter = getattr(recorder, "set_mic", None)
        if setter is None:
            if self._control_bar is not None:
                self._control_bar.set_mic_enabled(not enabled, available=False)
            show_toast("无法在录制中切换麦克风", "请先停止录制，然后在工具栏中选择声音来源", "info")
            return
        from ..core.audio import AudioDevice

        if enabled:
            device_id = settings.mic_device
            if not device_id:
                from ..core.audio import default_microphone

                default = default_microphone()
                device_id = default.id if default else ""
            if not device_id:
                if self._control_bar is not None:
                    self._control_bar.set_mic_enabled(False, available=False)
                show_toast("未找到麦克风", "", "info")
                return
            setter(AudioDevice(device_id, device_id))
        else:
            setter(None)
        settings.mic_enabled = enabled
        settings.save()

    def _on_pause_requested(self, paused: bool) -> None:
        if self._recorder is None:
            return
        if paused:
            self._recorder.pause()
        else:
            self._recorder.resume()

    def _on_recorder_state(self, state) -> None:
        if self._control_bar is None:
            return
        name = getattr(state, "name", str(state))
        self._control_bar.set_paused(name == "PAUSED")

    def _on_recorder_elapsed(self, seconds: float) -> None:
        if self._control_bar is not None:
            self._control_bar.set_elapsed(seconds)

    def _on_recorder_error(self, message: str) -> None:
        show_toast("录制出现问题", message, "info")

    def _on_recorder_finished(self, path: str) -> None:
        logging.getLogger("winsnip.ui").info("recording finished: %s", path or "(no output)")
        self._teardown_recording()
        if not path:
            self._restore_main()
            return
        size = 0
        try:
            size = os.path.getsize(path)
        except Exception:
            pass
        show_toast("录制已保存", f"{Path(path).name} · {_human_size(size)}", "check",
                   duration=5200, on_click=lambda: self._reveal(path))
        if settings.open_folder_when_done:
            self._reveal(path)
        self._restore_main()

    def stop_recording(self) -> None:
        if self._recorder is not None:
            self._recorder.stop()

    def discard_recording(self) -> None:
        if self._recorder is not None:
            self._recorder.discard()
            self._teardown_recording()
            show_toast("已取消录制", "临时文件已删除", "trash")
        self._restore_main()

    def _teardown_recording(self) -> None:
        self._unregister_recording_hotkeys()
        if self._control_bar is not None:
            self._control_bar.close()
            self._control_bar = None
        self._recorder = None

    # ------------------------------------------------------------------ #
    # Hotkeys
    # ------------------------------------------------------------------ #
    def _register_recording_hotkeys(self) -> None:
        from . import hotkeys

        # Deliberately different from the snip/record bindings: Ctrl+Alt+S is a
        # common fallback for "new snip" and reusing it here would make the stop
        # hotkey silently fail to register.
        for name, spec, handler in (
            ("pause", "Ctrl+Alt+P", self._toggle_pause_from_hotkey),
            ("stop", "Ctrl+Alt+Q", self.stop_recording),
        ):
            if not hotkeys.register(name, spec, handler):
                logging.getLogger("winsnip.ui").warning(
                    "recording hotkey %s (%s) could not be registered", name, spec)

    def _unregister_recording_hotkeys(self) -> None:
        from . import hotkeys

        hotkeys.unregister("pause")
        hotkeys.unregister("stop")

    def _toggle_pause_from_hotkey(self) -> None:
        if self._recorder is None:
            return
        state = getattr(self._recorder.state, "name", "")
        if state == "PAUSED":
            self._recorder.resume()
        else:
            self._recorder.pause()

    # ------------------------------------------------------------------ #
    # Misc actions
    # ------------------------------------------------------------------ #
    def open_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow()
            self._settings_window.applied.connect(self._on_settings_applied)
            self._settings_window.closed.connect(self._on_settings_closed)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _on_settings_applied(self) -> None:
        from PySide6.QtWidgets import QApplication

        from ..theme import apply_app_theme

        theme.mode = settings.theme
        theme.refresh()
        app = QApplication.instance()
        if app is not None:
            # Palette + stylesheet must be rebuilt, otherwise the Qt-drawn
            # controls (combo boxes and their popups) keep the old theme.
            apply_app_theme(app)
        self.refresh_theme()
        self._update_hint()
        for widget in app.topLevelWidgets() if app is not None else []:
            refresh = getattr(widget, "refresh_theme", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass
            widget.update()
        self.settingsChanged.emit()

    def _on_settings_closed(self) -> None:
        self._settings_window = None

    def open_output_folder(self) -> None:
        folder = settings.video_dir if self._mode == "video" else settings.image_dir
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            os.startfile(folder)  # noqa: S606
        except Exception as exc:
            show_toast("无法打开文件夹", str(exc), "info")

    def _reveal(self, path: str) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception:
            self.open_output_folder()

    def _toggle_max(self) -> None:
        self.toggle_maximized()
        self.title_bar.caption_buttons["max"].kind = "restore" if self.is_maximized() else "max"
        self.title_bar.caption_buttons["max"].update()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()

    def _quit(self) -> None:
        # QApplication::quit() closes every top level window first; without this
        # flag closeEvent would "minimise to tray" (event.ignore()) and the
        # application would never actually exit.
        self._quitting = True
        if self._recorder is not None:
            self._recorder.stop()
        try:
            self.tray.hide()
        except Exception:
            pass
        QGuiApplication.quit()

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: N802
        # Only a *user* close (clicking the X, spontaneous) should fall back to
        # the tray. A programmatic close -- including the one Qt performs while
        # shutting the application down -- must be honoured, otherwise
        # event.ignore() keeps the process alive forever.
        if self._quitting or not event.spontaneous():
            if self._recorder is not None:
                self._recorder.stop()
            event.accept()
            super().closeEvent(event)
            return
        if self._recorder is not None:
            self._recorder.stop()
        if settings.minimize_to_tray and self.tray.isVisible():
            self.hide()
            event.ignore()
            show_toast("截图工具仍在运行", "按 Win+Shift+S 截图，Win+Shift+R 录屏；右键托盘图标退出",
                       "info", duration=4200)
            return
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if settings.minimize_to_tray and not self.tray.isVisible():
            self.tray.show()


def _is_loopback(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in LOOPBACK_HINTS)


def _shorten(name: str, limit: int = 42) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def pretty(token: str) -> str:
    mapping = {"ctrl": "Ctrl", "control": "Ctrl", "shift": "Shift", "alt": "Alt",
               "win": "Win", "esc": "Esc", "space": "Space", "enter": "Enter"}
    lowered = token.lower()
    if lowered in mapping:
        return mapping[lowered]
    return token.upper() if len(token) == 1 else token


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
