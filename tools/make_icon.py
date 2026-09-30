"""Render assets/app.ico from the vector app icon."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import icons  # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841 - needed for QPixmap/QIcon
    assets = ROOT / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    icon = icons.app_icon()
    images = []
    for size in SIZES:
        pixmap = icon.pixmap(size, size)
        path = assets / f"icon_{size}.png"
        pixmap.save(str(path), "PNG")
        images.append(pixmap.toImage())

    ico_path = assets / "app.ico"
    # Qt's ICO writer takes a single image; Pillow (bundled runtime) merges sizes.
    pngs = [str(assets / f"icon_{size}.png") for size in SIZES]
    try:
        from PIL import Image  # type: ignore

        base = Image.open(pngs[-1]).convert("RGBA")
        base.save(ico_path, format="ICO",
                  sizes=[(s, s) for s in SIZES if s <= 256])
        print(f"wrote {ico_path} via Pillow")
    except Exception as exc:
        icon.pixmap(256, 256).save(str(ico_path), "ICO")
        print(f"wrote {ico_path} via Qt ({exc!r})")

    print(f"sizes: {SIZES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
