"""Easter-egg tests.

The egg hangs off the settings search box, so this also covers the search
filter it needed (the settings window had no place to type before).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_egg" / "_config"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import i18n, winapi  # noqa: E402
from winsnip.settings import settings  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    from winsnip.theme import apply_app_theme, theme
    from winsnip.ui import easter_egg
    from winsnip.ui.easter_egg import EasterEggWindow, asset_path, show_easter_egg, triggers
    from winsnip.ui.settings_dialog import SettingsWindow

    theme.style = "win11"
    theme.mode = "dark"
    theme.refresh()
    apply_app_theme(app)
    settings.animations = False
    settings.minimize_to_tray = False
    i18n.set_language("zh-Hans")

    # ---------------- 1. 素材 ----------------
    folder = easter_egg.asset_dir(easter_egg.ASSET_DIR)
    check("彩蛋图片目录 assets/egg 能找到", folder is not None and folder.is_dir(),
          str(folder))
    check("目录里至少有 8 张图", len(easter_egg.picture_paths()) >= 8,
          f"{len(easter_egg.picture_paths())} 张")

    window = EasterEggWindow()
    window.show()
    pump(app, 0.8)
    pixmap = window.image_label.pixmap()
    check("图片能加载并缩放显示",
          pixmap is not None and not pixmap.isNull() and pixmap.width() > 100,
          f"{pixmap.width()}x{pixmap.height()}" if pixmap else "无")

    # ---------------- 2. 触发词 ----------------
    check("只有输入廉丰榕才会触发",
          triggers("廉丰榕") and triggers("xx廉丰榕xx")
          and not triggers("廉丰") and not triggers("") and not triggers("榕丰廉"),
          "廉丰榕 命中，其它不命中")
    check("问题文案正确", window.question.text() == i18n.t("你是萝莉控吗？"),
          window.question.text())

    # ---------------- 3. 选「否」会重新问 ----------------
    first_question = window.question.text()
    window._on_no()
    pump(app, 0.4)
    check("选「否」窗口不关闭，换成「再选一次？」",
          window.isVisible() and window.question.text() != first_question
          and window.question.text() == i18n.t("再选一次？"),
          f"{first_question!r} -> {window.question.text()!r}")

    # ---------------- 3b. 关闭按钮已去掉；选「是」弹出「你承认啦！」 ----------------
    egg_window = EasterEggWindow()
    egg_window.show()
    pump(app, 0.5)
    captions = {key: button.isVisible()
                for key, button in egg_window.title_bar.caption_buttons.items()}
    check("彩蛋窗口没有关闭按钮（只能靠「是」退出）",
          not any(captions.values()),
          f"可见的标题栏按钮: {[k for k, v in captions.items() if v]}")

    from winsnip.ui.easter_egg import AdmissionWindow, show_admission

    before = [w for w in app.topLevelWidgets()
              if isinstance(w, AdmissionWindow) and w.isVisible()]
    egg_window._on_yes()
    pump(app, 0.7)
    after = [w for w in app.topLevelWidgets()
             if isinstance(w, AdmissionWindow) and w.isVisible()]
    check("选「是」会弹出「你承认啦！」窗口", len(after) == len(before) + 1,
          f"弹窗数 {len(before)} -> {len(after)}")
    check("选「是」之后彩蛋关闭", not egg_window.isVisible(), "已关闭")

    if after:
        popup = after[0]
        check("弹窗文案是「你承认啦！」",
              popup.message.text() == i18n.t("你承认啦！") == "你承认啦！",
              popup.message.text())
        check("弹窗有关闭用的「好」按钮",
              popup.ok_button.text() == i18n.t("好") and not popup.title_bar.caption_buttons["close"].isVisible(),
              f"{popup.ok_button.text()!r}")
        popup.ok_button.click()
        pump(app, 0.5)
        check("点「好」后弹窗关闭", not popup.isVisible(), "已关闭")

    # ---------------- 4. 画廊跑完后重新开一个窗口给后面的搜索测试 ----------------
    window._on_yes()
    pump(app, 0.4)
    check("选「是」窗口消失", not window.isVisible() and window.answer_is_yes())

    # ---------------- 2b. 画廊：否切下一张，是退出 ----------------
    from winsnip.ui.easter_egg import picture_paths

    count = window.picture_count()
    check("素材目录里的图片全部载入", count == len(picture_paths()) and count >= 8,
          f"目录 {len(picture_paths())} 张 / 载入 {count} 张")
    check("图片都缩放到了显示尺寸内",
          window.image_label.pixmap() is not None
          and window.image_label.width() <= 300 and window.image_label.height() <= 470,
          f"{window.image_label.width()}x{window.image_label.height()}")

    start = window.current_index()
    order = []
    for _ in range(count + 2):
        window._on_no()
        pump(app, 0.12)
        order.append(window.current_index())
    expected = [(start + step) % count for step in range(1, count + 3)]
    check("选「否」逐张切换并循环回第一张", order == expected,
          f"序号 {[i + 1 for i in order]}")

    check("计数与当前张数一致",
          window.counter.text() == f"{window.current_index() + 1} / {count}",
          window.counter.text())

    # 每张图都要能显示出来（不是空白框）
    blank = []
    for index in range(count):
        window._index = index
        window._show_current()
        pump(app, 0.08)
        pixmap = window.image_label.pixmap()
        if pixmap is None or pixmap.isNull() or pixmap.width() < 50:
            blank.append(index + 1)
    check("每张图都能正常显示（没有空白框）", not blank, f"异常: {blank}" if blank else "全部正常")

    # 窗口高度跟着图片走，横图不应留一大片空白
    window._index = 0
    window._show_current()
    pump(app, 0.3)
    tall = window.height()
    window._index = 1
    window._show_current()
    pump(app, 0.3)
    wide = window.height()
    check("窗口高度跟着图片，横图不留大片空白", wide < tall - 100,
          f"竖构图 {tall}px / 横构图 {wide}px")


    # ---------------- 5. 设置里的搜索框触发 ----------------
    settings_window = SettingsWindow()
    settings_window.show()
    pump(app, 1.0)
    check("设置里有搜索框（否则中文输入法无处可输）",
          hasattr(settings_window, "search_box"), "search_box 存在")

    total_rows = len(settings_window._rows)
    settings_window.search_box.setText(i18n.t("语言"))
    pump(app, 0.4)
    visible = sum(1 for row in settings_window._rows if row.isVisible())
    check("搜索会过滤设置项", 0 < visible < total_rows,
          f"「语言」命中 {visible}/{total_rows}")

    settings_window.search_box.setText("")
    pump(app, 0.3)
    check("清空搜索恢复全部设置项",
          sum(1 for row in settings_window._rows if row.isVisible()) == total_rows,
          f"{total_rows} 行全部可见")

    settings_window.search_box.setText(easter_egg.TRIGGER)
    pump(app, 1.2)
    check("在搜索框输入廉丰榕会弹出彩蛋", easter_egg.open_count() == 1,
          f"彩蛋窗口数={easter_egg.open_count()}")
    check("已经弹出时不会重复弹",
          show_easter_egg() is None and easter_egg.open_count() == 1,
          f"彩蛋窗口数={easter_egg.open_count()}")

    for egg in list(easter_egg._OPEN):
        egg._on_yes()
    pump(app, 0.5)
    check("关闭后不再占用窗口", easter_egg.open_count() == 0,
          f"彩蛋窗口数={easter_egg.open_count()}")

    # ---------------- 6. 四种语言 ----------------
    missing = [code for code in ("zh-Hant", "en", "ja")
               if not i18n.TABLE.get("你是萝莉控吗？")
               or not i18n.TABLE.get("搜索设置")]
    rendered = i18n.translate_all("你承认啦！")
    check("「你承认啦！」四种语言齐全",
          len(set(rendered.values())) == 4
          and rendered["zh-Hans"] == "你承认啦！"
          and all(rendered[code] for code in ("zh-Hant", "en", "ja")),
          str(rendered))
    check("彩蛋与搜索文案四种语言齐全", not missing, ", ".join(missing) or "齐全")

    translations = {}
    for code in ("zh-Hant", "en", "ja"):
        i18n.set_language(code)
        translations[code] = i18n.t("你是萝莉控吗？")
    check("三种译文的问句各不相同",
          len(set(translations.values())) == 3, str(translations))
    i18n.set_language("zh-Hans")

    settings_window.close()
    settings_window.deleteLater()
    pump(app, 0.3)

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- EASTER EGG SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("EASTER EGG SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
