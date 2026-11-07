"""Create a GitHub Release and attach build artifacts.

Usage (token comes from the environment so it never lands in shell history)::

    $env:GITHUB_TOKEN = "ghp_xxx"
    python tools/upload_release.py --tag v1.4.0 \\
        --asset "C:\\WinSnipRec-Setup\\WinSnipRec-Setup-1.4.0.exe"

The release body defaults to the section of CHANGELOG.md that matches the tag,
so the notes stay in sync with the changelog.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
DEFAULT_REPO = "mengjunyi616411/WinSnipRec"


def _request(url: str, token: str, *, method: str = "GET", data: bytes | None = None,
             content_type: str = "application/json", timeout: float = 60.0):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "WinSnipRec-release-uploader",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return json.loads(body) if body else None


def changelog_section(version: str) -> str:
    """The CHANGELOG block for ``version`` (without the heading)."""
    path = ROOT / "CHANGELOG.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^##\s*\[?" + re.escape(version.lstrip("vV")) + r"\]?[^\n]*\n(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def find_release(repo: str, tag: str, token: str):
    try:
        return _request(f"{API}/repos/{repo}/releases/tags/{tag}", token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def create_release(repo: str, tag: str, title: str, body: str, token: str):
    payload = json.dumps({
        "tag_name": tag,
        "name": title,
        "body": body,
        "draft": False,
        "prerelease": False,
    }).encode("utf-8")
    return _request(f"{API}/repos/{repo}/releases", token, method="POST", data=payload)


def delete_asset(repo: str, asset_id: int, token: str) -> None:
    _request(f"{API}/repos/{repo}/releases/assets/{asset_id}", token, method="DELETE")


def upload_asset(repo: str, release_id: int, path: Path, token: str) -> dict:
    data = path.read_bytes()
    suffix = path.suffix.lower()
    content_type = {
        ".exe": "application/x-msdownload",
        ".msi": "application/x-msi",
        ".zip": "application/zip",
        ".txt": "text/plain",
    }.get(suffix, "application/octet-stream")
    url = (f"{UPLOADS}/repos/{repo}/releases/{release_id}/assets"
           f"?name={urllib.parse.quote(path.name)}")
    return _request(url, token, method="POST", data=data,
                    content_type=content_type, timeout=900.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a GitHub release and upload assets.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPO", DEFAULT_REPO))
    parser.add_argument("--tag", required=True, help="e.g. v1.4.0")
    parser.add_argument("--title", default="", help="release title; defaults to the tag")
    parser.add_argument("--notes", default="", help="release body; defaults to CHANGELOG section")
    parser.add_argument("--asset", action="append", default=[], help="file to upload (repeatable)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        print("缺少 GITHUB_TOKEN 环境变量（需要一个带 repo 权限的 token）。", file=sys.stderr)
        return 2

    repo = args.repo.strip()
    tag = args.tag.strip()
    title = args.title.strip() or f"WinSnipRec {tag.lstrip('vV')}"
    body = args.notes.strip() or changelog_section(tag)
    assets = [Path(p) for p in args.asset]
    for asset in assets:
        if not asset.is_file():
            print(f"找不到附件：{asset}", file=sys.stderr)
            return 2

    print(f"仓库  : {repo}")
    print(f"标签  : {tag}")
    print(f"标题  : {title}")
    print(f"正文  : {len(body)} 字符" + ("（取自 CHANGELOG）" if not args.notes.strip() else ""))
    for asset in assets:
        print(f"附件  : {asset.name}  {asset.stat().st_size / 1024 / 1024:.1f} MB")
    if args.dry_run:
        print("dry-run：不实际调用 API")
        return 0

    release = find_release(repo, tag, token)
    if release is None:
        print("→ 创建 Release …")
        release = create_release(repo, tag, title, body, token)
        print(f"  已创建 id={release['id']}  {release['html_url']}")
    else:
        print(f"→ Release 已存在 id={release['id']}  {release['html_url']}")

    existing = {a["name"]: a["id"] for a in release.get("assets", [])}
    for asset in assets:
        if asset.name in existing:
            print(f"→ 覆盖同名附件 {asset.name} …")
            delete_asset(repo, existing[asset.name], token)
        print(f"→ 上传 {asset.name} …")
        uploaded = upload_asset(repo, release["id"], asset, token)
        print(f"  完成 {uploaded['size'] / 1024 / 1024:.1f} MB  "
              f"{uploaded['browser_download_url']}")

    final = find_release(repo, tag, token)
    print()
    print(f"Release 页面: {final['html_url']}")
    print(f"附件数量   : {len(final.get('assets', []))}")
    for asset in final.get("assets", []):
        print(f"  - {asset['name']}  {asset['size'] / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
