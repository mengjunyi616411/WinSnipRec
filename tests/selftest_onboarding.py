"""First-run guide tests.

The guide writes straight into the user's settings, so the important properties
are that every choice actually persists, that it only appears once, and that the
language step rebuilds the text instead of leaving mixed languages behind.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_onboarding" / "_config"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import i18n, winapi  # noqa: E402
from winsnip.settings import Settings, settings  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def real_click(app: QApplication, widget) -> None:
    """Deliver a genuine press+release, the way a mouse would.

    Calling select() directly bypasses QPushButton.clicked - and that is exactly
    where the index was being lost.
    """
    centre = widget.rect().center()
    for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        event = QMouseEvent(kind, centre, widget.mapToGlobal(centre),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        app.sendEvent(widget, event)


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    settings.minimize_to_tray = False
    settings.animations = False
    # This suite persists settings into its own config dir, so a previous run
    # that ended on the English step would otherwise start in English.
    settings.language = "system"
    i18n.set_language("system")

    from winsnip.theme import apply_app_theme, theme
    from winsnip.ui import onboarding
    from winsnip.ui.onboarding import OnboardingWindow

    theme.style = "win11"
    theme.mode = "dark"
    theme.refresh()
    apply_app_theme(app)

    # ---------------- 1. 结构 ----------------
    window = OnboardingWindow()
    window.show()
    pump(app, 0.8)

    check("默认还没有引导过", Settings().onboarded is False,
          f"onboarded={Settings().onboarded}")
    check("引导共 7 步（欢迎 + 5 项设置 + 完成）", window.total_steps == 7,
          f"total_steps={window.total_steps}")

    titles = []
    for index in range(window.total_steps):
        window._go_to(index)
        pump(app, 0.05)
        if index == 0:
            titles.append("欢迎")
        elif index >= len(window._pages):
            titles.append("完成")
        else:
            titles.append(window._pages[index].heading.text())
    check("步骤顺序正确",
          titles == ["欢迎", "界面风格", "主题", "背景材质", "光效强度", "界面语言", "完成"],
          " / ".join(titles))
    check("第一页确实是欢迎页（不是直接跳到界面风格）",
          window._pages[0].findChild(type(window._pages[1].heading)) is not None
          or window._pages[0] is not window._pages[1],
          "欢迎页独立存在")

    window._go_to(0)
    pump(app, 0.1)
    check("首屏不显示「上一步」，末屏显示「完成」",
          not window.back_button.isVisible()
          and window.skip_button.isVisible()
          and window.next_button.text() == i18n.t("下一步"),
          f"back={window.back_button.isVisible()} skip={window.skip_button.isVisible()}")

    # ---------------- 2. 每一步都真的写进设置 ----------------
    original = {"style": settings.style, "theme": settings.theme,
                "reveal_strength": settings.reveal_strength,
                "language": settings.language, "backdrop": settings.backdrop}

    window._go_to(1)
    window.style_choice.select(1)          # Windows 10
    pump(app, 0.2)
    check("选界面风格会写入设置并切换主题",
          settings.style == "win10" and theme.style == "win10",
          f"settings.style={settings.style} theme.style={theme.style}")

    window._go_to(2)
    window.theme_choice.select(1)          # 浅色
    pump(app, 0.2)
    check("选主题会写入设置并生效",
          settings.theme == "light" and theme.mode == "light",
          f"settings.theme={settings.theme} theme.mode={theme.mode}")

    window._go_to(4)
    window.reveal_choice.select(2)         # 高
    pump(app, 0.2)
    check("选光效强度会写入设置",
          settings.reveal_strength == "strong",
          f"reveal_strength={settings.reveal_strength}")

    window._go_to(3)
    window.backdrop_choice.select(1)       # 经典（壁纸）
    pump(app, 0.2)
    check("选背景材质会写入设置，并说明只对新窗口生效",
          settings.backdrop == "classic"
          and i18n.t("切换背景材质后，新打开的窗口会使用它") in window._pages[3].body.text(),
          f"backdrop={settings.backdrop}")

    # ---------------- 2b. 真实鼠标点击必须选中「被点的那个」 ----------------
    # 曾经这里全错：clicked(bool) 的 bool 被当成索引，点任何按钮都选中第 0 个。
    # 语言那步因为会重建窗口，看起来"能用"，掩盖了其它四步。
    clicks = []
    for step, name, setting_key, values in (
            (1, "界面风格", "style", ["win11", "win10"]),
            (2, "主题", "theme", ["system", "light", "dark"]),
            (3, "背景材质", "backdrop", ["auto", "classic", "native"]),
            (4, "光效强度", "reveal_strength", ["weak", "normal", "strong"])):
        window._go_to(step)
        pump(app, 0.25)
        row = (window.style_choice, window.theme_choice,
               window.backdrop_choice, window.reveal_choice)[step - 1]
        real_click(app, row._buttons[1])
        pump(app, 0.35)
        clicks.append((name, row.current(), getattr(settings, setting_key), values[1]))
    bad = [f"{n}: 选中={s} 设置={a} 期望={w}" for n, s, a, w in clicks
           if s != 1 or a != w]
    check("真实点击每一步都选中被点的那个（不再总是第 0 个）", not bad,
          "; ".join(bad) or "; ".join(f"{n}→{a}" for n, _s, a, _w in clicks))

    # 语言那一步同样要用真实点击验证
    original_language = settings.language
    window._go_to(5)
    pump(app, 0.25)
    real_click(app, window.language_choice._buttons[3])   # English
    pump(app, 1.2)
    check("真实点击语言按钮会切到所选语言",
          settings.language == "en",
          f"settings.language={settings.language!r}")
    i18n.set_language("zh-Hans")
    settings.language = original_language
    rebuilt_after_click = onboarding.current_onboarding()
    if rebuilt_after_click is not None and rebuilt_after_click is not window:
        rebuilt_after_click.close()
        rebuilt_after_click.deleteLater()
    pump(app, 0.4)
    if not window.isVisible():
        window.show()
    pump(app, 0.5)

    # ---------------- 3. 切换语言会重建 ----------------
    before_window = onboarding.current_onboarding()
    window._go_to(5)
    window.language_choice.select(3)       # English
    pump(app, 1.2)
    rebuilt = onboarding.current_onboarding()
    check("切换语言后引导会重建，文字变成所选语言",
          rebuilt is not None and rebuilt is not before_window
          and rebuilt._pages[1].heading.text() == "Interface style",
          f"标题={rebuilt._pages[1].heading.text() if rebuilt else '无'}")
    check("英文界面里不再出现中文步骤名",
          rebuilt is not None and "欢迎" not in [
              rebuilt._items[i].title for i in range(len(rebuilt._items))],
          f"{[rebuilt._items[i].title for i in range(len(rebuilt._items))] if rebuilt else '无'}")

    # 切回中文，免得影响后面的断言
    i18n.set_language("zh-Hans")
    rebuilt.close()
    rebuilt.deleteLater()
    pump(app, 0.4)

    # ---------------- 4. 完成 / 跳过 记账 ----------------
    settings.onboarded = False
    window_finish = OnboardingWindow()
    window_finish.show()
    pump(app, 0.7)
    window_finish._go_to(window_finish.total_steps - 1)
    pump(app, 0.2)
    check("最后一屏按钮变成「完成」",
          window_finish.next_button.text() == i18n.t("完成"),
          f"按钮={window_finish.next_button.text()}")
    window_finish._finish()
    pump(app, 0.3)
    check("点完成会记录已经引导过", settings.onboarded is True,
          f"onboarded={settings.onboarded}")

    settings.onboarded = False
    window_skip = OnboardingWindow()
    window_skip.show()
    pump(app, 0.7)
    window_skip._on_skip()
    pump(app, 0.3)
    check("点跳过同样不会再次弹出", settings.onboarded is True,
          f"onboarded={settings.onboarded}")

    # ---------------- 5. 设置里能重新运行 ----------------
    from winsnip.ui.settings_dialog import SettingsWindow

    settings_window = SettingsWindow()
    settings_window.show()
    pump(app, 0.8)
    check("设置里有「重新运行引导」按钮",
          hasattr(settings_window, "guide_button")
          and settings_window.guide_button.text() == i18n.t("重新运行引导"),
          f"按钮={getattr(getattr(settings_window, 'guide_button', None), 'text', lambda: '无')()}")
    settings_window.close()
    settings_window.deleteLater()
    pump(app, 0.3)

    # ---------------- 6. 启动门控 ----------------
    import app as app_module

    check("启动流程里有首次运行的入口",
          hasattr(app_module, "_show_first_run_guide"),
          "存在 _show_first_run_guide")
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    check("启动时按 onboarded 判断是否弹出，且静默启动不弹",
          'getattr(settings, "onboarded", False)' in source and "if not silent and" in source,
          "已按 onboarded 与 silent 门控")

    # 还原
    for key, value in original.items():
        setattr(settings, key, value)
    settings.onboarded = False
    i18n.set_language(settings.language)
    try:
        settings.save()
    except Exception:
        pass

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- ONBOARDING SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("ONBOARDING SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
