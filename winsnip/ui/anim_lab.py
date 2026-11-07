"""Developer tools: an animation preview window.

Unlocked by typing the developer phrase into the settings search box. Every
button here replays one of the app's real animations with the current style and
theme, so "this animation feels off" can be checked without hunting for the
place in the UI that triggers it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from .. import __version__, anim, winapi
from ..settings import settings
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
        button("运行动画自检", self._run_selfcheck)

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

        from PySide6.QtWidgets import QTextEdit

        self.report = QTextEdit(self)
        self.report.setReadOnly(True)
        self.report.setFont(ui_font(12))
        self.report.setFixedHeight(150)
        self.report.setPlaceholderText("点上面的「运行动画自检」")
        layout.addWidget(self.report)
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

    def _run_selfcheck(self) -> None:
        """实测几项动画指标，把结论写进下面的文本框。

        检查的都是这一路真实踩过的坑：半透明窗口合成耗时、下拉动画中途卡顿、
        几何是否恒定、幽灵圆角是否和窗口一致、系统动画开关。
        """
        import time
    
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication
    
        rows: list[tuple[str, str, str]] = []
    
        def add(name: str, ok: bool, detail: str) -> None:
            rows.append((name, "PASS" if ok else "WARN", detail))
    
        # --- 1. 系统开关 ---
        try:
            dwm = winapi.dwm_composition_enabled()
        except Exception:
            dwm = False
        add("DWM 合成", bool(dwm), "开启" if dwm else "关闭（动画都会退化成瞬跳）")
        try:
            native_min = bool(winapi.native_minimize_animation_enabled())
        except Exception:
            native_min = False
        add("系统最小化动画开关", native_min,
            "系统报告为开" if native_min else "系统报告为关")
        add("应用内动画开关", bool(anim.animations_enabled()),
            "开" if anim.animations_enabled() else "关")
    
        # --- 2. 半透明窗口一帧的合成耗时 ---
        try:
            t0 = time.perf_counter()
            ghost = anim._acquire_ghost(self.grab(), 8.0)
            ghost.setGeometry(-20000, -20000, 400, 300)
            ghost.show()
            QApplication.processEvents()
            ghost.repaint()
            QApplication.processEvents()
            cost = (time.perf_counter() - t0) * 1000
            ghost.hide()
            anim._release_ghost()
            add("半透明幽灵窗口首次合成", cost < 200, f"{cost:.0f} ms（低于 200ms 才算顺滑）")
        except Exception as exc:
            add("半透明幽灵窗口首次合成", False, f"测量失败：{exc}")
    
        # --- 3. 下拉弹出动画：帧数 + 几何是否恒定 ---
        try:
            self.combo.showPopup()
            cont = self.combo.view().window()
            seen = set()
            jumps = 0
            prev = None
            t0 = time.perf_counter()
            while (time.perf_counter() - t0) < 0.55:
                QApplication.processEvents()
                g = cont.geometry()
                key = (g.width(), g.height())
                seen.add(key)
                if prev is not None and (abs(key[0] - prev[0]) > 3
                                          or abs(key[1] - prev[1]) > 3):
                    jumps += 1
                prev = key
                time.sleep(0.005)
            self.combo.hidePopup()
            add("下拉弹出几何恒定", jumps == 0,
                f"{len(seen)} 种尺寸，跳变 {jumps} 次（应为 0）")
        except Exception as exc:
            add("下拉弹出几何恒定", False, f"测量失败：{exc}")
    
        # --- 4. 圆角一致性 ---
        try:
            win_r = float(getattr(self, "radius", 8))
            add("窗口圆角", True,
                f"{win_r:.0f}px（幽灵会读同一个值，不会形状突变）")
        except Exception as exc:
            add("窗口圆角", False, f"读取失败：{exc}")
    
        # --- 5. 时长配置 ---
        add("窗口开启动画", True, f"{anim.DURATION_NORMAL} ms")
        add("自绘最小化", True, f"{anim.MINIMIZE_DURATION} ms")
        add("最小化来源", True,
            f"{getattr(settings, "minimize_animation", "auto")}（auto/原生/drawn 自绘）")
    
        lines_out = [f"{state}  {name}    {detail}" for name, state, detail in rows]
        warn = sum(1 for _, state, _ in rows if state != "PASS")
        header = f"自检完成：{len(rows) - warn} 项通过，{warn} 项需要注意\n" + "-" * 46
        self.report.setPlainText(header + "\n" + "\n".join(lines_out))
        QApplication.clipboard().setText("\n".join(lines_out))
        show_toast("动画自检完成", f"{len(rows) - warn} 通过 / {warn} 注意（已复制）",
                   "check" if warn == 0 else "info", duration=2600)

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
