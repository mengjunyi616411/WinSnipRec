"""Update check.

Two sources are supported, both read-only:

* ``github``  —— ``https://api.github.com/repos/<owner>/<repo>/releases/latest``
  (the API endpoint is reachable from here; github.com itself times out, so the
  download page may not open — the caller surfaces that to the user)
* ``manifest`` —— any URL returning JSON shaped like::

      {"version": "1.4.0", "notes": "...", "url": "https://..."}

Nothing here downloads or installs anything. It only answers "is there a newer
version, and where do I send the user".
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__
from .i18n import t as _t

USER_AGENT = f"WinSnipRec/{__version__} (+https://github.com)"
TIMEOUT = 8.0

#: 官方仓库；用户没配置「更新源」时查这里。
DEFAULT_REPO = "mengjunyi616411/WinSnipRec"


@dataclass(frozen=True)
class UpdateInfo:
    """A newer release than the running build."""

    version: str
    notes: str
    url: str

    @property
    def current(self) -> str:
        return __version__


def _version_tuple(text: str) -> tuple[int, ...]:
    """'v1.4.2' -> (1, 4, 2). Unparsable parts are ignored."""
    cleaned = (text or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", cleaned.split("-")[0].split("+")[0])
    return tuple(int(p) for p in parts) if parts else (0,)


def _paren(text: str) -> str:
    """用当前语言的括号包起来。中文/日文用全角，其它用半角。"""
    try:
        from .i18n import language as _language

        wide = _language() in ("zh-Hans", "zh-Hant", "ja")
    except Exception:
        wide = True
    return f"（{text}）" if wide else f"({text})"


def normalize_target(text: str) -> str:
    """把用户填的东西整理成 owner/repo。

    用户很自然地会把整个网址贴进来（实测就有人填
    https://github.com/owner/repo），而 API 只认 owner/repo —— 之前直接拼进
    URL 就会拼出 /repos/https://github.com/... 然后 404。这里统一收口：
      https://github.com/owner/repo(.git)  -> owner/repo
      git@github.com:owner/repo.git        -> owner/repo
      owner/repo                           -> owner/repo
    """
    value = (text or "").strip()
    if not value:
        return ""
    match = re.search(r"github\.com[/:]+([^/\s]+)/([^/\s#?]+)", value)
    if match:
        owner, repo = match.group(1), match.group(2)
        if repo.endswith(".git"):
            repo = repo[:-4]
        return f"{owner}/{repo}"
    # 已经是 owner/repo 形态就直接用（顺手去掉 .git）
    if "/" in value and "://" not in value and "@" not in value:
        parts = [p for p in value.split("/") if p]
        if len(parts) >= 2:
            repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
            return f"{parts[0]}/{repo}"
    return value


def is_newer(candidate: str, current: str | None = None) -> bool:
    """Whether ``candidate`` is a strictly newer version than ``current``."""
    new = _version_tuple(candidate)
    old = _version_tuple(current if current is not None else __version__)
    length = max(len(new), len(old))
    new += (0,) * (length - len(new))
    old += (0,) * (length - len(old))
    return new > old


def system_proxy() -> str:
    """读 Windows「Internet 选项」里配置的代理（Clash/v2ray 的"系统代理"就写这里）。

    urllib 自己只认环境变量和 macOS/Linux 的设置，不读 Windows 这个键，
    所以用户开了系统代理程序仍然直连 —— 这里补上。
    """
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return ""
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        finally:
            key.Close()
    except Exception:
        return ""
    server = str(server or "").strip()
    if not server:
        return ""
    # "http=127.0.0.1:7890;https=127.0.0.1:7890" 或 "127.0.0.1:7890"
    for part in server.split(";"):
        if "=" in part:
            name, _, value = part.partition("=")
            if name.strip().lower() in ("http", "https"):
                server = value.strip()
                break
    if "://" not in server:
        server = "http://" + server
    return server


def proxy_url() -> str:
    """当前生效的代理地址。空字符串表示直连。

    配置（设置里的「网络代理」）：
      留空 / system  -> 跟随 Windows 系统代理
      direct         -> 强制直连
      http://...     -> 手动指定
    """
    try:
        from .settings import settings as _settings

        mode = str(getattr(_settings, "update_proxy", "") or "").strip()
    except Exception:
        mode = ""
    if mode.lower() == "direct":
        return ""
    if mode and mode.lower() != "system":
        return mode if "://" in mode else "http://" + mode
    return system_proxy()


def _build_opener():
    """按当前代理配置建 opener。空配置也用 ProxyHandler({}) 显式关掉环境变量代理。"""
    address = proxy_url()
    if address:
        handler = urllib.request.ProxyHandler({"http": address, "https": address})
    else:
        handler = urllib.request.ProxyHandler({})
    return urllib.request.build_opener(handler)


def _fetch_json(url: str, timeout: float = TIMEOUT) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
    opener = _build_opener()
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _release_to_info(data: dict) -> UpdateInfo | None:
    """把一个 GitHub release 对象转成 UpdateInfo（版本不比当前新就返回 None）。"""
    tag = str(data.get("tag_name") or "").strip()
    if not tag or not is_newer(tag):
        return None
    notes = str(data.get("body") or "").strip()
    url = str(data.get("html_url") or "").strip()
    assets = data.get("assets") or []
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            if name.lower().endswith(".exe"):
                url = str(asset.get("browser_download_url") or url)
                break
    return UpdateInfo(version=tag.lstrip("vV"), notes=notes, url=url)


def _from_github_preview(repo: str, timeout: float) -> UpdateInfo | None:
    """预览通道：在 /releases 里找最新的那个 prerelease。

    GitHub 的 /releases/latest 只会返回正式版，预览版必须自己筛：
    按 created_at 倒序取第一个 prerelease=True 且不是 draft 的。
    """
    data = _fetch_json(f"https://api.github.com/repos/{repo}/releases?per_page=30", timeout)
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("draft") or not item.get("prerelease"):
            continue
        info = _release_to_info(item)
        if info is not None:
            return info
    return None


def _from_github(repo: str, timeout: float) -> UpdateInfo | None:
    """稳定通道：/releases/latest 只返回正式版。"""
    data = _fetch_json(f"https://api.github.com/repos/{repo}/releases/latest", timeout)
    return _release_to_info(data) if isinstance(data, dict) else None


def _from_manifest(url: str, timeout: float) -> UpdateInfo | None:
    data = _fetch_json(url, timeout)
    if not isinstance(data, dict):
        return None
    version = str(data.get("version") or "").strip()
    if not version or not is_newer(version):
        return None
    return UpdateInfo(version=version.lstrip("vV"),
                      notes=str(data.get("notes") or "").strip(),
                      url=str(data.get("url") or "").strip())


def mirror_url(url: str, prefix: str) -> str:
    """给 GitHub 下载链接套一个加速前缀。

    用户反馈裸网访问 github.com 不稳定。实测：直连能下但慢（2552ms），
    ghfast.top 前缀 1026ms（快 2.5 倍），gh-proxy.com 1771ms；
    gh.llkk.cc / hub.gitmirror.com / ghp.ci / moeyy.xyz 已经死掉。
    所以前缀做成可配置，默认给 ghfast.top，失效时清空即可回到直连。
    """
    prefix = (prefix or "").strip()
    if not prefix or not url:
        return url
    if not prefix.endswith("/"):
        prefix += "/"
    if url.startswith(prefix):
        return url
    return prefix + url


def check(source: str = "github", target: str = "", *, channel: str = "stable",
          timeout: float = TIMEOUT) -> tuple[UpdateInfo | None, str]:
    """Look for a newer release.

    ``channel`` 决定查哪个通道：
      · ``stable``  —— /releases/latest，只返回正式版；
      · ``preview`` —— /releases 里最新的 prerelease（预览版）。

    Returns ``(info, message)``. ``info`` is None when already up to date *or*
    when the check failed; ``message`` always explains which of the two.
    """
    channel = (channel or "stable").strip().lower()
    source = (source or "github").strip().lower()
    target = (target or "").strip()
    if source == "manifest":
        if not target:
            return None, _t("没有配置更新地址")
        try:
            info = _from_manifest(target, timeout)
        except urllib.error.HTTPError as exc:
            return None, f"{_t('更新地址返回 HTTP')} {exc.code}"
        except urllib.error.URLError as exc:
            return None, f"{_t('连不上更新地址')}：{exc.reason}"
        except Exception as exc:
            return None, f"{_t('检查失败')}：{type(exc).__name__}: {exc}"
    else:
        repo = normalize_target(target) or DEFAULT_REPO
        if "/" not in repo or "OWNER" in repo:
            return None, _t("还没配置仓库地址") + _paren(_t("更新源"))
        try:
            if channel == "preview":
                info = _from_github_preview(repo, timeout)
            else:
                info = _from_github(repo, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, _t("找不到该仓库的 Release") + _paren(_t("可能还没发布"))
            return None, f"GitHub API HTTP {exc.code}"
        except urllib.error.URLError as exc:
            return None, f"{_t('连不上 GitHub')}：{exc.reason}"
        except Exception as exc:
            return None, f"{_t('检查失败')}：{type(exc).__name__}: {exc}"

    if info is None:
        message = f"{_t('已是最新版')}{_paren(__version__)}"
        if channel == "preview":
            message = f"{_t('没有预览版')}{_paren(_t('当前版本') + ' ' + __version__)}"
        return None, message
    label = _t("发现预览版") if channel == "preview" else _t("发现新版本")
    return info, f"{label} {info.version} {_paren(_t('当前版本') + ' ' + __version__)}"

