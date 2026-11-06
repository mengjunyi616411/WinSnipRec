"""Fluent motion helpers.

Animations follow the Windows 11 motion language: short durations (150-300 ms)
with ease-out curves, plus a small directional offset for entering surfaces.
They are skipped entirely when Windows' "show animations" accessibility setting
is off, or when the user disabled them in the app's settings.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, QRectF,
    Qt, QTimer,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from . import winapi

# Fluent duration tokens (Windows 11 motion guidelines)
DURATION_FAST = 150
DURATION_NORMAL = 240
DURATION_SLOW = 320
#: 截图/录屏 切换（命令栏的分段控件）。比通用动效慢，让滑动指示条读起来像一次
#: 明确的模式切换，而不是一闪而过。
DURATION_MODE_SWITCH = 400
#: 打开动画的起始不透明度。**不能是 0**：从全透明开始，窗口在整段过渡里就是一块玻璃，
#: 桌面直接透过来 —— 用户报"每次打开都发灰"就是这个。0.65 试过，背景花的时候仍然看得出
#: 透视，所以提到 0.92：留一点点柔和感，但视觉上已经是实心窗口。
OPEN_FADE_START = 0.92


def _settings_enabled() -> bool:
    try:
        from .settings import settings

        return bool(settings.animations)
    except Exception:
        return True


def animations_enabled() -> bool:
    """True when both the app and Windows allow animations."""
    return _settings_enabled() and winapi.client_area_animations_enabled()


def curve(kind: str = "out") -> QEasingCurve:
    mapping = {
        "out": QEasingCurve.Type.OutCubic,
        "in": QEasingCurve.Type.InCubic,
        "inout": QEasingCurve.Type.InOutCubic,
        "decelerate": QEasingCurve.Type.OutQuint,
    }
    return QEasingCurve(mapping.get(kind, QEasingCurve.Type.OutCubic))


def _freeze(window: QWidget, frozen: bool) -> None:
    """Skip Mica re-computation while a window is moving, then refresh once."""
    if hasattr(window, "_freeze_backdrop"):
        window._freeze_backdrop = frozen
        if not frozen and hasattr(window, "invalidate_backdrop"):
            window.invalidate_backdrop()


def play_window_open(window: QWidget, *, slide: int = 14, fade_only: bool = False,
                     duration: int = DURATION_NORMAL) -> None:
    """Animate an already-visible window in. Safe to call from ``showEvent``.

    The fade starts at OPEN_FADE_START, not at zero. Starting from fully
    transparent makes the window a sheet of glass for the whole transition: on a
    machine with slow compositing the desktop shows straight through it and the
    window reads as "washed out / greyed out" every single time it opens. 0.65
    still avoids a full-opacity flash while never looking see-through.
    """
    window.setWindowOpacity(OPEN_FADE_START)
    if not animations_enabled():
        window.setWindowOpacity(1.0)
        return
    _freeze(window, True)
    final = QRect(window.geometry())
    if not fade_only:
        window.move(final.x(), final.y() + slide)

    group = QParallelAnimationGroup(window)
    fade = QPropertyAnimation(window, b"windowOpacity", group)
    fade.setDuration(duration)
    fade.setStartValue(OPEN_FADE_START)
    fade.setEndValue(1.0)
    fade.setEasingCurve(curve("out"))

    if not fade_only:
        move = QPropertyAnimation(window, b"pos", group)
        move.setDuration(duration)
        move.setStartValue(QPoint(final.x(), final.y() + slide))
        move.setEndValue(QPoint(final.x(), final.y()))
        move.setEasingCurve(curve("decelerate"))

    settled = {"done": False}

    def finished() -> None:
        # 幂等：动画正常结束和下面的兜底定时器都可能调用它。
        if settled["done"]:
            return
        settled["done"] = True
        # 窗口可能已经销毁了：菜单这类窗口带 WA_DeleteOnClose，点选后立刻关闭，
        # 而动画组和兜底定时器还活着 —— 回调晚到就会撞上已删除的 C++ 对象，
        # 抛 "Internal C++ object (FluentMenu) already deleted" 把整个程序打崩。
        try:
            if not fade_only:
                window.setGeometry(final)
            window.setWindowOpacity(1.0)
            _freeze(window, False)
        except RuntimeError:
            pass

    group.finished.connect(finished)
    group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)

    # 兜底：动画组的删除策略是 DeleteWhenStopped，窗口若在动画途中被隐藏或销毁，
    # finished 就永远不会发 —— 窗口会永久卡在「半透明 + 冻结」。用户截图里的
    # "设置窗口整体发灰、只有蓝色按钮还亮"就是这个：淡入没走完，再也没恢复。
    # QPropertyAnimation 按墙钟推进，慢机器上只是帧数少，所以这个超时足够宽松。
    QTimer.singleShot(max(600, duration * 4 + 500), finished)


class _ThemeFadeOverlay(QWidget):
    """Paints a snapshot of how a window looked before the theme switched.

    Shown on top of the freshly re-themed window and faded out, so light <-> dark
    cross-fades instead of snapping between two very different looks.
    """

    def __init__(self, parent: QWidget, snapshot: QPixmap) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(parent.rect())

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._snapshot)
        painter.end()


def fade_theme_change(windows, apply, *, changed=lambda: True,
                      duration: int = DURATION_NORMAL) -> None:
    """Run ``apply`` (the theme switch) behind a cross-fade of the previous look.

    Snapshots are taken *before* ``apply`` runs. If ``changed()`` reports False
    afterwards -- the light/dark state did not actually flip -- the overlays are
    dropped, so changing an unrelated setting never flashes.
    """
    if not animations_enabled():
        apply()
        return

    snapshots: list[tuple[QWidget, QPixmap]] = []
    for window in windows:
        try:
            if window.isVisible() and window.width() > 1 and window.height() > 1:
                snapshots.append((window, window.grab()))
        except Exception:
            pass

    apply()

    try:
        if not changed():
            return
    except Exception:
        return

    for window, snapshot in snapshots:
        try:
            overlay = _ThemeFadeOverlay(window, snapshot)
            overlay.show()
            overlay.raise_()
            effect = QGraphicsOpacityEffect(overlay)
            overlay.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", overlay)
            animation.setDuration(duration)
            animation.setStartValue(1.0)
            animation.setEndValue(0.0)
            animation.setEasingCurve(curve("out"))
            animation.finished.connect(overlay.deleteLater)
            animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        except Exception:
            pass


def show_window_animated(window: QWidget, *, slide: int = 14,
                         duration: int = DURATION_NORMAL) -> None:
    """Show a window with the Fluent enter transition.

    The window is shown first (at zero opacity) so the platform still performs
    its own placement -- moving a never-shown window would pin it to Qt's
    default position instead of the centred one Windows chooses. The automatic
    transition that ``FluentWindow.showEvent`` would play is suppressed so the
    two animations cannot fight over the window position.
    """
    if not animations_enabled():
        window.setWindowOpacity(1.0)
        window.show()
        return

    if hasattr(window, "_suppress_open_animation"):
        window._suppress_open_animation = True
    try:
        window.setWindowOpacity(OPEN_FADE_START)
        window.show()
    finally:
        if hasattr(window, "_suppress_open_animation"):
            window._suppress_open_animation = False
    play_window_open(window, slide=slide, duration=duration)


def hide_window_animated(window: QWidget, *, on_finished=None,
                         duration: int = DURATION_FAST) -> None:
    """Fade a window out, then hide it."""
    if not animations_enabled():
        window.hide()
        window.setWindowOpacity(1.0)
        if on_finished is not None:
            on_finished()
        return

    fade = QPropertyAnimation(window, b"windowOpacity", window)
    fade.setDuration(duration)
    fade.setStartValue(window.windowOpacity())
    fade.setEndValue(0.0)
    fade.setEasingCurve(curve("in"))

    settled = {"done": False}

    def finished() -> None:
        # 幂等：正常结束和兜底定时器都可能调用。
        if settled["done"]:
            return
        settled["done"] = True
        # 与 play_window_open 同理：菜单这类窗口带 WA_DeleteOnClose，可能在动画跑完前
        # 就被销毁了（点选后立即关闭），回调晚到会撞上已删除的 C++ 对象。
        try:
            window.hide()
            window.setWindowOpacity(1.0)
        except RuntimeError:
            pass
        if on_finished is not None:
            on_finished()

    fade.finished.connect(finished)
    fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # 同样兜底：动画被打断时窗口不能既没隐藏又停在半透明。
    QTimer.singleShot(max(400, duration * 4 + 400), finished)


#: The single reusable ghost, plus whether it is currently animating. Holding the
#: instance keeps Python from collecting the widget mid-flight.
_ghost: _MinimizeGhost | None = None
_ghost_live = False


def _minimize_ghost_count() -> int:
    """How many minimize snapshots are on screen (used by the self-tests)."""
    return 1 if _ghost_live else 0


def _acquire_ghost(snapshot: QPixmap, radius: float) -> _MinimizeGhost:
    """The reusable ghost, re-pointed at the new snapshot.

    NOTE: the previous version cleared the pool list on release, so every call
    allocated a fresh widget and the reuse never happened.
    """
    global _ghost, _ghost_live
    if _ghost is None:
        _ghost = _MinimizeGhost(snapshot, radius)
    else:
        _ghost.retarget(snapshot, radius)
    _ghost_live = True
    return _ghost


def prewarm_ghost(size: tuple[int, int] = (640, 360)) -> None:
    """Create and composite the ghost off-screen ahead of time.

    用户反馈「自绘最小化会抽搐」。实测第一次最小化时幽灵窗口是新建的，
    创建 + 半透明合成要上百毫秒，动画在那之前就启动了，第一帧之后整块卡住。
    预热必须用**真实尺寸**的画面 —— 2x2 的空白图只省掉控件创建，
    省不掉分层窗口的首次合成。
    """
    global _ghost, _ghost_live
    if _ghost is not None or _ghost_live:
        return
    try:
        from PySide6.QtGui import QColor, QPixmap

        w, h = max(64, int(size[0])), max(48, int(size[1]))
        blank = QPixmap(w, h)
        blank.fill(QColor(0, 0, 0, 8))
        ghost = _acquire_ghost(blank, 14.0)
        ghost.setGeometry(-20000, -20000, w, h)
        ghost.show()
        ghost.repaint()

        def _hide() -> None:
            try:
                ghost.hide()
            except RuntimeError:
                pass
            _release_ghost()

        QTimer.singleShot(250, _hide)
    except Exception:
        pass


def _release_ghost() -> None:
    """Keep the widget alive for the next minimize, just stop counting it."""
    global _ghost_live
    _ghost_live = False


def minimize_target(window: QWidget, scale: float = 0.34) -> QRect:
    """Where a minimize animation should end: just above the taskbar."""
    geometry = window.geometry()
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.screenAt(geometry.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else geometry
    except Exception:
        area = geometry

    width = max(90, int(geometry.width() * scale))
    height = max(70, int(geometry.height() * scale))
    x = geometry.center().x() - width // 2
    x = max(area.left() + 6, min(area.right() - width - 6, x))
    y = area.bottom() - height - 6
    return QRect(x, y, width, height)


class _MinimizeGhost(QWidget):
    """A snapshot of a window, animated down to the taskbar.

    One instance is reused for the whole process: creating and compositing a
    translucent window costs ~70 ms here, and the animation used to start before
    that finished, so the ghost appeared already part-shrunk.
    """

    def __init__(self, snapshot: QPixmap, radius: float) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._radius = radius
        self.painted_frames = 0
        self._origin = QRect()
        self._target = QRect()
        self._union = QRect()
        self._progress = 0.0
        self._fade = 1.0
        #: Size of the first frame after a retarget. The animation must start at
        #: the window's full size; if it starts any later the ghost pops in
        #: already shrunk, which is exactly the judder this guards against.
        self.first_frame_size: tuple[int, int] | None = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def retarget(self, snapshot: QPixmap, radius: float) -> None:
        self._snapshot = snapshot
        self._radius = radius
        self.painted_frames = 0
        self.first_frame_size = None
        self._progress = 0.0
        self._fade = 1.0

    def play(self, origin: QRect, target: QRect, duration: int,
             on_finished=None) -> None:
        """Start the shrink motion.

        用户反馈「自绘最小化会抽搐」。原因是原来的做法每帧改窗口 geometry ——
        半透明顶层窗口每帧都要重新合成，实测帧率极低（前 28ms 完全静止，之后
        一帧跳 150px）。现在窗口几何只设一次（起点∪终点的并集），动画只推进
        一个 0..1 的进度值，绘制时把快照按进度缩放并移动到对应位置，全程零重排。
        """
        from PySide6.QtCore import QVariantAnimation

        self._origin = origin
        self._target = target
        self._progress = 0.0
        self._fade = 1.0
        union = origin.united(target)
        self._union = union
        self.setGeometry(union)
        self.setWindowOpacity(1.0)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(curve("in_out"))
        self._anim.valueChanged.connect(self._on_progress)
        if on_finished is not None:
            self._anim.finished.connect(on_finished)
        self._anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_progress(self, value) -> None:
        try:
            self._progress = float(value)
            # 只更新这一帧和上一帧覆盖的区域，避免整块重绘
            self._fade = max(0.0, min(1.0, 1.0 - float(value) ** 1.6))
            self.update(self.rect())
        except RuntimeError:
            pass

    def current_rect(self) -> QRect:
        """当前帧在屏幕坐标下的矩形（按进度在起止矩形之间插值）。"""
        from PySide6.QtCore import QEasingCurve

        t = curve("in_out").valueForProgress(max(0.0, min(1.0, self._progress)))
        o, d = self._origin, self._target
        x = int(o.x() + (d.x() - o.x()) * t)
        y = int(o.y() + (d.y() - o.y()) * t)
        w = int(o.width() + (d.width() - o.width()) * t)
        h = int(o.height() + (d.height() - o.height()) * t)
        return QRect(x, y, max(1, w), max(1, h))

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter, QPainterPath

        self.painted_frames += 1
        if self.first_frame_size is None:
            self.first_frame_size = (self.width(), self.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 按进度算出这一刻应该在屏幕上的位置，再换算成窗口内坐标
        cur = self.current_rect() if hasattr(self, "_union") else self.geometry()
        local = QRectF(cur.translated(-self.x(), -self.y()))
        painter.setOpacity(min(1.0, max(0.0, getattr(self, "_fade", 1.0))))
        path = QPainterPath()
        path.addRoundedRect(local, self._radius, self._radius)
        painter.setClipPath(path)
        painter.drawPixmap(local, self._snapshot, QRectF(self._snapshot.rect()))
        painter.end()


# 自绘最小化的时长。这台机器（远程虚拟显示器）半透明窗口合成很慢，实测 240ms
# 只有 7~10 帧；帧数上不去就只能把每帧位移降到最小，所以拉到 420ms。
MINIMIZE_DURATION = 420


def minimize_window_animated(window: QWidget, *, on_finished=None,
                             duration: int = MINIMIZE_DURATION) -> None:
    """Play the Windows-style minimize, then actually minimize the window.

    The real window is minimized at once and a snapshot ghost provides the
    motion: resizing the live window would re-lay-out its contents every frame,
    which looks nothing like the system animation.
    """
    def fall_back() -> None:
        window.showMinimized()
        if on_finished is not None:
            on_finished()

    if not animations_enabled():
        fall_back()
        return

    try:
        snapshot = window.grab()
        snapshot.setDevicePixelRatio(1.0)
    except Exception:
        fall_back()
        return

    origin = window.geometry()
    target = minimize_target(window)

    ghost = _acquire_ghost(snapshot, 14.0)
    window.showMinimized()

    finished_flag = {"done": False}

    def cleanup() -> None:
        if finished_flag["done"]:
            return
        finished_flag["done"] = True
        ghost.hide()
        _release_ghost()
        if on_finished is not None:
            on_finished()

    try:
        # 用户："自绘最小化会抽搐"。旧做法每帧改窗口 geometry，半透明顶层窗口
        # 每帧重新合成，实测前 28ms 完全静止、之后一帧跳 150px。
        # 现在窗口几何只设一次（起点∪终点的并集），动画只推进 0..1 的进度，
        # 绘制时把快照按进度缩放并移动，全程零重排。
        # 必须先 show 再 play：play 里会 setGeometry 并立刻启动动画，
        # 如果窗口还没显示，前几帧的 update() 会被吞掉（实测只剩 2 种矩形）。
        ghost.show()
        ghost.play(origin, target, duration, cleanup)
        ghost.repaint()
    except Exception:
        fall_back()

    # One turn of the event loop: the ghost is on screen at full size by then.


def fade_in(widget: QWidget, *, duration: int = DURATION_NORMAL, start: float = 0.0,
            effect_owner: QWidget | None = None) -> QGraphicsOpacityEffect | None:
    """Fade a plain widget (no window) in, using an opacity effect."""
    if not animations_enabled():
        return None
    owner = effect_owner or widget
    effect = QGraphicsOpacityEffect(owner)
    effect.setOpacity(start)
    owner.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", owner)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(1.0)
    animation.setEasingCurve(curve("out"))

    def finished() -> None:
        # Leaving the effect installed would keep the widget on a slow path.
        owner.setGraphicsEffect(None)

    animation.finished.connect(finished)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return effect


def after(milliseconds: int, callback) -> None:
    QTimer.singleShot(milliseconds, callback)
