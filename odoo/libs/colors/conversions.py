"""Color conversion helpers between RGB, hexadecimal and HSL representations."""

import re
from hashlib import sha512
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def get_saturation(rgb: Sequence[int]) -> float:
    """Return the saturation (HSL format) of a given RGB color.

    :param rgb: RGB tuple or list with values 0-255
    :returns: Saturation value between 0 and 1

    Example::

        >>> get_saturation((255, 0, 0))  # Pure red
        1.0
        >>> get_saturation((128, 128, 128))  # Gray
        0.0
    """
    c_max = max(rgb) / 255
    c_min = min(rgb) / 255
    d = c_max - c_min
    # 0.0 (not 0) so the achromatic path matches the declared float return type
    return 0.0 if d == 0 else d / (1 - abs(c_max + c_min - 1))


def get_lightness(rgb: Sequence[int]) -> float:
    """Return the lightness (HSL format) of a given RGB color.

    :param rgb: RGB tuple or list with values 0-255
    :returns: Lightness value between 0 and 1

    Example::

        >>> get_lightness((255, 255, 255))  # White
        1.0
        >>> get_lightness((0, 0, 0))  # Black
        0.0
        >>> get_lightness((128, 128, 128))  # Middle gray
        0.5019607843137255
    """
    return (max(rgb) + min(rgb)) / 2 / 255


_HEX_COLOR_RE = re.compile(
    r"#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z"
)


def hex_to_rgb(hx: str) -> tuple[int, int, int]:
    """Convert a hexadecimal color string to an RGB tuple.

    Accepts the CSS forms ``#rgb``, ``#rrggbb`` and their alpha variants
    (``#rgba`` / ``#rrggbbaa``, alpha ignored); the leading ``#`` is optional.

    :param hx: Hexadecimal color string (e.g., '#FF0000')
    :returns: RGB tuple with values 0-255
    :raises ValueError: if ``hx`` is not a hexadecimal color

    Example::

        >>> hex_to_rgb('#FF0000')
        (255, 0, 0)
        >>> hex_to_rgb('#00FF00')
        (0, 255, 0)
        >>> hex_to_rgb('#f00')
        (255, 0, 0)
        >>> hex_to_rgb('FF0000')
        (255, 0, 0)
        >>> hex_to_rgb('nope')
        Traceback (most recent call last):
        ...
        ValueError: not a hexadecimal color: 'nope'
    """
    # Slicing blindly from index 1 assumed a leading "#" and validated nothing:
    # 'FF0000' silently read the digits one position off and returned
    # (240, 0, 0), and a 3-digit shorthand crashed with a bare
    # "invalid literal for int()".
    if not _HEX_COLOR_RE.match(hx):
        raise ValueError(f"not a hexadecimal color: {hx!r}")
    digits = hx.removeprefix("#")
    if len(digits) <= 4:  # shorthand: each digit is doubled
        digits = "".join(d * 2 for d in digits)
    return tuple(int(digits[i : i + 2], 16) for i in range(0, 6, 2))  # type: ignore[return-value]


def rgb_to_hex(rgb: Sequence[int]) -> str:
    """Convert an RGB tuple or list to a hexadecimal color string.

    :param rgb: RGB tuple or list with values 0-255
    :returns: Hexadecimal color string starting with '#'

    Example::

        >>> rgb_to_hex((255, 0, 0))
        '#ff0000'
        >>> rgb_to_hex((0, 255, 0))
        '#00ff00'
    """
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def hsl_from_seed(seed: str) -> str:
    """Generate a deterministic HSL color string from a seed string.

    Hashes the seed with SHA-512 and derives hue, saturation, and lightness
    values. The result is colorful but not too flashy, and not too bright or
    dark — suitable for avatar background colors.

    :param seed: Arbitrary string used to generate the color
    :returns: HSL color string, e.g. ``'hsl(214, 55%, 45%)'``

    Example::

        >>> hsl_from_seed('Alice')  # deterministic
        'hsl(58, 57%, 45%)'
    """
    hashed_seed = sha512(seed.encode()).hexdigest()
    # full range of colors, in degree
    hue = int(hashed_seed[0:2], 16) * 360 / 255
    # colorful result but not too flashy, in percent
    sat = int(hashed_seed[2:4], 16) * ((70 - 40) / 255) + 40
    # not too bright and not too dark, in percent
    lig = 45
    return f"hsl({hue:.0f}, {sat:.0f}%, {lig:.0f}%)"
