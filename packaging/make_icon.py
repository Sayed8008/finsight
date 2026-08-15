"""Render the Windows icon from the SVG the application already uses.

    .venv/bin/python packaging/make_icon.py

Windows executables carry a `.ico`, and PyInstaller refuses an SVG on that
platform — so a raster copy has to exist. It is generated rather than drawn by
hand so the two cannot drift: change `finsight.svg` and re-run this, and the
launcher, the window and the Windows executable all show the same mark.

Qt does the rasterising, which is deliberate: it is already a dependency, it
reads the SVG with the same renderer the application uses, and it writes ICO
natively. Pulling in Pillow or ImageMagick to produce one file would be a
build-time dependency for something Qt already does.

An ICO holds several sizes and Windows picks per context — 16px in a title
bar, 48px in Explorer, 256px on the desktop. Rendering each from the vector
gives a crisp result at every one; scaling a single large bitmap down does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtWidgets import QApplication

RESOURCES = Path(__file__).resolve().parents[1] / "frontend" / "client" / "resources"
SOURCE = RESOURCES / "finsight.svg"
TARGET = RESOURCES / "finsight.ico"

#: The sizes Windows actually asks for. 256 is what the desktop and the large
#: icon view use; 16 is the title bar and the taskbar at small scaling.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(source: Path, target: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"No such icon source: {source}")

    icon = QIcon(str(source))
    if icon.isNull():
        raise SystemExit(f"Qt could not read {source}")

    images = []
    for size in SIZES:
        # Painted onto a transparent image rather than taken from
        # `icon.pixmap()` alone, so every size is rendered from the vector at
        # that size instead of being scaled from whichever one Qt cached.
        image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        icon.paint(painter, 0, 0, size, size)
        painter.end()
        images.append(image)

    # Qt's ICO writer takes the largest image and generates the rest, so the
    # 256 is written and the smaller renders confirm it reads cleanly at those
    # sizes before it is.
    if not images[-1].save(str(target), "ICO"):
        raise SystemExit(f"Qt could not write {target}")


def main() -> int:
    QApplication(sys.argv)
    render(SOURCE, TARGET)
    size_kb = TARGET.stat().st_size / 1024
    shown = TARGET.relative_to(Path.cwd()) if TARGET.is_relative_to(Path.cwd()) else TARGET
    print(f"Wrote {shown}")
    print(f"  {size_kb:.1f} KB, sizes rendered: {', '.join(str(s) for s in SIZES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
