#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "pillow>=11.3.0",
# ]
# ///
"""Shrink the images of the docs so none is larger than 2000 x 2000 pixels.

Mintlify never serves an image wider than 2500 px, and a screenshot above 2000 px
only makes the repository heavier. This script resizes every PNG, JPEG and WebP
that does not fit in a 2000 x 2000 box (the aspect ratio is kept), then saves it
again with lossless compression, so the text of a screenshot stays sharp.

It is idempotent: an image that already fits is left untouched.

    uv run scripts/optimize_images.py              # every image in images/ and logo/
    uv run scripts/optimize_images.py a.png b.png  # only these files

pre-commit calls it with the staged files. It exits with 1 when it changed a
file, so the commit stops and you can stage the smaller image.
"""

import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOLDERS = ("images", "logo")
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_SIDE = 2000


def iter_images(arguments):
    if arguments:
        for argument in arguments:
            path = pathlib.Path(argument).resolve()
            if path.suffix.lower() in EXTENSIONS and path.is_file():
                yield path
        return
    for folder in FOLDERS:
        for path in sorted((ROOT / folder).rglob("*")):
            if path.suffix.lower() in EXTENSIONS:
                yield path


def save_lossless(image, path):
    extension = path.suffix.lower()
    if extension == ".png":
        image.save(path, format="PNG", optimize=True)
    elif extension == ".webp":
        image.save(path, format="WEBP", lossless=True, quality=100, method=6)
    else:
        image.save(path, format="JPEG", quality=92, optimize=True)


def optimize(path):
    """Resize `path` if it is too big. Returns (old_size, new_size) or None."""
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        if max(width, height) <= MAX_SIDE:
            return None
        before = path.stat().st_size
        resized = image.copy()
        resized.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    save_lossless(resized, path)
    after = path.stat().st_size
    print(
        f"{path.relative_to(ROOT)}: {width}x{height} -> "
        f"{resized.width}x{resized.height}, {before / 1024:.0f} KB -> {after / 1024:.0f} KB"
    )
    return before, after


def main(arguments):
    changed = [path for path in iter_images(arguments) if optimize(path)]
    if changed:
        print(f"resized {len(changed)} image(s). Stage them again.")
        return 1
    print("every image fits in 2000 x 2000")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
