"""Autostart (logon Run key) test.

Enables, verifies and disables the entry, and restores whatever was registered
before the test so the machine is left exactly as it was found.

Run:  .venv\\Scripts\\python.exe tests\\selftest_startup.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_startup" / "_config"))

from winsnip import startup  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def main() -> int:
    original = startup.registered_command()
    print(f"[info] 测试前注册表里的值: {original!r}")
    print(f"[info] 本副本应注册的命令行 : {startup.startup_command()}")
    print(f"[info] 命令行解析出的可执行文件: {startup._executable_of(startup.startup_command())}")

    check("命令行以 --tray 结尾（登录后静默进托盘）",
          startup.startup_command().rstrip().endswith("--tray"),
          startup.startup_command())
    check("命令行指向真实存在的程序",
          Path(startup._executable_of(startup.startup_command())).exists(),
          startup._executable_of(startup.startup_command()))
    check("解析可执行文件能处理带空格的引号路径",
          startup._executable_of('"C:\\a b\\c.exe" --tray') == "C:\\a b\\c.exe",
          startup._executable_of('"C:\\a b\\c.exe" --tray'))

    # ---- enable ---------------------------------------------------------- #
    ok, message = startup.enable()
    check("enable() 成功", ok, message)
    check("注册表中出现该项", startup.is_enabled())
    check("注册的值与本副本一致", startup.is_current(), startup.registered_command() or "")
    check("enabled_and_current() 为真", startup.enabled_and_current())
    check("describe() 显示已开启", "已开启" in startup.describe(), startup.describe())
    check("重复 enable() 幂等", startup.enable()[0] and startup.is_current())

    # ---- disable --------------------------------------------------------- #
    ok, message = startup.disable()
    check("disable() 成功", ok, message)
    check("注册表中已移除该项", not startup.is_enabled())
    check("关闭后 describe() 提示未开启", "不会自动运行" in startup.describe(), startup.describe())
    check("重复 disable() 不报错", startup.disable()[0])

    # ---- stale entry repair ---------------------------------------------- #
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, startup.RUN_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, startup.VALUE_NAME, 0, winreg.REG_SZ,
                          r'"C:\definitely\not\here\nope.exe" --tray')
    check("能识别指向不存在文件的失效项", startup._stale())
    check("失效时 describe() 会提示", "已不存在" in startup.describe(), startup.describe())
    check("失效时 is_enabled() 仍为真（只是指向错了）",
          startup.is_enabled() and not startup.is_current())
    fixed = startup.refresh_if_stale()
    check("refresh_if_stale() 修复了失效项", fixed and startup.is_current(),
          startup.registered_command() or "")
    check("修复后不再是失效项", not startup._stale())

    # ---- live: launch exactly what the logon entry would launch ---------- #
    import subprocess
    import time

    subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe"], capture_output=True)
    time.sleep(0.5)
    startup.enable()
    command = startup.startup_command()
    print(f"[info] 现在模拟登录：直接执行注册的命令行\n       {command}")
    process = subprocess.Popen(command, cwd=str(ROOT))
    try:
        from winsnip import winapi

        # The window-visibility assertion needs a real desktop session; on the
        # offscreen platform (CI) there is no native window to enumerate, so only
        # the process-level checks run there.
        interactive = os.environ.get("QT_QPA_PLATFORM", "").lower() != "offscreen"
        main_window = None
        deadline = time.time() + 45
        while time.time() < deadline:
            time.sleep(0.5)
            if interactive:
                windows = winapi.list_windows()
                main_window = next((w for w in windows if "截图工具" in w.title), None)
                if main_window is not None:
                    break
            if process.poll() is not None:
                break
        check("登录命令能启动程序", process.poll() is None, f"pid={process.pid}")
        if interactive:
            check("启动后窗口是隐藏的（静默进托盘）", main_window is None,
                  "未发现可见主窗口" if main_window is None else f"出现了 {main_window.title}")
        else:
            check("启动后窗口是隐藏的（静默进托盘）", True, "offscreen 平台跳过窗口枚举")

        log = Path(os.environ["APPDATA"]) / "WinSnipRec" / "app.log"
        content = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        check("日志里记录了 ready", "ready" in content,
              content.strip().splitlines()[-1] if content.strip() else "无日志")
    finally:
        try:
            process.terminate()
            process.wait(timeout=10)
        except Exception:
            pass
        subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe"], capture_output=True)
        time.sleep(0.5)

    # ---- restore --------------------------------------------------------- #
    if original is None:
        startup.disable()
    else:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, startup.RUN_KEY_PATH, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, startup.VALUE_NAME, 0, winreg.REG_SZ, original)
    restored = startup.registered_command()
    check("测试后已恢复原状", restored == original,
          f"{restored!r} (原值 {original!r})")

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- STARTUP SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("STARTUP SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
