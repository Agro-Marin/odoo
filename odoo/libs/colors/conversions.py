import re
from hashlib import sha512
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
__all__ = [
    "get_brightness",
    "get_hsl_from_seed",
    "get_lightness",
    "get_palette_color",
    "get_saturation",
    "hex_to_rgb",
    "lighten_hex",
    "rgb_to_hex",
]


def get_saturation(rgb: Sequence[int]) -> float:
    c_max = max(rgb) / 255
    c_min = min(rgb) / 255
    d = c_max - c_min
    return 0.0 if d == 0 else d / (1 - abs(c_max + c_min - 1))


def get_lightness(rgb: Sequence[int]) -> float:
    return (max(rgb) + min(rgb)) / 2 / 255


_HEX_COLOR_RE = re.compile(r"#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")


def hex_to_rgb(hx: str) -> tuple[int, int, int]:
    if not _HEX_COLOR_RE.match(hx):
        raise ValueError(f"not a hexadecimal color: {hx!r}")
    digits = hx.removeprefix("#")
    if len(digits) == 3:
        digits = "".join(d * 2 for d in digits)
    red, green, blue = (int(digits[i : i + 2], 16) for i in range(0, 6, 2))
    return red, green, blue


def rgb_to_hex(rgb: Sequence[int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def get_brightness(color: str) -> float:
    red, green, blue = hex_to_rgb(color)
    return (0.299 * red + 0.587 * green + 0.114 * blue) / 255


def get_palette_color(index: int, palette: Sequence[str], *, wrap: bool = False) -> str:
    if wrap:
        if not palette:
            raise ValueError("a color palette cannot be empty")
        index %= len(palette)
    if not 0 <= index < len(palette):
        raise IndexError(index)
    return palette[index]


def get_hsl_from_seed(seed: str) -> str:
    hashed_seed = sha512(seed.encode()).hexdigest()
    hue = int(hashed_seed[0:2], 16) * 360 / 255
    sat = int(hashed_seed[2:4], 16) * ((70 - 40) / 255) + 40
    lig = 45
    return f"hsl({hue:.0f}, {sat:.0f}%, {lig:.0f}%)"


def lighten_hex(color: str, factor: float) -> str:
    """Blend an RGB hex color toward white, clamping the factor to [0, 1]."""
    factor = max(0.0, min(factor, 1.0))
    return rgb_to_hex(
        tuple(
            round(channel + (255 - channel) * factor) for channel in hex_to_rgb(color)
        )
    )
