"""``--selftest-minimize``: report what the minimize animation will actually do.

Answers "I don't see any animation" without guessing: it prints the machine's
animation capabilities, then really minimizes a window and reports which path ran
(native DWM animation vs the self-drawn fallback), plus how long the call took.

The path is decided by looking for the snapshot ghost right after the call: the
fallback creates it synchronously, the native path never does.
"""

from __future__ import annotations

import time

from PySide6.QtWidgets import QApplication

from .. import anim, winapi
from ..settings import settings
from .main_window import MainWindow


def _pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def run_minimize_selftest(app: QApplication) -> int:
    print("=" * 70)
    print("最小化动画自检")
    print("=" * 70)

    caps = winapi.animation_capabilities()
    print(f"  DWM 合成                     : {'开' if caps['dwm_composition'] else '关'}")
    print(f"  在 Windows 中显示动画         : {'开' if caps['client_area_animations'] else '关'}")
    print(f"  最小化/最大化时动画显示窗口    : {'开' if caps['minimize_animation'] else '关'}")
    print(f"  设置里的界面动画              : {'开' if settings.animations else '关'}")
    print()

    window = MainWindow()
    window.show()
    _pump(app, 1.2)
    print(f"  窗口 {window.width()}x{window.height()} @({window.x()},{window.y()})")

    started = time.perf_counter()
    window.minimize_animated()
    call_ms = (time.perf_counter() - started) * 1000
    # 关键：立刻查浮层。回退路径是同步创建快照的，原生路径永远不会有浮层。
    ghost_at_call = anim._minimize_ghost_count()

    _pump(app, 0.9)
    ghost_after = anim._minimize_ghost_count()
    minimized = window.isMinimized()

    print()
    print(f"  minimize_animated() 调用耗时  : {call_ms:.0f} ms")
    print(f"  调用瞬间的自绘浮层数          : {ghost_at_call}")
    print(f"  0.9 秒后的自绘浮层数          : {ghost_after}")
    print(f"  窗口已最小化                  : {minimized}")
    print()

    used_native = ghost_at_call == 0
    print(f"  => 实际走的路径               : "
          f"{'原生（由 DWM 播动画）' if used_native else '自绘快照回退'}")
    if used_native:
        print("     系统有播 Windows 自己的最小化动效。肉眼看不到时通常是：")
        print("       · 机器满载，合成被拖慢（任务管理器看 CPU/内存）")
        print("       · 虚拟显示适配器对 DWM 动画支持不完整")
    else:
        print("     系统关闭了「最小化/最大化时动画显示窗口」，所以由程序自己画。")
        print("     开启方法：Win+R -> SystemPropertiesPerformance -> 视觉效果 ->")
        print("     勾选「最小化/最大化时动画显示窗口」。")
    print()

    window.showNormal()
    _pump(app, 0.4)
    window._quitting = True
    window.close()
    print("=" * 70)
    return 0
