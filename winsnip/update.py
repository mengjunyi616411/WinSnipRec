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
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

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


def _fetch_json(url: str, timeout: float = TIMEOUT) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _from_github(repo: str, timeout: float) -> UpdateInfo | None:
    data = _fetch_json(f"https://api.github.com/repos/{repo}/releases/latest", timeout)
    if not isinstance(data, dict):
        return None
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


def check(source: str = "github", target: str = "", *,
          timeout: float = TIMEOUT) -> tuple[UpdateInfo | None, str]:
    """Look for a newer release.

    Returns ``(info, message)``. ``info`` is None when already up to date *or*
    when the check failed; ``message`` always explains which of the two.
    """
    source = (source or "github").strip().lower()
    target = (target or "").strip()
    if source == "manifest":
        if not target:
            return None, "没有配置更新地址"
        try:
            info = _from_manifest(target, timeout)
        except urllib.error.HTTPError as exc:
            return None, f"更新地址返回 HTTP {exc.code}"
        except urllib.error.URLError as exc:
            return None, f"连不上更新地址：{exc.reason}"
        except Exception as exc:
            return None, f"检查失败：{type(exc).__name__}: {exc}"
    else:
        repo = normalize_target(target) or DEFAULT_REPO
        if "/" not in repo or "OWNER" in repo:
            return None, "还没配置仓库地址（设置里的「更新源」）"
        try:
            info = _from_github(repo, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, "找不到该仓库的 Release（可能还没发布）"
            return None, f"GitHub API 返回 HTTP {exc.code}"
        except urllib.error.URLError as exc:
            return None, f"连不上 GitHub：{exc.reason}"
        except Exception as exc:
            return None, f"检查失败：{type(exc).__name__}: {exc}"

    if info is None:
        return None, f"已是最新版（{__version__}）"
    return info, f"发现新版本 {info.version}（当前 {__version__}）"
