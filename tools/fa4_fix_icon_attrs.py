#!/usr/bin/env python3
"""
FA4 → FA7: Fix icon= XML attributes with FA4 bare names.

Converts `icon="fa-X-o"` and `icon="fa-X"` patterns in XML files to
explicit FA7 class strings (`fa-regular fa-Y` or `fa-solid fa-Y`).

These patterns appear in Odoo view XML as stat button icon attributes:
    <button ... icon="fa-clock-o" ...>

The icon string is passed to `iconFromString()` in view_button.js, which
previously relied on the `fa` base class. With FA7, the full style prefix
must be present.
"""

import re
import sys
from pathlib import Path

# FA4 icon name (without `fa-` prefix) → FA7 full class string
# Keys cover both `-o` outline variants and renamed solid icons.
ICON_MAP: dict[str, str] = {
    # Outline (-o) variants → fa-regular + FA7 name
    "fa-file-text-o": "fa-regular fa-file-lines",
    "fa-pencil-square-o": "fa-regular fa-pen-to-square",
    "fa-clock-o": "fa-regular fa-clock",
    "fa-commenting-o": "fa-regular fa-comment-dots",
    "fa-envelope-o": "fa-regular fa-envelope",
    "fa-bell-slash-o": "fa-regular fa-bell-slash",
    "fa-sun-o": "fa-regular fa-sun",
    "fa-files-o": "fa-regular fa-copy",
    "fa-star-half-o": "fa-regular fa-star-half-stroke",
    "fa-id-card-o": "fa-regular fa-id-card",
    "fa-address-card-o": "fa-regular fa-address-card",
    "fa-calendar-plus-o": "fa-regular fa-calendar-plus",
    "fa-calendar-o": "fa-regular fa-calendar",
    "fa-paper-plane-o": "fa-regular fa-paper-plane",
    "fa-check-square-o": "fa-regular fa-square-check",
    "fa-square-o": "fa-regular fa-square",
    "fa-circle-o": "fa-regular fa-circle",
    "fa-star-o": "fa-regular fa-star",
    "fa-heart-o": "fa-regular fa-heart",
    "fa-file-text-o": "fa-regular fa-file-lines",
    "fa-minus-square-o": "fa-regular fa-square-minus",
    "fa-plus-square-o": "fa-regular fa-square-plus",
    "fa-caret-square-o-right": "fa-regular fa-square-caret-right",
    "fa-caret-square-o-down": "fa-regular fa-square-caret-down",
    "fa-caret-square-o-up": "fa-regular fa-square-caret-up",
    "fa-caret-square-o-left": "fa-regular fa-square-caret-left",
    "fa-file-image-o": "fa-regular fa-file-image",
    "fa-file-pdf-o": "fa-regular fa-file-pdf",
    "fa-file-video-o": "fa-regular fa-file-video",
    "fa-picture-o": "fa-regular fa-image",
    "fa-question-circle-o": "fa-regular fa-circle-question",
    "fa-smile-o": "fa-regular fa-face-smile",
    "fa-building-o": "fa-regular fa-building",
    "fa-user-o": "fa-regular fa-user",
    "fa-user-circle-o": "fa-regular fa-circle-user",
    "fa-share-square-o": "fa-regular fa-share-from-square",
    "fa-trash-o": "fa-regular fa-trash-can",
    "fa-bell-o": "fa-regular fa-bell",
    "fa-keyboard-o": "fa-regular fa-keyboard",
    "fa-hand-paper-o": "fa-regular fa-hand",
    "fa-pause-circle-o": "fa-regular fa-circle-pause",
    "fa-play-circle-o": "fa-regular fa-circle-play",
    "fa-hourglass-o": "fa-regular fa-hourglass",
    "fa-circle-o-notch": "fa-solid fa-circle-notch",
    "fa-check-circle-o": "fa-regular fa-circle-check",
    "fa-times-circle-o": "fa-regular fa-circle-xmark",
    "fa-info-circle": "fa-solid fa-circle-info",
    "fa-exclamation-circle": "fa-solid fa-circle-exclamation",
    "fa-heart-o": "fa-regular fa-heart",
    # Solid renamed icons (no -o suffix, but renamed in FA7)
    "fa-file-text": "fa-solid fa-file-lines",
    "fa-pencil-square": "fa-solid fa-pen-to-square",
    "fa-commenting": "fa-solid fa-comment-dots",
    "fa-picture": "fa-solid fa-image",
    "fa-plus-square": "fa-solid fa-square-plus",
    "fa-minus-square": "fa-solid fa-square-minus",
    "fa-check-square": "fa-solid fa-square-check",
    "fa-caret-square-right": "fa-solid fa-square-caret-right",
    "fa-user-times": "fa-solid fa-user-xmark",
    "fa-share-square": "fa-solid fa-share-from-square",
    "fa-id-card": "fa-solid fa-id-card",
    "fa-address-card": "fa-solid fa-address-card",
    "fa-circle-thin": "fa-regular fa-circle",
    "fa-trash": "fa-solid fa-trash-can",
    # Brand icons
    "fa-whatsapp": "fa-brands fa-whatsapp",
    "fa-facebook": "fa-brands fa-facebook",
    "fa-twitter": "fa-brands fa-x-twitter",
    "fa-linkedin": "fa-brands fa-linkedin",
    "fa-github": "fa-brands fa-github",
    "fa-google": "fa-brands fa-google",
    "fa-youtube": "fa-brands fa-youtube",
    "fa-instagram": "fa-brands fa-instagram",
}

# Match icon="<value>" in XML attributes (both single and double-quoted)
_ICON_ATTR_RE = re.compile(r'(?<=\bicon=)(["\'])(fa-[\w-]+)(\1)')


def _replace_icon(m: re.Match) -> str:
    quote, name, _ = m.group(1), m.group(2), m.group(3)
    fa7 = ICON_MAP.get(name)
    if fa7 is None:
        # Unknown name: try stripping -o suffix for generic outline → regular mapping
        if name.endswith("-o"):
            base = name[:-2]
            fa7 = f"fa-regular {base}"
        else:
            return m.group(0)  # unchanged
    return f'{quote}{fa7}{quote}'


def fix_file(path: Path) -> int:
    """Return number of substitutions made."""
    text = path.read_text(encoding="utf-8")
    new_text, count = _ICON_ATTR_RE.subn(_replace_icon, text)
    if count:
        path.write_text(new_text, encoding="utf-8")
    return count


def main(roots: list[str]) -> None:
    total_files = 0
    total_subs = 0
    for root in roots:
        for xml_path in sorted(Path(root).rglob("*.xml")):
            # Skip node_modules and dist directories
            parts = xml_path.parts
            if any(p in parts for p in ("node_modules", "dist", "_vendor")):
                continue
            count = fix_file(xml_path)
            if count:
                total_files += 1
                total_subs += count
                print(f"  {xml_path}: {count} fix(es)")
    print(f"\nTotal: {total_files} files, {total_subs} substitutions")


if __name__ == "__main__":
    search_roots = sys.argv[1:] if len(sys.argv) > 1 else ["."]
    main(search_roots)
