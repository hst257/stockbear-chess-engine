"""Development-only asset preparation. Runtime never downloads artwork.

Run from the repository root with the project Python after installing requirements.
Original SVGs are retained unchanged; PNGs are rendered at 256 pixels with Pygame.
"""

import io
import hashlib
import argparse
import os
from pathlib import Path
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

ET.register_namespace("", "http://www.w3.org/2000/svg")

ROOT = Path(__file__).resolve().parents[1] / "app" / "assets"
AGENT = {"User-Agent": "ChessLab/0.1 (educational desktop chess; asset preparation)"}


def fetch(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (429, 502, 503) or attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("Asset download failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Rebuild PNGs from checked-in SVGs.")
    args = parser.parse_args()
    (ROOT / "source").mkdir(parents=True, exist_ok=True)
    (ROOT / "pieces").mkdir(parents=True, exist_ok=True)
    for side, color in (("l", "w"), ("d", "b")):
        for piece in "pnbrqk":
            filename = f"Chess_{piece}{side}t45.svg"
            page = f"https://commons.wikimedia.org/wiki/File:{filename}"
            # Check the offered license on each individual file, not just the set.
            if not args.offline:
                license_page = fetch(page).decode("utf-8")
                if "creativecommons.org/licenses/by-sa/3.0" not in license_page:
                    raise RuntimeError(f"Expected CC BY-SA 3.0 offer not found: {page}")
            path = ROOT / "source" / filename
            if not path.exists():
                if args.offline:
                    raise FileNotFoundError(path)
                digest = hashlib.md5(filename.encode(), usedforsecurity=False).hexdigest()
                path.write_bytes(fetch(f"https://upload.wikimedia.org/wikipedia/commons/{digest[0]}/{digest[:2]}/{filename}"))
            svg = ET.fromstring(path.read_bytes())
            # SDL_image's SVG loader does not consistently scale viewBox content.
            # An explicit vector transform keeps the raster sharp at 256 pixels.
            svg.set("viewBox", "0 0 256 256")
            svg.set("width", "256")
            svg.set("height", "256")
            group = ET.Element("{http://www.w3.org/2000/svg}g", transform=f"scale({256 / 45})")
            for child in list(svg):
                svg.remove(child)
                group.append(child)
            svg.append(group)
            image = pygame.image.load(io.BytesIO(ET.tostring(svg)), "piece.svg")
            pygame.image.save(image, ROOT / "pieces" / f"{color}{piece.upper()}.png")
            print(f"Prepared {color}{piece.upper()}: {page}")
            if not args.offline:
                time.sleep(1)
    if not args.offline:
        (ROOT / "CC-BY-SA-3.0.txt").write_bytes(
            fetch("https://creativecommons.org/licenses/by-sa/3.0/legalcode.txt")
        )


if __name__ == "__main__":
    main()
