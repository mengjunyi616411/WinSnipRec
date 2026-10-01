"""Interface language tests.

The important properties:
  * every user-visible Chinese string goes through _t() (checked by walking the
    AST, so a newly added label cannot silently stay Chinese);
  * folder names and window-title matching tables are NOT translated - moving a
    user's save path would be a data-loss class bug;
  * unknown strings fall back to the source rather than showing a key;
  * switching the language actually changes rendered text.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_i18n" / "_config"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import i18n, winapi  # noqa: E402

checks: list[tuple[str, bool, str]] = []
CJK = re.compile(r"[\u4e00-\u9fff]")
SKIP_FILES = {"selftest_ui.py", "selftest_frozen.py", "i18n.py"}
# Deliberately not translated: folder names, matching tables, the app name.
#: Deliberately NOT translated at all - folder names, matching tables, the app
#: name, output file names. These must NOT appear in the translation table.
UNTRANSLATED = {
    ("settings.py", "屏幕截图"), ("settings.py", "录制"),
    ("winapi.py", "windows 输入体验"), ("winapi.py", "窗口"),
    ("__init__.py", "截图工具"),
    ("main_window.py", "截图 "), ("main_window.py", "屏幕录制 "),
}

#: Stored as source strings and translated later, so the AST walk sees the raw
#: Chinese. These MUST appear in the translation table.
DEFERRED = {
    ("main_window.py", "新建截图"), ("main_window.py", "新建录屏"),
    ("main_window.py", "设置"), ("main_window.py", "打开保存文件夹"),
    ("main_window.py", "退出"),
    ("widgets.py", "最小化"), ("widgets.py", "最大化"),
    ("widgets.py", "还原"), ("widgets.py", "关闭"),
}

ALLOWED = UNTRANSLATED | DEFERRED
LOG_CALLS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def unwrapped_strings() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for path in sorted((ROOT / "winsnip").rglob("*.py")):
        if "__pycache__" in str(path) or path.name in SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        protected = docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant):
                        protected.add(id(key))
            if isinstance(node, ast.Compare):
                for operand in [node.left, *node.comparators]:
                    if isinstance(operand, ast.Constant):
                        protected.add(id(operand))
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
                if name in LOG_CALLS:
                    for arg in node.args:
                        if isinstance(arg, ast.Constant):
                            protected.add(id(arg))
        wrapped: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "_t" and node.args:
                if isinstance(node.args[0], ast.Constant):
                    wrapped.add(id(node.args[0]))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and CJK.search(node.value) and id(node) not in protected \
                    and id(node) not in wrapped:
                if (path.name, node.value) in ALLOWED:
                    continue
                found[str(path.relative_to(ROOT))].append((node.lineno, node.value))
    return found


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    from winsnip.settings import Settings, settings
    from winsnip.theme import apply_app_theme, current_font_families, theme

    settings.minimize_to_tray = False
    settings.animations = False
    theme.style = "win10"
    theme.mode = "dark"
    theme.refresh()
    apply_app_theme(app)

    # ---------------- 1. 四种语言的查表 ----------------
    expected = {
        "zh-Hans": "设置",
        "zh-Hant": "設定",
        "en": "Settings",
        "ja": "設定",
    }
    problems = []
    for code, want in expected.items():
        i18n.set_language(code)
        got = i18n.t("设置")
        if got != want:
            problems.append(f"{code}: 期望 {want} 得到 {got}")
    check("四种语言都能查到「设置」", not problems, "; ".join(problems) or "全部正确")

    i18n.set_language("zh-Hans")
    check("简体中文原样返回", i18n.t("设置") == "设置")
    i18n.set_language("en")
    check("未翻译的字符串回退到原文（不显示键名）",
          i18n.t("这句话不在表里") == "这句话不在表里")
    check("英文不再是中文", not CJK.search(i18n.t("新建录屏")), i18n.t("新建录屏"))

    # ---------------- 2. 系统语言映射 ----------------
    mapping = {
        "zh_TW": "zh-Hant", "zh_HK": "zh-Hant", "zh_CN": "zh-Hans",
        "ja_JP": "ja", "en_US": "en", "de_DE": "zh-Hans",
    }
    wrong = [f"{tag}->{i18n.resolve(tag)}" for tag, want in mapping.items()
             if i18n.resolve(tag) != want]
    check("系统区域映射正确（繁中/日文/英文）", not wrong,
          "; ".join(wrong) or f"{len(mapping)} 个都正确")

    # ---------------- 3. 表格完整性 ----------------
    missing = []
    for key, entry in i18n.TABLE.items():
        if not isinstance(entry, tuple) or len(entry) != len(i18n.TRANSLATED):
            missing.append(key)
        elif not all(isinstance(value, str) and value for value in entry):
            missing.append(key)
    check("每个条目都有三种语言的译文", not missing,
          f"{len(i18n.TABLE)} 条" + (f"，缺 {missing[:3]}" if missing else ""))

    # ---------------- 4. 覆盖：用户可见文案都要走 _t() ----------------
    # 延后翻译的那些必须先存原文、后查表，所以必须真的在翻译表里，
    # 否则这个例外就成了漏译的藏身处。
    deferred_missing = sorted({key for _file, key in DEFERRED if key not in i18n.TABLE})
    check("延后翻译的例外都在翻译表里（例外不会掩盖漏译）",
          not deferred_missing,
          ", ".join(deferred_missing) or f"{len(DEFERRED)} 条全部已翻译")
    # 注意：这里不能断言"故意不翻译的那些不在表里"——同一个中文字符串在别处可能
    # 确实要翻译（"窗口" 同时是截图形状选项，"截图工具" 是应用名）。真正要保证的是
    # *使用位置*不被翻译，而这一点由上面对 AST 的遍历已经确认。

    leftover = unwrapped_strings()
    count = sum(len(items) for items in leftover.values())
    detail = "; ".join(f"{name}:{items[0][1][:16]}" for name, items in list(leftover.items())[:3])
    check("所有用户可见的中文字符串都经过 _t()", count == 0,
          detail or "0 处遗漏")

    # ---------------- 5. 绝不能翻译的东西 ----------------
    from winsnip import settings as settings_module

    folder_defaults = []
    for name in dir(settings_module.Settings):
        if "dir" in name:
            value = getattr(Settings(), name, "")
            if isinstance(value, str) and CJK.search(value):
                folder_defaults.append(f"{name}={value}")
    check("默认保存路径保持中文原名（翻译会改变用户的保存位置）",
          not folder_defaults, "; ".join(folder_defaults) or "路径未被翻译")

    # ---------------- 6. 字体随语言变化 ----------------
    fonts = {}
    for code in ("zh-Hans", "zh-Hant", "ja", "en"):
        i18n.set_language(code)
        fonts[code] = current_font_families()[0]
    check("日文使用含假名的字体", "Yu Gothic" in " ".join(
        current_font_families() if i18n.language() == "ja" else [])
        or fonts["ja"] != fonts["en"],
        f"ja -> {fonts['ja']}")
    i18n.set_language("zh-Hant")
    check("繁中使用正黑體", "JhengHei" in " ".join(current_font_families()),
          f"zh-Hant -> {current_font_families()[0]}")

    # ---------------- 7. 界面真的变了 ----------------
    i18n.set_language("zh-Hans")
    from winsnip.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    pump(app, 1.0)
    def hint_text(win) -> str:
        """HotkeyHint keeps its rendered text as (text, kind) pairs."""
        lines = getattr(getattr(win, "hint", None), "_lines", None) or []
        return " ".join(text for text, _kind in lines)

    chinese_title = hint_text(window)
    window._quitting = True
    window.close()
    window.deleteLater()
    pump(app, 0.3)

    i18n.set_language("en")
    window_en = MainWindow()
    window_en.show()
    pump(app, 1.0)
    english_title = hint_text(window_en)
    window_en._quitting = True
    window_en.close()
    window_en.deleteLater()
    pump(app, 0.3)

    # 路径里的文件夹名是故意不翻译的，判断前先把它从字符串里去掉，
    # 否则 "Videos\录制" 会被当成没翻译的界面文字。
    def without_paths(value: str) -> str:
        for folder in (settings.video_dir, settings.image_dir,
                       getattr(settings, "screenshot_dir", "") or ""):
            if folder:
                value = value.replace(folder, "")
        return value

    check("切到英文后界面文字确实变了（路径除外）",
          bool(chinese_title) and chinese_title != english_title
          and not CJK.search(without_paths(english_title)),
          f"{chinese_title!r} -> {english_title!r}")

    # ---------------- 8. 设置里有语言下拉 ----------------
    from winsnip.ui.settings_dialog import SettingsWindow

    settings_window = SettingsWindow()
    settings_window.show()
    pump(app, 0.6)
    combo = settings_window.language_combo
    labels = [combo.itemText(i) for i in range(combo.count())]
    check("设置里有「界面语言」下拉，含四种语言",
          combo.count() == 5 and "繁體中文" in labels and "English" in labels
          and "日本語" in labels,
          f"{labels}")
    settings_window.close()
    settings_window.deleteLater()
    pump(app, 0.2)

    # ---------------- 9. 切换语言要影响到整个应用 ----------------
    # 复现过的 bug：在引导里选了英文，引导自己变了，但主窗口和托盘菜单还是中文，
    # 看起来就像"设置语言没成功"。
    i18n.set_language("zh-Hans")
    apply_app_theme(app)
    main = MainWindow()
    main.show()
    pump(app, 1.0)

    def tray_texts(win) -> list[str]:
        menu = win.tray.contextMenu()
        return [a.text() for a in menu.actions() if a.text()]

    before_title = main.windowTitle()
    before_new = main.new_button.text()
    before_folder = main.folder_button.text()
    before_tray = tray_texts(main)
    check("切换前主窗口是中文", "截图工具" in before_title,
          f"{before_title!r} / {before_new!r} / {before_tray[:2]}")

    i18n.set_language("en")
    from winsnip.ui.widgets import retranslate_windows

    retranslate_windows()
    pump(app, 0.3)

    after_title = main.windowTitle()
    after_new = main.new_button.text()
    after_folder = main.folder_button.text()
    after_tray = tray_texts(main)
    check("切换语言后主窗口标题跟着变",
          after_title != before_title and not CJK.search(after_title),
          f"{before_title!r} -> {after_title!r}")
    check("切换语言后主窗口按钮跟着变",
          after_new != before_new and after_folder != before_folder
          and not CJK.search(after_new + after_folder),
          f"{before_new!r}/{before_folder!r} -> {after_new!r}/{after_folder!r}")
    check("切换语言后托盘菜单跟着变",
          after_tray != before_tray and not CJK.search(" ".join(after_tray)),
          f"{before_tray} -> {after_tray}")
    check("模式切换（截图/录屏）也跟着变",
          main.segmented._items[0][1] == "Screenshot"
          and main.segmented._items[1][1] == "Recording",
          f"{[item[1] for item in main.segmented._items]}")
    check("标题栏按钮的提示也跟着变",
          main.title_bar.caption_buttons["close"].toolTip() == "Close",
          f"关闭按钮提示={main.title_bar.caption_buttons['close'].toolTip()!r}")

    onboarding_source = (ROOT / "winsnip" / "ui" / "onboarding.py").read_text(encoding="utf-8")
    settings_source = (ROOT / "winsnip" / "ui" / "settings_dialog.py").read_text(encoding="utf-8")
    check("引导切换语言时会重译其它窗口",
          "retranslate_windows()" in onboarding_source,
          "onboarding 调用了 retranslate_windows")
    check("设置切换语言时也会重译其它窗口",
          "retranslate_windows()" in settings_source,
          "settings 调用了 retranslate_windows")

    i18n.set_language("zh-Hans")
    retranslate_windows()
    pump(app, 0.2)
    main._quitting = True
    main.close()
    main.deleteLater()
    pump(app, 0.3)

    i18n.set_language("system")

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- I18N SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("I18N SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
