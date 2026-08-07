import re
from hashlib import sha512
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def get_saturation(rgb: Sequence[int]) -> float:
    c_max = max(rgb) / 255
    c_min = min(rgb) / 255
    d = c_max - c_min
    return 0.0 if d == 0 else d / (1 - abs(c_max + c_min - 1))


def get_lightness(rgb: Sequence[int]) -> float:
    return (max(rgb) + min(rgb)) / 2 / 255


_HEX_COLOR_RE = re.compile(
    r"#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z"
)


def hex_to_rgb(hx: str) -> tuple[int, int, int]:
    if not _HEX_COLOR_RE.match(hx):
        raise ValueError(f"not a hexadecimal color: {hx!r}")
    digits = hx.removeprefix("#")
    if len(digits) <= 4:
        digits = "".join(d * 2 for d in digits)
    return tuple(int(digits[i : i + 2], 16) for i in range(0, 6, 2))


def rgb_to_hex(rgb: Sequence[int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def hsl_from_seed(seed: str) -> str:
    hashed_seed = sha512(seed.encode()).hexdigest()
    hue = int(hashed_seed[0:2], 16) * 360 / 255
    sat = int(hashed_seed[2:4], 16) * ((70 - 40) / 255) + 40
    lig = 45
    return f"hsl({hue:.0f}, {sat:.0f}%, {lig:.0f}%)"
