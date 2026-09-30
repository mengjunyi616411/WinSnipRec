"""Recording core of WinSnipRec: screen grabbing, audio devices, encoding.

The public entry points are re-exported here for convenience::

    from winsnip.core import Recorder, RecorderState, ScreenGrabber
"""

from __future__ import annotations

from .audio import AudioDevice, default_microphone, list_microphones
from .encoder import (
    FfmpegVideoWriter,
    ffmpeg_available,
    ffmpeg_path,
    run_ffmpeg,
)
from .recorder import Recorder, RecorderState
from .screen import Monitor, ScreenGrabber, list_monitors, virtual_rect

__all__ = [
    "AudioDevice",
    "FfmpegVideoWriter",
    "Monitor",
    "Recorder",
    "RecorderState",
    "ScreenGrabber",
    "default_microphone",
    "ffmpeg_available",
    "ffmpeg_path",
    "list_microphones",
    "list_monitors",
    "run_ffmpeg",
    "virtual_rect",
]
