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
from ..theme import rgba, theme, ui_font
from .control_bar import CountdownOverlay, RecordControlBar
from .overlay import CaptureOverlay
from .preview import ImagePreviewWindow
from .settings_dialog import SettingsWindow
from .widgets import (
    FluentButton, FluentMenu, FluentWindow, IconButton, SegmentedControl, Separator,
    TitleBar, show_toast,
)
from ..i18n import t as _t

SHAPES = [
    ("rectangle", _t("矩形区域"), "add_rect"),
    ("window", _t("窗口"), "window"),
    ("fullscreen", _t("全屏"), "fullscreen"),
    ("freeform", _t("自由绘制"), "freeform"),
]
SHAPE_ICONS = {key: icon for key, _, icon in SHAPES}

#: 主窗口的卡片尺寸。高度按 Windows 11 截图工具的主界面对齐：只留一行提示，
#: 不再显示保存位置，也没有底部的「打开保存文件夹」。
CARD_WIDTH, CARD_HEIGHT = 620, 287

LOOPBACK_HINTS = ("stereo mix", _t("立体声混音"), "what u hear", "voicemeeter", "cable output",
                  "loopback", _t("监视器"), _t("混音"))


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


def _cached_mics(wait: float = 0.0):
    """Microphone list from the background scan; starts one if needed.

    ``wait`` blocks until the scan lands (bounded). Starting a recording without
    the user's microphone is silent data loss, so the record path waits briefly
    for a scan that is already in flight; nothing else should.
    """
    from ..core.audio import cached_microphones, scan_microphones_async

    devices = cached_microphones()
    if devices:
        return devices
    thread = scan_microphones_async()
    if wait > 0:
        import time

        # The scan is already running on a worker thread, so this only waits for
        # work that has started; it is bounded so the UI cannot hang on ffmpeg.
        deadline = time.perf_counter() + wait
        while time.perf_counter() < deadline and thread is not None and thread.is_alive():
            time.sleep(0.02)
        devices = cached_microphones()
    return devices


class MainWindow(FluentWindow):
    """Command bar + hint area, mirroring 截图工具 on Windows 11."""

    captureRequested = Signal(str)          # camera | video
    settingsChanged = Signal()

    def __init__(self) -> None:
        super().__init__(None, resizable=True)
        self.setWindowTitle(_t("截图工具"))
        self.setWindowIcon(icons.app_icon())
        self.set_card_size(CARD_WIDTH, CARD_HEIGHT)
        # 最小尺寸就是卡片尺寸：这里的 +40 是阴影边距时代的遗留，边距归零后
        # 它把窗口锁死在 660x340，多出来的 40px 变成了空白。
        self.setMinimumSize(CARD_WIDTH, CARD_HEIGHT)

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
        # 启动时主题已经按当前设置应用过了，这里先记下签名 —— 否则"设置里第一次拨开关"
        # 会因为签名还是 None 而白跑一次约 1.8 秒的配色重建。
        self._applied_theme_signature = self._theme_signature()

        self._build()
        self.refresh_theme()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        # 标题栏要贴着窗口边缘（Win11 的标题按钮就在右上角），所以根布局不留边距；
        # 命令栏和内容区各自带 16/20px 内边距，视觉上不受影响。
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(_t("截图工具"), self)
        self.title_bar.icon_label.setPixmap(icons.app_icon().pixmap(16, 16))
        caption = self.title_bar.caption_buttons
        caption["min"].clicked.connect(self.minimize_animated)
        caption["max"].clicked.connect(self._toggle_max)
        caption["close"].clicked.connect(self.close)
        root.addWidget(self.title_bar)

        command = QWidget(self)
        command.setFixedHeight(56)
        command_layout = QHBoxLayout(command)
        command_layout.setContentsMargins(16, 0, 16, 0)
        command_layout.setSpacing(10)

        self.new_button = FluentButton(_t("新建"), command, variant="standard", icon_name="add",
                                       accent_icon=True, height=36, font_size=14)
        self.new_button.clicked.connect(self.start_capture)
        command_layout.addWidget(self.new_button)

        self.segmented = SegmentedControl([("camera", _t("截图")), ("video", _t("录屏"))], command,
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

        # 仍然创建它（其他地方会引用），但不放进布局：主界面与 Windows 11 截图
        # 工具一致，不显示这一行。功能保留在托盘右键菜单里。
        self.folder_button = FluentButton(_t("打开保存文件夹"), self.content, variant="hyperlink",
                                          icon_name="folder", height=28, font_size=12)
        self.folder_button.clicked.connect(self.open_output_folder)
        self.folder_button.setVisible(False)
        root.addWidget(self.content, 1)

        self._build_tray()
        self._update_hint()
        self._update_audio_icon()

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip(_t("截图工具"))
        menu = QMenu()
        self._tray_actions: list[tuple[object, str]] = []

        def add(source: str, slot) -> None:
            action = menu.addAction(_t(source), slot)
            self._tray_actions.append((action, source))

        add("新建截图", lambda: self.start_capture("camera"))
        add("新建录屏", lambda: self.start_capture("video"))
        menu.addSeparator()
        add("设置", self.open_settings)
        add("打开保存文件夹", self.open_output_folder)
        menu.addSeparator()
        add("退出", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

    # ------------------------------------------------------------------ #
    # Theme
    # ------------------------------------------------------------------ #
    def retranslate(self) -> None:
        """Re-apply every persistent label (interface language changed).

        Menus, toasts and dialogs are built on demand and pick up the new
        language by themselves; only long-lived widgets need this.
        """
        self.setWindowTitle(_t("截图工具"))
        self.title_bar.set_title(_t("截图工具"))
        self.title_bar.retranslate()
        self.new_button.setText(_t("新建"))
        self.segmented.set_labels([_t("截图"), _t("录屏")])
        self.folder_button.setText(_t("打开保存文件夹"))
        self.tray.setToolTip(_t("截图工具"))
        for action, source in getattr(self, "_tray_actions", []):
            action.setText(_t(source))
        self._update_hint()
        self._update_audio_icon()

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
            primary = _t("按 {0} 开始截图").format(self._hotkey_display(spec))
        else:
            spec = settings.hotkey_record
            primary = _t("按 {0} 开始录制").format(self._hotkey_display(spec))
        if self._hint_mode == "capture":
            primary = _t("拖动以选择区域 · Esc 取消")
        # 只留一行：Windows 11 截图工具的主界面就是这样，不再显示保存位置，
        # 底部的「打开保存文件夹」也一并去掉（托盘菜单里仍有同一功能）。
        self.hint.set_hint(primary, "")

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
        self.audio_button.setToolTip(_t("录制声音") if self._mode == "video" else _t("录屏时可选择声音来源"))

    def _show_shape_menu(self) -> None:
        menu = FluentMenu(self, min_width=210)
        for key, label, icon_name in SHAPES:
            enabled = key != "freeform" or self._mode == "camera"
            menu.add_item(label, icon_name=icon_name, checked=(key == self._shape), enabled=enabled,
                          radio=True, keep_open=False,
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
        menu.add_item(_t("录制麦克风"), icon_name="mic", checked=settings.mic_enabled,
                      on_activate=lambda: self._set_mic_enabled(not settings.mic_enabled))
        menu.add_item(_t("录制系统声音"), icon_name="sound", checked=settings.system_audio,
                      on_activate=lambda: self._set_system_audio(not settings.system_audio))
        menu.add_separator()

        # Never enumerate synchronously here: ffmpeg takes ~4.7 s and the menu
        # would freeze the window. Kick a scan and use whatever is cached.
        from ..core.audio import cached_microphones, microphones_scanned
        from ..core.audio import scan_microphones_async

        scan_microphones_async()
        devices = cached_microphones()
        microphones = [d for d in devices if not _is_loopback(d.name)]
        loopbacks = [d for d in devices if _is_loopback(d.name)]
        if not devices:
            menu.add_header(_t("音频设备"))
            menu.add_item(_t("未找到音频设备") if microphones_scanned() else _t("正在检测音频设备…"),
                          checked=False, on_activate=lambda: None)
            menu.add_separator()
        if microphones:
            menu.add_header(_t("麦克风设备"))
            for device in microphones[:12]:
                menu.add_item(_shorten(device.name), checked=(device.id == settings.mic_device), radio=True,
                              on_activate=lambda d=device: self._set_mic_device(d.id))
        if loopbacks:
            menu.add_header(_t("系统声音设备（回环）"))
            for device in loopbacks[:12]:
                menu.add_item(_shorten(device.name),
                              checked=(device.id == settings.system_audio_device), radio=True,
                              on_activate=lambda d=device: self._set_loopback_device(d.id))
        if not devices:
            menu.add_item(_t("未找到音频设备"), enabled=False)
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
        show_toast(_t(_t("麦克风已开启")) if enabled else _t(_t("麦克风已关闭")),
                   _t("录制时将") + (_t("采集") if enabled else _t("不采集")) + _t("麦克风声音"), "mic")

    def _set_system_audio(self, enabled: bool) -> None:
        settings.system_audio = enabled
        settings.save()
        self._update_audio_icon()
        if enabled and not settings.system_audio_device:
            from ..core.audio import cached_microphones, scan_microphones_async

            scan_microphones_async()
            loopback = next((d for d in cached_microphones() if _is_loopback(d.name)), None)
            if loopback:
                settings.system_audio_device = loopback.id
                settings.save()
            else:
                settings.system_audio = False
                settings.save()
                self._update_audio_icon()
                show_toast(_t("无法录制系统声音"),
                           _t("未找到立体声混音等回环设备。可在“声音设置”中启用“立体声混音”。"), "info")
                return
        show_toast(_t(_t("系统声音已开启")) if enabled else _t(_t("系统声音已关闭")), "", "sound")

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
        menu.add_header(_t("开始前延迟"))
        for value in (0, 3, 5, 10):
            menu.add_item(_t("无延迟") if value == 0 else _t("{0} 秒").format(value),
                            checked=(settings.countdown == value), radio=True,
                          on_activate=lambda v=value: self._set_countdown(v))
        menu.add_separator()
        autostart = startup.is_enabled()
        menu.add_item(_t("开机自动启动"), icon_name="monitor", checked=autostart,
                      on_activate=self._toggle_autostart)
        menu.add_item(_t("设置"), icon_name="settings", on_activate=self.open_settings)
        menu.add_item(_t("打开保存文件夹"), icon_name="folder", on_activate=self.open_output_folder)
        menu.add_separator()
        menu.add_item(_t("关于截图工具"), icon_name="info", on_activate=self._show_about)
        menu.popup(self.more_button.mapToGlobal(QPoint(0, self.more_button.height() + 6)))

    def _toggle_autostart(self) -> None:
        from .. import startup

        if startup.is_enabled():
            ok, message = startup.disable()
            show_toast(_t("开机自动启动已关闭") if ok else _t("操作失败"),
                       _t("已从注册表启动项中移除") if ok else message,
                       "info" if ok else "info", duration=4200 if ok else 5200)
        else:
            ok, message = startup.enable()
            show_toast(_t("开机自动启动已开启") if ok else _t("操作失败"),
                       _t("登录 Windows 后会在通知区域静默运行，可直接用快捷键唤起")
                       if ok else message,
                       "check" if ok else "info", duration=5200)
        if self._settings_window is not None:
            self._settings_window.refresh_theme()

    def _set_countdown(self, value: int) -> None:
        settings.countdown = value
        settings.save()
        show_toast(_t("延迟已设置"),
                       _t("无延迟") if value == 0 else _t("{0} 秒后开始").format(value),
                       "timer")

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
            show_toast(_t("正在录制中"), _t("按 Ctrl+Alt+Q 停止录制，Ctrl+Alt+P 暂停/继续"),
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
            show_toast(_t("无法启动捕获"), _t("请查看日志 %APPDATA%\\WinSnipRec\\app.log"), "info")
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
            show_toast(_t("截图失败"), _t("无法读取屏幕内容"), "info")
            self._restore_main()
            return
        if settings.copy_image_to_clipboard:
            QGuiApplication.clipboard().setImage(image)
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H%M%S")
        path = Path(settings.image_dir) / f"截图 {stamp}.png"
        try:
            if not image.save(str(path), "PNG"):
                raise OSError(_t("PNG 编码失败"))
        except Exception as exc:
            show_toast(_t("保存失败"), str(exc), "info")
        self._preview = ImagePreviewWindow(str(path), image)
        self._preview.closed.connect(self._restore_main)
        self._preview.show()
        if settings.copy_image_to_clipboard:
            show_toast(_t("已复制到剪贴板"), _t("同时保存到 {0}").format(path), "copy")

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
            device = next((d for d in _cached_mics(wait=1.5)
                           if not _is_loopback(d.name)), None)
            if device is None:
                import logging

                logging.getLogger(__name__).warning(
                    "no microphone found; recording without audio (device scan "
                    "may still be running)")
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
        show_toast(_t("录屏已开始"), f"{physical.width()}×{physical.height()} · {settings.fps} fps",
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
            show_toast(_t("无法在录制中切换麦克风"), _t("请先停止录制，然后在工具栏中选择声音来源"), "info")
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
                show_toast(_t("未找到麦克风"), "", "info")
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
        show_toast(_t("录制出现问题"), message, "info")

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
        show_toast(_t("录制已保存"), f"{Path(path).name} · {_human_size(size)}", "check",
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
            show_toast(_t("已取消录制"), _t("临时文件已删除"), "trash")
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
            self._settings_built_language = getattr(settings, "language", "system")
        elif getattr(self, "_settings_built_language", None) != getattr(settings, "language", "system"):
            # 语言变了才重建：界面文字是在构造时取的 _t()，不重建就会留着旧语言。
            self._settings_window = None
            self.open_settings()
            return
        else:
            # 复用已有实例。实测构造一次要 ~1.3 秒、show 又要 0.7 秒，加上淡入近 3 秒
            # —— 用户报的"打开设置有明显卡顿"就是因为以前关闭时把它丢掉了，每次
            # 打开都从头重建。这里只把可能被别处改过的显示值同步一下。
            self._settings_window.refresh_theme()
            self._settings_window.sync_volatile_rows()
            # 复用也要有打开动画：之前为了消掉 2.5 秒的卡顿把这里也一起静音了，
            # 结果窗口直接蹦出来、没有过渡。现在动画起点是 0.92（不再像块玻璃）、
            # 时长 150ms，慢机器上约 0.5 秒落位 —— 有过渡但不拖沓。
            # 用「重新打开」而不是首次打开：slide 小一点，观感更轻。
            self._settings_window._open_slide = 8
            # 显式复位：万一之前被置过 True（旧版本的行为），窗口会一直不播动画。
            self._settings_window._suppress_open_animation = False
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    #: 影响配色/材质重建的设置项。只有这些变了才需要重建调色板与窗口背景。
    _THEME_ATTRS = ("theme", "style", "backdrop", "reveal")

    def _theme_signature(self) -> tuple:
        return tuple(getattr(settings, name, None) for name in self._THEME_ATTRS)

    def _on_settings_applied(self) -> None:
        from PySide6.QtWidgets import QApplication

        from .. import anim
        from ..theme import apply_app_theme

        # 大多数设置项（各种开关、帧率、目录…）跟配色无关，但它们同样会走这条路径。
        # 以前一律重建调色板 + 给每个顶层窗口 invalidate_backdrop()，实测接近 1 秒 ——
        # 这就是"点开关有卡顿"的来源。先比签名，没变就只刷新提示后返回。
        signature = self._theme_signature()
        if signature == getattr(self, "_applied_theme_signature", None):
            self._update_hint()
            self.settingsChanged.emit()
            return
        self._applied_theme_signature = signature

        app = QApplication.instance()
        was_dark = theme.dark
        windows = [w for w in (app.topLevelWidgets() if app is not None else []) if w.isVisible()]

        def apply_theme() -> None:
            theme.mode = settings.theme
            theme.refresh()
            if app is not None:
                # Palette + stylesheet must be rebuilt, otherwise the Qt-drawn
                # controls (combo boxes and their popups) keep the old theme.
                apply_app_theme(app)
            self.refresh_theme()
            self._update_hint()
            for widget in app.topLevelWidgets() if app is not None else []:
                # 背景来自缓存的 static_card()，不清掉的话明暗切换后窗口底色还是旧的
                # ——实测：以深色启动是 #303233，但实时切到深色后仍是 #F0F2F4。
                # （_on_style_changed 里本来就调了 invalidate_backdrop，这里漏了。）
                invalidate = getattr(widget, "invalidate_backdrop", None)
                if callable(invalidate):
                    try:
                        invalidate()
                    except Exception:
                        pass
                refresh = getattr(widget, "refresh_theme", None)
                if callable(refresh):
                    try:
                        refresh()
                    except Exception:
                        pass
                widget.update()

        # 明暗真的翻转时做交叉淡变（旧画面在上层淡出），改其它设置项则完全不闪。
        anim.fade_theme_change(windows, apply_theme, changed=lambda: theme.dark != was_dark)
        self.settingsChanged.emit()

    def _on_settings_closed(self) -> None:
        # 不再丢弃实例：SettingsWindow 的构造实测 ~1.3 秒，丢掉就意味着下次打开
        # 又要重建一次（加上 show 与淡入接近 3 秒），那就是用户感觉到的卡顿。
        # 实例保留为隐藏的顶层窗口，下次 open_settings 直接复用。
        pass

    def open_output_folder(self) -> None:
        folder = settings.video_dir if self._mode == "video" else settings.image_dir
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            os.startfile(folder)  # noqa: S606
        except Exception as exc:
            show_toast(_t("无法打开文件夹"), str(exc), "info")

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
            show_toast(_t("截图工具仍在运行"), _t("按 Win+Shift+S 截图，Win+Shift+R 录屏；右键托盘图标退出"),
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
