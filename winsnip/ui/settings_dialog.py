"""Settings and about windows."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QScrollArea, QSlider,
    QVBoxLayout, QWidget,
)

from .. import __version__, icons, startup
from .. import i18n as _i18n
from .. import anim
from ..settings import Settings, settings
from ..theme import apply_app_theme, rgba, theme, ui_font
from .widgets import (
    FluentButton, FluentComboBox, FluentWindow, Separator, TitleBar, ToggleSwitch, show_toast,
)
from ..i18n import t as _t

BACKDROP_LEVELS = [_t("自动"), _t("经典（壁纸）"), _t("强制实时")]
REVEAL_LEVELS = [_t("低"), _t("中"), _t("高")]
REVEAL_VALUES = ["weak", "normal", "strong"]

QUALITY_PRESETS = [(_t("高质量 (CRF 18)"), 18), (_t("较高 (CRF 20)"), 20), (_t("标准 (CRF 23)"), 23),
                   (_t("较小体积 (CRF 26)"), 26)]
FPS_PRESETS = [15, 24, 30, 60]


class _Row(QWidget):
    def __init__(self, title: str, subtitle: str = "", control: QWidget | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(16)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self.title = QLabel(title, self)
        self.title.setFont(ui_font(14))
        text_layout.addWidget(self.title)
        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setFont(ui_font(12))
        self.subtitle.setWordWrap(True)
        if subtitle:
            text_layout.addWidget(self.subtitle)
        layout.addLayout(text_layout, 1)
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.refresh()

    def refresh(self) -> None:
        palette = theme.palette
        self.title.setStyleSheet(f"color: {palette.text_primary};")
        self.subtitle.setStyleSheet(f"color: {palette.text_secondary};")


class SettingsWindow(FluentWindow):
    applied = Signal()
    devices_ready = Signal(object)   # 后台扫描完成后回主线程
    closed = Signal()

    def __init__(self) -> None:
        # Win10 风格的窗口背景要用"真实屏幕内容"做高斯，所以必须在窗口出现前先抓一张。
        try:
            from .widgets import capture_desktop_shot

            capture_desktop_shot()
        except Exception:
            pass
        super().__init__(None, resizable=True)
        self.setWindowTitle(_t("设置"))
        self.setWindowIcon(icons.app_icon())
        self.set_card_size(600, 640)
        self.setMinimumSize(520, 480)   # +40 是阴影边距时代的遗留
        self._rows: list[_Row] = []
        self._row_separators: list[QWidget] = []

        root = QVBoxLayout(self)
        # 标题栏铺满窗口（与主窗口一致）；body 自带 24px 内边距
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(_t("设置"), self)
        self.title_bar.icon_label.setPixmap(icons.app_icon().pixmap(16, 16))
        self.title_bar.caption_buttons["min"].clicked.connect(self.minimize_animated)
        self.title_bar.caption_buttons["max"].clicked.connect(self._toggle_max)
        self.title_bar.caption_buttons["close"].clicked.connect(self.close)
        root.addWidget(self.title_bar)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }"
                             "QScrollArea > QWidget > QWidget { background: transparent; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(24, 8, 24, 16)
        self.body_layout.setSpacing(0)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # 设备下拉的状态与后台扫描回调连接，必须早于 _build_rows()
        self._device_rows: list[tuple[QComboBox, str, bool]] = []
        self.devices_ready.connect(self._on_devices_ready)

        self._build_rows()
        self._add_search_box()

        footer = QWidget(self)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 8, 24, 18)
        footer_layout.setSpacing(10)
        self.reset_button = FluentButton(_t("恢复默认"), footer, variant="subtle", height=36)
        self.reset_button.clicked.connect(self._reset)
        self.guide_button = FluentButton(_t("重新运行引导"), footer, variant="subtle",
                                         height=36)
        self.guide_button.clicked.connect(self._run_onboarding)
        footer_layout.addWidget(self.guide_button)
        footer_layout.addWidget(self.reset_button)
        footer_layout.addStretch(1)
        self.done_button = FluentButton(_t("完成"), footer, variant="accent", height=36)
        self.done_button.clicked.connect(self.close)
        footer_layout.addWidget(self.done_button)
        root.addWidget(footer)

        self.refresh_theme()

    # ------------------------------------------------------------------ #
    def _section(self, title: str) -> None:
        label = QLabel(title, self)
        label.setFont(ui_font(12, 600))
        label.setContentsMargins(0, 14, 0, 2)
        self.body_layout.addWidget(label)
        self._section_labels = getattr(self, "_section_labels", [])
        self._section_labels.append(label)

    def sync_volatile_rows(self) -> None:
        """Re-read the values that can also be changed outside this dialog.

        The window is reused between openings now (rebuilding it cost ~1.3s), so a
        few rows could otherwise show stale values: the microphone also has a menu
        in the command bar, the backdrop note is written by the live probe, and the
        autostart switch reflects a registry entry that can change elsewhere.
        """
        try:
            index = self.mic_combo.findData(settings.mic_device)
            if index >= 0 and index != self.mic_combo.currentIndex():
                blocked = self.mic_combo.blockSignals(True)
                self.mic_combo.setCurrentIndex(index)
                self.mic_combo.blockSignals(blocked)
        except Exception:
            pass
        try:
            if hasattr(self, "_autostart_row"):
                self._autostart_row.subtitle.setText(startup.describe())
        except Exception:
            pass
        try:
            if hasattr(self, "backdrop_combo"):
                for row in self._rows:
                    if getattr(row, "control", None) is self.backdrop_combo:
                        row.subtitle.setText(self._backdrop_note())
                        break
        except Exception:
            pass

    def _add_row(self, title: str, subtitle: str, control: QWidget | None) -> _Row:
        row = _Row(title, subtitle, control, self)
        self._rows.append(row)
        self.body_layout.addWidget(row)
        separator = Separator(self, vertical=False)
        # Kept so the search filter can hide the divider with its row.
        self._row_separators.append(separator)
        self.body_layout.addWidget(separator)
        return row

    def _build_rows(self) -> None:
        self._section(_t("外观"))
        self.language_combo = FluentComboBox(self)
        for code, label in _i18n.available():
            self.language_combo.addItem(label, code)
        index = self.language_combo.findData(getattr(settings, "language", "system"))
        self.language_combo.setCurrentIndex(index if index >= 0 else 0)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._add_row(_t("界面语言"), _t("切换后立即生效，无需重启"), self.language_combo)

        self.theme_combo = FluentComboBox(self)
        self.theme_combo.addItems([_t("跟随系统"), _t("浅色"), _t("深色")])
        self.theme_combo.setCurrentIndex({"system": 0, "light": 1, "dark": 2}.get(settings.theme, 0))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self._add_row(_t("主题"), _t("浅色或深色外观，默认跟随 Windows 设置"), self.theme_combo)

        self.style_combo = FluentComboBox(self)
        self.style_combo.addItems([_t("跟随系统"), "Windows 11", "Windows 10"])
        self.style_combo.setCurrentIndex(
            {"system": 0, "win11": 1, "win10": 2}.get(getattr(settings, "style", "win11"), 1))
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self._add_row(_t("界面风格"), _t("窗口圆角、材质与标题栏按钮的样式"), self.style_combo)

        self.backdrop_combo = FluentComboBox(self)
        self.backdrop_combo.addItems(BACKDROP_LEVELS)
        self.backdrop_combo.setCurrentIndex(
            {"auto": 0, "classic": 1, "native": 2}.get(
                getattr(settings, "backdrop", "auto"), 0))
        self.backdrop_combo.currentIndexChanged.connect(self._on_backdrop_changed)
        self._add_row(_t("背景材质"), self._backdrop_note(), self.backdrop_combo)

        self.reveal_combo = FluentComboBox(self)
        self.reveal_combo.addItems(REVEAL_LEVELS)
        # 默认最低档：浅色底色离纯白只剩 12 级余量，光越淡越不像染色。
        self.reveal_combo.setCurrentIndex(
            {"weak": 0, "normal": 1, "strong": 2}.get(
                getattr(settings, "reveal_strength", "weak"), 0))
        self.reveal_combo.currentIndexChanged.connect(
            lambda index: self._set("reveal_strength", REVEAL_VALUES[index]))
        self._add_row(_t("光效强度"),
                      _t("Windows 10 风格下跟随鼠标的高光强度，也用于按钮悬停边框"),
                      self.reveal_combo)
        # 用户："在 win11 风格下隐藏光效强度" —— 这一项只有 Win10 风格才有效。
        self._reveal_row = self._rows[-1]
        self._reveal_row.setVisible(theme.is_win10)

        # 用户："在 win10 风格下，再做一个可调节背景透明程度的调节按钮"。
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(getattr(settings, "backdrop_opacity", 45)))
        self.opacity_slider.setFixedWidth(150)
        self.opacity_slider.sliderReleased.connect(self._on_backdrop_opacity_changed)
        self._add_row(
            _t("背景不透明度"),
            _t("Windows 10 风格下窗口背景的实心程度：越小越透，越能看清桌面内容"),
            self.opacity_slider)
        self._opacity_row = self._rows[-1]
        self._opacity_row.setVisible(theme.is_win10)

        self.tray_toggle = ToggleSwitch(settings.minimize_to_tray, self)
        self.tray_toggle.toggled.connect(lambda v: self._set("minimize_to_tray", v))
        self._add_row(_t("最小化到系统托盘"), _t("关闭窗口时继续在后台运行，可随时用快捷键唤起"), self.tray_toggle)

        self.open_folder_toggle = ToggleSwitch(settings.open_folder_when_done, self)
        self.open_folder_toggle.toggled.connect(lambda v: self._set("open_folder_when_done", v))
        self._add_row(_t("录制完成后打开文件夹"), _t("结束时自动在资源管理器中定位文件"), self.open_folder_toggle)

        self.autostart_toggle = ToggleSwitch(startup.is_enabled(), self)
        self.autostart_toggle.toggled.connect(self._on_autostart_toggled)
        self._add_row(_t("开机自动启动"), startup.describe(), self.autostart_toggle)
        self._autostart_row = self._rows[-1]

        self.animation_toggle = ToggleSwitch(settings.animations, self)
        self.animation_toggle.toggled.connect(self._on_animations_toggled)
        self._add_row(_t("界面动画"), _t("启动动画、窗口淡入与滑动效果；Windows 关闭「显示动画」时自动跳过"),
                      self.animation_toggle)

        self._section(_t("录制"))
        self.fps_combo = FluentComboBox(self)
        for value in FPS_PRESETS:
            self.fps_combo.addItem(f"{value} fps", value)
        index = self.fps_combo.findData(settings.fps)
        self.fps_combo.setCurrentIndex(index if index >= 0 else 2)
        self.fps_combo.currentIndexChanged.connect(
            lambda: self._set("fps", self.fps_combo.currentData()))
        self._add_row(_t("帧率"), _t("帧率越高越流畅，文件也越大"), self.fps_combo)

        self.quality_combo = FluentComboBox(self)
        for label, crf in QUALITY_PRESETS:
            self.quality_combo.addItem(label, crf)
        index = self.quality_combo.findData(settings.crf)
        self.quality_combo.setCurrentIndex(index if index >= 0 else 1)
        self.quality_combo.currentIndexChanged.connect(
            lambda: self._set("crf", self.quality_combo.currentData()))
        self._add_row(_t("画质"), _t("H.264 编码质量 (CRF)"), self.quality_combo)

        self.cursor_toggle = ToggleSwitch(settings.capture_cursor, self)
        self.cursor_toggle.toggled.connect(lambda v: self._set("capture_cursor", v))
        self._add_row(_t("录制鼠标光标"), _t("在画面中绘制鼠标指针"), self.cursor_toggle)

        self.delay_combo = FluentComboBox(self)
        for value in (0, 3, 5, 10):
            self.delay_combo.addItem(_t("无延迟") if value == 0 else _t("{0} 秒").format(value),
                                     value)
        index = self.delay_combo.findData(settings.countdown)
        self.delay_combo.setCurrentIndex(index if index >= 0 else 0)
        self.delay_combo.currentIndexChanged.connect(
            lambda: self._set("countdown", self.delay_combo.currentData()))
        self._add_row(_t("开始前倒计时"), _t("点击新建后等待指定秒数再开始"), self.delay_combo)

        self.confirm_toggle = ToggleSwitch(settings.confirm_region, self)
        self.confirm_toggle.toggled.connect(lambda v: self._set("confirm_region", v))
        self._add_row(
            _t("框选后需要确认"),
            _t("关闭时与 Windows 11 一致：松开鼠标立即开始；"
               "打开后可用手柄调整区域，按确认或回车才开始"),
            self.confirm_toggle)

        self._section(_t("音频"))
        self.mic_toggle = ToggleSwitch(settings.mic_enabled, self)
        self.mic_toggle.toggled.connect(self._on_mic_toggled)
        self._add_row(_t("录制麦克风"), _t("在视频中混入麦克风声音"), self.mic_toggle)

        self.mic_combo = FluentComboBox(self)
        self.mic_combo.setMinimumWidth(230)
        self._populate_devices(self.mic_combo, settings.mic_device, loopback=False)
        self.mic_combo.currentIndexChanged.connect(
            lambda: self._set("mic_device", self.mic_combo.currentData() or ""))
        self._add_row(_t("麦克风设备"), _t("选择要录制的输入设备"), self.mic_combo)

        self.sound_toggle = ToggleSwitch(settings.system_audio, self)
        self.sound_toggle.toggled.connect(lambda v: self._set("system_audio", v))
        self._add_row(_t("录制系统声音"), _t("需要“立体声混音”等回环设备；Windows 10 默认未启用"), self.sound_toggle)

        self.sound_combo = FluentComboBox(self)
        self.sound_combo.setMinimumWidth(230)
        self._populate_devices(self.sound_combo, settings.system_audio_device, loopback=True)
        self.sound_combo.currentIndexChanged.connect(
            lambda: self._set("system_audio_device", self.sound_combo.currentData() or ""))
        self._add_row(_t("系统声音设备"), _t("回环设备 (What U Hear / 立体声混音 / VoiceMeeter)"), self.sound_combo)

        self._section(_t("保存位置"))
        self.video_choose = FluentButton(_t("更改…"), self, variant="standard", height=32, font_size=12)
        self.video_choose.clicked.connect(lambda: self._choose_dir("video_dir"))
        holder = QWidget(self)
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(self.video_choose)
        self._add_row(_t("视频文件夹"), settings.video_dir, holder)
        self._rows[-1].subtitle.setWordWrap(True)
        self._video_row = self._rows[-1]

        self.image_choose = FluentButton(_t("更改…"), self, variant="standard", height=32, font_size=12)
        self.image_choose.clicked.connect(lambda: self._choose_dir("image_dir"))
        holder2 = QWidget(self)
        holder2_layout = QHBoxLayout(holder2)
        holder2_layout.setContentsMargins(0, 0, 0, 0)
        holder2_layout.addWidget(self.image_choose)
        self._add_row(_t("图片文件夹"), settings.image_dir, holder2)
        self._image_row = self._rows[-1]

        self._section(_t("快捷键"))
        self.hotkey_snip_combo = FluentComboBox(self)
        self.hotkey_record_combo = FluentComboBox(self)
        options = ["Win+Shift+S", "Win+Shift+R", "Ctrl+Alt+S", "Ctrl+Alt+R", "Ctrl+Shift+S",
                   "Ctrl+Shift+R", "PrintScreen"]
        for combo, current in ((self.hotkey_snip_combo, settings.hotkey_snip),
                               (self.hotkey_record_combo, settings.hotkey_record)):
            combo.addItems(options)
            if current in options:
                combo.setCurrentText(current)
        self.hotkey_snip_combo.currentTextChanged.connect(
            lambda text: self._set("hotkey_snip", text))
        self.hotkey_record_combo.currentTextChanged.connect(
            lambda text: self._set("hotkey_record", text))
        self._add_row(_t("截图快捷键"), _t("若被系统占用，程序会自动回退到备用组合"), self.hotkey_snip_combo)
        self._add_row(_t("录屏快捷键"), _t("截图工具 (Windows 11) 会占用 Win+Shift+R"), self.hotkey_record_combo)

    def _populate_devices(self, combo: QComboBox, current: str, loopback: bool) -> None:
        """Fill a device list without blocking the UI thread.

        Reading the cache is instant; the first scan runs on a worker thread and
        the combos are re-filled when it reports back.
        """
        from ..core.audio import cached_microphones, scan_microphones_async

        self._device_rows.append((combo, current, loopback))
        self._fill_devices(combo, current, loopback, cached_microphones())
        scan_microphones_async(done=self._devices_scanned)

    def _devices_scanned(self, devices) -> None:
        """Runs on the worker thread; the signal hops back to the GUI thread."""
        self.devices_ready.emit(list(devices))

    def _on_devices_ready(self, devices) -> None:
        for combo, current, loopback in self._device_rows:
            # Prefer whatever the user has selected by now.
            picked = combo.currentData() or current
            self._fill_devices(combo, picked, loopback, devices)

    def _fill_devices(self, combo: QComboBox, current: str, loopback: bool,
                      devices) -> None:
        from .main_window import _is_loopback

        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_t("（未选择）"), "")
        for device in devices:
            if _is_loopback(device.name) != loopback:
                continue
            combo.addItem(device.name, device.id)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    # ------------------------------------------------------------------ #
    def _backdrop_note(self) -> str:
        """Say what the probe found, so the choice is not a mystery."""
        from .. import backdrop

        supported = backdrop.native_available()
        if supported:
            return _t("本机支持实时模糊，用它更真实；不支持时会自动回退")
        return _t("本机实测不支持系统实时模糊（已自动回退到壁纸材质）")

    def _on_backdrop_changed(self, index: int) -> None:
        self._set("backdrop", ["auto", "classic", "native"][index])

    def _set(self, attribute: str, value) -> None:
        setattr(settings, attribute, value)
        settings.save()
        self.applied.emit()

    def _on_language_changed(self, index: int) -> None:
        code = self.language_combo.itemData(index) or "system"
        self._set("language", code)
        _i18n.set_language(code)
        from .widgets import retranslate_windows

        retranslate_windows()
        # Rebuild the window so every label picks up the new language. The
        # dialog is cheap to rebuild and the user sees the result immediately.
        QTimer.singleShot(0, self._rebuild_after_language_change)

    def _rebuild_after_language_change(self) -> None:
        parent = self.parent()
        geometry = self.geometry()
        self.close()
        if parent is not None and hasattr(parent, "_settings_window"):
            parent._settings_window = None
            parent.open_settings()
            window = parent._settings_window
            if window is not None:
                window.setGeometry(geometry)

    def _run_onboarding(self) -> None:
        """Reopen the guide; the settings window gets out of the way."""
        from .onboarding import show_onboarding

        self.close()
        show_onboarding()

    # ------------------------------------------------------------------ #
    # Search + easter egg
    # ------------------------------------------------------------------ #
    def _add_search_box(self) -> None:
        from PySide6.QtWidgets import QLineEdit

        holder = QWidget(self)
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(0)
        self.search_box = QLineEdit(holder)
        self.search_box.setPlaceholderText(_t("搜索设置"))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search)
        layout.addWidget(self.search_box)
        self.body_layout.insertWidget(0, holder)
        self._search_holder = holder

        # Shown when the filter hides everything, so the body is not just blank.
        self._empty_hint = QLabel(_t("没有匹配的设置项"), self)
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setVisible(False)
        self.body_layout.insertWidget(1, self._empty_hint)

    def _on_search(self, text: str) -> None:
        from .easter_egg import show_easter_egg, triggers

        self._filter_rows(text)
        if triggers(text):
            show_easter_egg(self)

    def _filter_rows(self, text: str) -> None:
        """Hide rows whose title and subtitle do not contain the query."""
        needle = (text or "").strip().lower()
        visible = 0
        for index, row in enumerate(self._rows):
            haystack = f"{row.title.text()} {row.subtitle.text()}".lower()
            match = not needle or needle in haystack
            row.setVisible(match)
            separator = (self._row_separators[index]
                         if index < len(self._row_separators) else None)
            if separator is not None:
                separator.setVisible(match)
            visible += int(match)
        for label in getattr(self, "_section_labels", []):
            if needle:
                label.setVisible(False)
            else:
                label.setVisible(True)
        if hasattr(self, "_empty_hint"):
            self._empty_hint.setVisible(bool(needle) and visible == 0)

    def _on_theme_changed(self, index: int) -> None:
        self._set("theme", ["system", "light", "dark"][index])

    def _on_backdrop_opacity_changed(self) -> None:
        """拖动完滑块后保存并让所有窗口重新生成背景。"""
        value = int(self.opacity_slider.value())
        self._set("backdrop_opacity", value)
        for widget in QApplication.topLevelWidgets():
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

    def _set_row_visible_animated(self, row, visible: bool) -> None:
        """带展开/收起动画地显示或隐藏一行（光效强度用）。

        - 展开：高度 0 -> 自然高度，同时淡入；
        - 收起：自然高度 -> 0，同时淡出，结束后 setVisible(False)。
        """
        if row is None:
            return
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        effect = row.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(row)
            row.setGraphicsEffect(effect)
        if not anim.animations_enabled():
            row.setMaximumHeight(16777215)
            effect.setOpacity(1.0 if visible else 0.0)
            row.setVisible(visible)
            return
        if visible:
            row.setVisible(True)
        full = max(1, row.sizeHint().height())
        start_h = row.maximumHeight() if row.isVisible() else 0
        if start_h >= 16777215 or start_h <= 0:
            start_h = full if row.isVisible() and not visible else 0
        end_h = full if visible else 0
        row.setMaximumHeight(start_h)
        anim_h = QPropertyAnimation(row, b"maximumHeight", row)
        anim_h.setDuration(240)
        anim_h.setStartValue(start_h)
        anim_h.setEndValue(end_h)
        anim_h.setEasingCurve(anim.curve("decelerate"))
        anim_o = QPropertyAnimation(effect, b"opacity", row)
        anim_o.setDuration(240)
        anim_o.setStartValue(0.0 if visible else 1.0)
        anim_o.setEndValue(1.0 if visible else 0.0)
        anim_o.setEasingCurve(anim.curve("out"))

        def _finish() -> None:
            try:
                if not visible:
                    row.setVisible(False)
                row.setMaximumHeight(16777215)
                effect.setOpacity(1.0)
            except RuntimeError:
                pass

        anim_h.finished.connect(_finish)
        anim_h.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        anim_o.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_style_changed(self, index: int) -> None:
        name = ["system", "win11", "win10"][index]
        self._set("style", name)
        theme.style = name
        theme.refresh()
        apply_app_theme(QApplication.instance())
        # 已打开的窗口要重新计算圆角与背景，所以整体刷新一遍
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, "invalidate_backdrop"):
                widget.invalidate_backdrop()
            if hasattr(widget, "refresh_theme"):
                widget.refresh_theme()
        # 光效强度只在 Win10 风格下有意义，切换风格时同步显隐。
        row = getattr(self, "_reveal_row", None)
        if row is not None:
            self._set_row_visible_animated(row, theme.is_win10)
            opacity_row = getattr(self, "_opacity_row", None)
            if opacity_row is not None:
                self._set_row_visible_animated(opacity_row, theme.is_win10)
        label = {"system": _t("跟随系统"), "win11": "Windows 11", "win10": "Windows 10"}[name]
        show_toast(_t("界面风格已切换"), _t("当前：{0}").format(label), "check",
                       duration=2600)

    def _on_autostart_toggled(self, enabled: bool) -> None:
        ok, message = startup.enable() if enabled else startup.disable()
        if not ok:
            # Revert the switch so the UI never lies about the real state.
            self.autostart_toggle.blockSignals(True)
            self.autostart_toggle.setChecked(not enabled)
            self.autostart_toggle.blockSignals(False)
            show_toast(_t("开机自启设置失败"), message, "info", duration=5200)
        else:
            show_toast(_t(_t("开机自动启动已开启")) if enabled else _t(_t("开机自动启动已关闭")),
                       _t("登录 Windows 后将在通知区域静默运行") if enabled else
                       _t("已从注册表启动项中移除"),
                       "check" if enabled else "info")
        self._refresh_autostart_row()

    def _refresh_autostart_row(self) -> None:
        row = getattr(self, "_autostart_row", None)
        if row is not None:
            row.subtitle.setText(startup.describe())

    def _on_animations_toggled(self, enabled: bool) -> None:
        self._set("animations", enabled)
        if enabled:
            show_toast(_t("界面动画已开启"), _t("启动动画、窗口淡入与滑动效果已启用"), "check",
                       duration=2600)
        else:
            show_toast(_t("界面动画已关闭"), _t("界面将立即切换，不再有过渡效果"), "info",
                       duration=2600)

    def _on_mic_toggled(self, enabled: bool) -> None:
        self._set("mic_enabled", enabled)
        if enabled and not settings.mic_device:
            from ..core.audio import default_microphone

            device = default_microphone()
            if device:
                settings.mic_device = device.id
                settings.save()
                index = self.mic_combo.findData(device.id)
                if index >= 0:
                    self.mic_combo.setCurrentIndex(index)

    def _choose_dir(self, attribute: str) -> None:
        folder = QFileDialog.getExistingDirectory(self, _t("选择文件夹"), getattr(settings, attribute))
        if not folder:
            return
        setattr(settings, attribute, folder)
        settings.save()
        self.refresh_theme()          # updates the path shown in the row subtitle
        self.applied.emit()
        show_toast(_t("保存位置已更新"), folder, "folder")

    def _reset(self) -> None:
        defaults = Settings()
        for field_name in ("theme", "fps", "crf", "capture_cursor", "countdown",
                           "minimize_to_tray", "open_folder_when_done", "mic_enabled",
                           "system_audio"):
            setattr(settings, field_name, getattr(defaults, field_name))
        settings.save()
        self.theme_combo.setCurrentIndex({"system": 0, "light": 1, "dark": 2}[settings.theme])
        self.fps_combo.setCurrentIndex(max(0, self.fps_combo.findData(settings.fps)))
        self.quality_combo.setCurrentIndex(max(0, self.quality_combo.findData(settings.crf)))
        self.cursor_toggle.setChecked(settings.capture_cursor)
        self.delay_combo.setCurrentIndex(max(0, self.delay_combo.findData(settings.countdown)))
        self.confirm_toggle.setChecked(settings.confirm_region)
        self.tray_toggle.setChecked(settings.minimize_to_tray)
        self.open_folder_toggle.setChecked(settings.open_folder_when_done)
        self.mic_toggle.setChecked(settings.mic_enabled)
        self.sound_toggle.setChecked(settings.system_audio)
        self.applied.emit()
        show_toast(_t("已恢复默认设置"), "", "check")

    def _toggle_max(self) -> None:
        self.toggle_maximized()
        button = self.title_bar.caption_buttons["max"]
        button.kind = "restore" if self.is_maximized() else "max"
        button.update()

    # ------------------------------------------------------------------ #
    def refresh_theme(self) -> None:
        self.title_bar.refresh()
        palette = theme.palette
        for row in self._rows:
            row.refresh()
        # 下拉弹窗是独立的原生窗口，样式只在 showPopup 时套过一次。切主题时它可能正开着
        # （点选后不再关闭），不重套的话就会出现"窗口已经变浅、弹窗还是深色"。
        for combo in self.findChildren(FluentComboBox):
            combo._style_popup()
        for label in getattr(self, "_section_labels", []):
            label.setStyleSheet(f"color: {palette.text_secondary};")
        if hasattr(self, "_video_row"):
            self._video_row.subtitle.setText(settings.video_dir)
        if hasattr(self, "_image_row"):
            self._image_row.subtitle.setText(settings.image_dir)
        if hasattr(self, "_autostart_row"):
            self._autostart_row.subtitle.setText(startup.describe())
            self.autostart_toggle.blockSignals(True)
            self.autostart_toggle.setChecked(startup.is_enabled())
            self.autostart_toggle.blockSignals(False)
        if hasattr(self, "animation_toggle"):
            self.animation_toggle.blockSignals(True)
            self.animation_toggle.setChecked(bool(settings.animations))
            self.animation_toggle.blockSignals(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        settings.save()
        super().closeEvent(event)
        self.closed.emit()


class AboutWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle(_t("关于"))
        self.setWindowIcon(icons.app_icon())
        self.set_card_size(430, 322)
        root = QVBoxLayout(self)
        # 标题栏铺满窗口（与主窗口一致）；body 自带 24px 内边距
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(_t("关于"), self)
        self.title_bar.icon_label.setPixmap(icons.app_icon().pixmap(16, 16))
        self.title_bar.caption_buttons["max"].setVisible(False)
        self.title_bar.caption_buttons["min"].clicked.connect(self.minimize_animated)
        self.title_bar.caption_buttons["close"].clicked.connect(self.close)
        root.addWidget(self.title_bar)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 12, 24, 20)
        layout.setSpacing(8)
        icon_label = QLabel(body)
        icon_label.setPixmap(icons.app_icon().pixmap(56, 56))
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        name = QLabel(_t("截图工具 WinSnipRec"), body)
        name.setFont(ui_font(18, 600))
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)
        version = QLabel(_t("版本 {0}").format(__version__), body)
        version.setFont(ui_font(12))
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        description = QLabel(
            _t("在 Windows 10 上重现 Windows 11 截图工具的录屏体验。\n"
               "区域 / 窗口 / 全屏录制 · 暂停继续 · 麦克风与系统声音 · H.264 MP4 输出。\n"
               "界面、图标与配色按 Windows 11 Fluent 设计规范绘制。"),
            body,
        )
        description.setFont(ui_font(12))
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description)

        layout.addSpacing(2)
        self.producer = QLabel(_t("制作人：天童 アリス"), body)
        self.producer.setObjectName("aboutProducer")
        self.producer.setFont(ui_font(12, 600))
        self.producer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.producer)

        layout.addStretch(1)
        close_button = FluentButton(_t("确定"), body, variant="accent", height=36)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(body, 1)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self.title_bar.refresh()
        palette = theme.palette
        for label in self.findChildren(QLabel):
            if label.pixmap() is not None and not label.pixmap().isNull():
                continue
            label.setStyleSheet(f"color: {palette.text_primary};")
        # After the loop: it paints every label primary, and the credit should
        # stand out.
        producer = getattr(self, "producer", None)
        if producer is not None:
            producer.setStyleSheet(f"color: {palette.accent};")
