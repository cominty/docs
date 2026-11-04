#!/usr/bin/env python3
"""Check that the images of the docs can be served by Mintlify.

Mintlify serves static files from the repository as they are committed. It does
not resolve Git LFS without an Enterprise plan: it would publish the 131-byte
pointer file instead of the image, and every image of the site would break.

    python scripts/check_images.py

Errors (exit code 1):
  - a file of 20 MB or more (Mintlify's limit);
  - a PNG, JPEG, GIF or WebP larger than 2000 px on a side;
  - a `filter=lfs` rule in .gitattributes that covers images/ or logo/;
  - a file that is a Git LFS pointer (a checkout without LFS shows it).

Warning (exit code 0): a GIF or SVG over 1 MB. Mintlify serves them as they are.

Standard library only, so CI needs no install.
"""

import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOLDERS = ("images", "logo")
MAX_BYTES = 20 * 1024 * 1024
MAX_SIDE = 2000
WARN_BYTES = 1024 * 1024
LFS_POINTER = b"version https://git-lfs"
FIX = "run `uv run scripts/optimize_images.py`"


def png_size(head):
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", head[16:24])
    return None


def gif_size(head):
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", head[6:10])
    return None


def jpeg_size(path):
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            return None
        while True:
            marker = handle.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                return None
            if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                continue
            length_bytes = handle.read(2)
            if len(length_bytes) < 2:
                return None
            length = struct.unpack(">H", length_bytes)[0]
            if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                handle.read(1)
                height, width = struct.unpack(">HH", handle.read(4))
                return width, height
            handle.seek(length - 2, 1)


def webp_size(head):
    if head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    kind = head[12:16]
    if kind == b"VP8X":
        width = int.from_bytes(head[24:27], "little") + 1
        height = int.from_bytes(head[27:30], "little") + 1
        return width, height
    if kind == b"VP8L":
        bits = int.from_bytes(head[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8 ":
        width, height = struct.unpack("<HH", head[26:30])
        return width & 0x3FFF, height & 0x3FFF
    return None


def image_size(path, head):
    suffix = path.suffix.lower()
    if suffix == ".png":
        return png_size(head)
    if suffix == ".gif":
        return gif_size(head)
    if suffix in (".jpg", ".jpeg"):
        return jpeg_size(path)
    if suffix == ".webp":
        return webp_size(head)
    return None


def check_gitattributes():
    errors = []
    path = ROOT / ".gitattributes"
    if not path.exists():
        return errors
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "filter=lfs" not in line:
            continue
        pattern = line.split()[0]
        if pattern.startswith(FOLDERS) or pattern.startswith("*"):
            errors.append(
                f".gitattributes: `{pattern}` is stored with Git LFS. Mintlify "
                "publishes the pointer file instead of the image. Remove the rule."
            )
    return errors


def check_file(path):
    errors, warnings = [], []
    name = path.relative_to(ROOT)
    size = path.stat().st_size
    with path.open("rb") as handle:
        head = handle.read(64)
    if head.startswith(LFS_POINTER):
        return [f"{name}: Git LFS pointer, not an image. Commit the real file."], []
    if size >= MAX_BYTES:
        errors.append(f"{name}: {size / 1024 / 1024:.1f} MB, Mintlify's limit is 20 MB")
    dimensions = image_size(path, head)
    if dimensions and max(dimensions) > MAX_SIDE:
        errors.append(
            f"{name}: {dimensions[0]}x{dimensions[1]}, larger than "
            f"{MAX_SIDE}x{MAX_SIDE}. {FIX}"
        )
    if path.suffix.lower() in (".gif", ".svg") and size > WARN_BYTES:
        warnings.append(
            f"{name}: {size / 1024:.0f} KB. Mintlify serves GIF and SVG files "
            "as is, so compress it first."
        )
    return errors, warnings


def main():
    errors = check_gitattributes()
    warnings = []
    checked = 0
    for folder in FOLDERS:
        for path in sorted((ROOT / folder).rglob("*")):
            if not path.is_file():
                continue
            checked += 1
            file_errors, file_warnings = check_file(path)
            errors.extend(file_errors)
            warnings.extend(file_warnings)

    print(f"checked {checked} file(s) in {', '.join(FOLDERS)}")
    for warning in warnings:
        print(f"  warning: {warning}")
    if errors:
        print(f"found {len(errors)} problem(s):")
        for error in errors:
            print(f"  {error}")
        return 1
    print("all images are ready for Mintlify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
