"""Application settings persisted as JSON in %APPDATA%."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_data_dir() -> Path:
    """Where settings and logs live.

    ``WINSNIPREC_HOME`` overrides the location so that the self-tests never
    touch the settings of a real installation.
    """
    override = os.environ.get("WINSNIPREC_HOME")
    if override:
        path = Path(override)
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / "WinSnipRec"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_videos_dir() -> str:
    """The user's Videos\\录制 folder, mirroring the Xbox Game Bar convention."""
    candidates = [
        Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos" / "录制",
        Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos" / "Captures",
        Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return str(candidate)
        except Exception:
            continue
    return str(Path.home())


def default_pictures_dir() -> str:
    path = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Pictures" / "屏幕截图"
    try:
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    except Exception:
        return str(Path.home())


@dataclass
class Settings:
    theme: str = "system"                 # system | light | dark
    video_dir: str = field(default_factory=default_videos_dir)
    image_dir: str = field(default_factory=default_pictures_dir)
    fps: int = 30
    crf: int = 20                         # lower = better quality / bigger file
    capture_cursor: bool = True
    mic_enabled: bool = False
    mic_device: str = ""                  # ffmpeg dshow device id
    system_audio: bool = False            # loopback; only when a device exists
    system_audio_device: str = ""         # loopback dshow device id (Stereo Mix / What U Hear)
    countdown: int = 0                    # 0 / 3 / 5 / 10 seconds
    confirm_region: bool = False          # False = start as soon as the drag ends (Win11 behaviour)
    animations: bool = True               # Fluent motion: splash, window fade / slide
    style: str = "win11"                  # interface style: win11 | win10 | system
    reveal_strength: str = "weak"         # Win10 pointer light: weak | normal | strong
    hotkey_snip: str = "Win+Shift+S"
    hotkey_record: str = "Win+Shift+R"
    last_mode: str = "video"              # camera | video
    last_shape: str = "rectangle"         # rectangle | window | fullscreen | freeform
    show_region_hint: bool = True
    copy_image_to_clipboard: bool = True
    open_folder_when_done: bool = False
    minimize_to_tray: bool = True
    show_countdown: bool = True

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        settings = cls(**clean)
        settings.sanitise()
        return settings

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        try:
            path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def sanitise(self) -> None:
        self.fps = max(5, min(60, int(self.fps or 30)))
        self.crf = max(0, min(51, int(self.crf if self.crf is not None else 20)))
        if self.theme not in ("system", "light", "dark"):
            self.theme = "system"
        if self.last_mode not in ("camera", "video"):
            self.last_mode = "video"
        if self.last_shape not in ("rectangle", "window", "fullscreen", "freeform"):
            self.last_shape = "rectangle"
        if self.countdown not in (0, 3, 5, 10):
            self.countdown = 0
        for attr in ("video_dir", "image_dir"):
            value = getattr(self, attr)
            try:
                Path(value).mkdir(parents=True, exist_ok=True)
            except Exception:
                setattr(self, attr, str(Path.home()))

    def ensure_dirs(self) -> None:
        for attr in ("video_dir", "image_dir"):
            try:
                Path(getattr(self, attr)).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass


settings = Settings.load()
