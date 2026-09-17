#!/usr/bin/env python3
"""Regenerate `lucide.json` from the `lucide-static` npm package.

The app ships icon geometry rather than pulling a font from a CDN (restyle plan
Phase 6), so the SVG bodies are vendored into `lucide.json` and read at runtime
by `apps/web/templatetags/icons.py`, `assets/javascript/common/Icon.jsx` and
`assets/javascript/common/Icon.vue`.

`aliases.json` maps the names the call sites use — mostly the Font Awesome
names they were converted from — onto Lucide names, and is hand-maintained.

Usage (from the repo root):

    npm install --no-save lucide-static
    python assets/icons/build_icons.py

Only the icons already in `lucide.json` are refreshed; to add one, pass it:

    python assets/icons/build_icons.py chevron-up folder
"""

import json
import re
import sys
from pathlib import Path

ICONS_DIR = Path(__file__).resolve().parent
SOURCE_DIR = ICONS_DIR.parents[1] / "node_modules" / "lucide-static" / "icons"


def body(name):
    """The inner markup of one Lucide SVG, with the wrapper `<svg>` stripped.

    The wrapper is supplied by the renderers, so every icon inherits one set of
    stroke attributes and cannot drift from the others.
    """
    src = (SOURCE_DIR / f"{name}.svg").read_text()
    inner = src[src.index(">", src.index("<svg")) + 1 : src.rindex("</svg>")]
    return re.sub(r"\s+", " ", inner).strip()


def main(extra):
    path = ICONS_DIR / "lucide.json"
    geometry = json.loads(path.read_text())
    for name in sorted(set(geometry) | set(extra)):
        geometry[name] = body(name)
    path.write_text(json.dumps(dict(sorted(geometry.items())), indent=2) + "\n")

    aliases = json.loads((ICONS_DIR / "aliases.json").read_text())
    dangling = sorted({v for v in aliases.values()} - set(geometry))
    if dangling:
        sys.exit(f"aliases.json points at icons that are not in lucide.json: {dangling}")
    print(f"{len(geometry)} icons, {len(aliases)} aliases")


if __name__ == "__main__":
    main(sys.argv[1:])
