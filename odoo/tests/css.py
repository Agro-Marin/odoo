import ast
import operator
import re

SOURCE_MARK_RE = re.compile(r"/\*\s*(/[^*]+?)\s*\*/")

DARK_SELECTOR_RE = re.compile(r':root\[data-color-scheme="?dark"?\]')

DARK_SCOPE_RE = re.compile(r'(?:^|(?<= )):root\[data-color-scheme="?dark"?\] +')

COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^()]*\)")

_KEYWORDS = {
    "white": "#ffffff",
    "black": "#000000",
    "#000": "#000000",
    "#fff": "#ffffff",
}


def parse(css):
    stack: list[str] = []
    out, buf, source = [], "", "?"
    index, end = 0, len(css)

    def flush():
        nonlocal buf
        declaration, buf = buf.strip(), ""
        if ":" in declaration and stack:
            prop, _, value = declaration.partition(":")
            out.append((source, " ".join(stack), prop.strip(), value.strip()))

    while index < end:
        char = css[index]
        if char == "/" and css[index + 1 : index + 2] == "*":
            close = css.find("*/", index + 2)
            close = end if close < 0 else close + 2
            mark = SOURCE_MARK_RE.fullmatch(css[index:close])
            if mark and not stack:
                source = mark.group(1)
            index = close
            continue
        if char in "\"'":
            close = index + 1
            while close < end and css[close] != char:
                close += 2 if css[close] == "\\" else 1
            buf += css[index : close + 1]
            index = close + 1
            continue
        if char == "{":
            stack.append(buf.strip())
            buf = ""
        elif char == "}":
            flush()
            if stack:
                stack.pop()
        elif char == ";":
            flush()
        else:
            buf += char
        index += 1
    return out


def split_selector(selector):
    parts, depth, current = [], 0, ""
    for char in selector:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and not depth:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def is_root(selector):
    return ":root" in split_selector(selector)


def unreachable(selector):
    parts = split_selector(selector)
    return bool(parts) and all("[data-bs-theme=" in part for part in parts)


ROOT = "\x00:root"


def settle(declarations):
    keep, order = {}, []
    for source, selector, prop, value in declarations:
        key = (
            (ROOT, prop)
            if prop.startswith("--") and is_root(selector)
            else (selector, prop)
        )
        if key not in keep:
            order.append(key)
        keep[key] = (source, value)
    return [(keep[key][0], key[0], key[1], keep[key][1]) for key in order]


def resolve(value, scope, depth=0):
    if depth > 12:
        return value
    out, index, changed = "", 0, False
    while True:
        start = value.find("var(", index)
        if start < 0 or (
            start and (value[start - 1].isalnum() or value[start - 1] in "-_")
        ):
            if start < 0:
                out += value[index:]
                break
            out += value[index : start + 4]
            index = start + 4
            continue
        end = _closing(value, start + 3)
        if end < 0:
            out += value[index:]
            break
        inner = value[start + 4 : end]
        name, _, fallback = inner.partition(",")
        name = name.strip()
        if name in scope:
            replacement = resolve(scope[name], scope, depth + 1)
        elif fallback.strip():
            replacement = resolve(fallback.strip(), scope, depth + 1)
        else:
            replacement = value[start : end + 1]
        changed = changed or replacement != value[start : end + 1]
        out += value[index:start] + replacement
        index = end + 1
    return out if not changed else resolve(out, scope, depth + 1)


def pick_dark(value):
    while True:
        start = value.lower().find("light-dark(")
        if start < 0:
            return value
        depth, index = 0, start + len("light-dark(") - 1
        while index < len(value):
            if value[index] == "(":
                depth += 1
            elif value[index] == ")":
                depth -= 1
                if not depth:
                    break
            index += 1
        inner = value[start + len("light-dark(") : index]
        halves = split_selector(inner)
        if len(halves) != 2:
            return value
        value = value[:start] + pick_dark(halves[1]) + value[index + 1 :]


def is_mask(prop):
    return bool(re.fullmatch(r"(?:-webkit-)?mask(?:-image)?", prop.strip().lower()))


def flatten_opaque(value):
    return COLOR_RE.sub(
        lambda match: "#000000" if _is_opaque(match.group(0)) else match.group(0),
        value,
    )


def _is_opaque(literal):
    literal = norm(literal)
    if literal.startswith("#"):
        return len(literal) == 7
    parts = literal[len("rgb(") : -1].split(",") if literal.startswith("rgb(") else []
    return len(parts) == 3


def norm(value):
    value = re.sub(r"\s+", " ", (value or "").strip().lower())
    value = re.sub(r"(?<![\w.])\.(\d)", r"0.\1", value)
    return canonical_colours(_KEYWORDS.get(value, value))


# A colour is compared by what it paints, not how it is spelled: a token
# rewrite turns `mix()` or `rgba($x, .1)` into color-mix(), rgb(from ...) or
# hsl(...), and the dark bundle serves the literal Sass computed.
_COLOUR_FUNCTIONS = ("rgba", "rgb", "hsla", "hsl", "color-mix")
_NAMED_HEX = {
    "aliceblue": "f0f8ff",
    "antiquewhite": "faebd7",
    "aqua": "00ffff",
    "aquamarine": "7fffd4",
    "azure": "f0ffff",
    "beige": "f5f5dc",
    "bisque": "ffe4c4",
    "black": "000000",
    "blanchedalmond": "ffebcd",
    "blue": "0000ff",
    "blueviolet": "8a2be2",
    "brown": "a52a2a",
    "burlywood": "deb887",
    "cadetblue": "5f9ea0",
    "chartreuse": "7fff00",
    "chocolate": "d2691e",
    "coral": "ff7f50",
    "cornflowerblue": "6495ed",
    "cornsilk": "fff8dc",
    "crimson": "dc143c",
    "cyan": "00ffff",
    "darkblue": "00008b",
    "darkcyan": "008b8b",
    "darkgoldenrod": "b8860b",
    "darkgray": "a9a9a9",
    "darkgreen": "006400",
    "darkgrey": "a9a9a9",
    "darkkhaki": "bdb76b",
    "darkmagenta": "8b008b",
    "darkolivegreen": "556b2f",
    "darkorange": "ff8c00",
    "darkorchid": "9932cc",
    "darkred": "8b0000",
    "darksalmon": "e9967a",
    "darkseagreen": "8fbc8f",
    "darkslateblue": "483d8b",
    "darkslategray": "2f4f4f",
    "darkslategrey": "2f4f4f",
    "darkturquoise": "00ced1",
    "darkviolet": "9400d3",
    "deeppink": "ff1493",
    "deepskyblue": "00bfff",
    "dimgray": "696969",
    "dimgrey": "696969",
    "dodgerblue": "1e90ff",
    "firebrick": "b22222",
    "floralwhite": "fffaf0",
    "forestgreen": "228b22",
    "fuchsia": "ff00ff",
    "gainsboro": "dcdcdc",
    "ghostwhite": "f8f8ff",
    "gold": "ffd700",
    "goldenrod": "daa520",
    "gray": "808080",
    "green": "008000",
    "greenyellow": "adff2f",
    "grey": "808080",
    "honeydew": "f0fff0",
    "hotpink": "ff69b4",
    "indianred": "cd5c5c",
    "indigo": "4b0082",
    "ivory": "fffff0",
    "khaki": "f0e68c",
    "lavender": "e6e6fa",
    "lavenderblush": "fff0f5",
    "lawngreen": "7cfc00",
    "lemonchiffon": "fffacd",
    "lightblue": "add8e6",
    "lightcoral": "f08080",
    "lightcyan": "e0ffff",
    "lightgoldenrodyellow": "fafad2",
    "lightgray": "d3d3d3",
    "lightgreen": "90ee90",
    "lightgrey": "d3d3d3",
    "lightpink": "ffb6c1",
    "lightsalmon": "ffa07a",
    "lightseagreen": "20b2aa",
    "lightskyblue": "87cefa",
    "lightslategray": "778899",
    "lightslategrey": "778899",
    "lightsteelblue": "b0c4de",
    "lightyellow": "ffffe0",
    "lime": "00ff00",
    "limegreen": "32cd32",
    "linen": "faf0e6",
    "magenta": "ff00ff",
    "maroon": "800000",
    "mediumaquamarine": "66cdaa",
    "mediumblue": "0000cd",
    "mediumorchid": "ba55d3",
    "mediumpurple": "9370db",
    "mediumseagreen": "3cb371",
    "mediumslateblue": "7b68ee",
    "mediumspringgreen": "00fa9a",
    "mediumturquoise": "48d1cc",
    "mediumvioletred": "c71585",
    "midnightblue": "191970",
    "mintcream": "f5fffa",
    "mistyrose": "ffe4e1",
    "moccasin": "ffe4b5",
    "navajowhite": "ffdead",
    "navy": "000080",
    "oldlace": "fdf5e6",
    "olive": "808000",
    "olivedrab": "6b8e23",
    "orange": "ffa500",
    "orangered": "ff4500",
    "orchid": "da70d6",
    "palegoldenrod": "eee8aa",
    "palegreen": "98fb98",
    "paleturquoise": "afeeee",
    "palevioletred": "db7093",
    "papayawhip": "ffefd5",
    "peachpuff": "ffdab9",
    "peru": "cd853f",
    "pink": "ffc0cb",
    "plum": "dda0dd",
    "powderblue": "b0e0e6",
    "purple": "800080",
    "rebeccapurple": "663399",
    "red": "ff0000",
    "rosybrown": "bc8f8f",
    "royalblue": "4169e1",
    "saddlebrown": "8b4513",
    "salmon": "fa8072",
    "sandybrown": "f4a460",
    "seagreen": "2e8b57",
    "seashell": "fff5ee",
    "sienna": "a0522d",
    "silver": "c0c0c0",
    "skyblue": "87ceeb",
    "slateblue": "6a5acd",
    "slategray": "708090",
    "slategrey": "708090",
    "snow": "fffafa",
    "springgreen": "00ff7f",
    "steelblue": "4682b4",
    "tan": "d2b48c",
    "teal": "008080",
    "thistle": "d8bfd8",
    "tomato": "ff6347",
    "turquoise": "40e0d0",
    "violet": "ee82ee",
    "wheat": "f5deb3",
    "white": "ffffff",
    "whitesmoke": "f5f5f5",
    "yellow": "ffff00",
    "yellowgreen": "9acd32",
}
_NAMED = {
    name: (
        float(int(code[0:2], 16)),
        float(int(code[2:4], 16)),
        float(int(code[4:6], 16)),
        1.0,
    )
    for name, code in _NAMED_HEX.items()
}
_NAMED["transparent"] = (0.0, 0.0, 0.0, 0.0)
_HEX_RE = re.compile(r"#([0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})\b")


def _closing(value, open_index):
    depth = 0
    for index in range(open_index, len(value)):
        if value[index] == "(":
            depth += 1
        elif value[index] == ")":
            depth -= 1
            if not depth:
                return index
    return -1


def _split_top(text, separators):
    parts, depth, current = [], 0, ""
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char in separators and not depth:
            parts.append(current.strip())
            current = ""
            continue
        current += char
    parts.append(current.strip())
    return [part for part in parts if part]


_ARITHMETIC = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _arithmetic(node):
    if isinstance(node, ast.Expression):
        return _arithmetic(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_arithmetic(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC:
        return _ARITHMETIC[type(node.op)](
            _arithmetic(node.left), _arithmetic(node.right)
        )
    raise ValueError(ast.dump(node))


def _calc(expression, channels):
    text = expression.strip()
    if text.startswith("calc(") and text.endswith(")"):
        text = text[len("calc(") : -1]
    for name, number in sorted(channels.items(), key=lambda item: -len(item[0])):
        text = re.sub(rf"\b{name}\b", repr(number), text)
    text = re.sub(r"(\d(?:\.\d+)?)(?:%|deg)", r"\1", text)
    return _arithmetic(ast.parse(text, mode="eval"))


def _number(token, scale=1.0):
    token = token.strip()
    if token.startswith("calc("):
        return _calc(token, {})
    if token.endswith("%"):
        return float(token[:-1]) * scale / 100
    return float(token)


def _hsl_to_rgb(hue, saturation, lightness):
    hue, saturation, lightness = hue % 360, saturation / 100, lightness / 100

    def channel(n):
        k = (n + hue / 30) % 12
        a = saturation * min(lightness, 1 - lightness)
        return 255 * (lightness - a * max(-1, min(k - 3, 9 - k, 1)))

    return channel(0), channel(8), channel(4)


def _rgb_to_hsl(red, green, blue):
    red, green, blue = red / 255, green / 255, blue / 255
    high, low = max(red, green, blue), min(red, green, blue)
    lightness = (high + low) / 2
    if high == low:
        return 0.0, 0.0, lightness * 100
    delta = high - low
    saturation = delta / (1 - abs(2 * lightness - 1))
    if high == red:
        hue = 60 * (((green - blue) / delta) % 6)
    elif high == green:
        hue = 60 * ((blue - red) / delta + 2)
    else:
        hue = 60 * ((red - green) / delta + 4)
    return hue, saturation * 100, lightness * 100


def _parse_colour(text):
    text = text.strip()
    if text in _NAMED:
        return _NAMED[text]
    match = _HEX_RE.fullmatch(text)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            digits = "".join(char * 2 for char in digits)
        values = [int(digits[i : i + 2], 16) for i in range(0, len(digits), 2)]
        alpha = values[3] / 255 if len(values) == 4 else 1.0
        return float(values[0]), float(values[1]), float(values[2]), alpha
    open_index = text.find("(")
    if open_index < 0 or _closing(text, open_index) != len(text) - 1:
        raise ValueError(text)
    name, inner = text[:open_index], text[open_index + 1 : -1]
    if name == "color-mix":
        return _parse_mix(inner)
    if name not in ("rgb", "rgba", "hsl", "hsla"):
        raise ValueError(text)
    if inner.startswith("from "):
        return _parse_relative(name, inner[len("from ") :])
    head, _, alpha = inner.partition("/")
    parts = _split_top(head, ", ")
    if len(parts) == 4 and not alpha:
        parts, alpha = parts[:3], parts[3]
    if len(parts) != 3:
        raise ValueError(text)
    opacity = _number(alpha, 1.0) if alpha.strip() else 1.0
    if name.startswith("rgb"):
        return (*(_number(part, 255.0) for part in parts), opacity)
    hue = float(parts[0].removesuffix("deg"))
    return (*_hsl_to_rgb(hue, _number(parts[1], 100), _number(parts[2], 100)), opacity)


def _parse_relative(name, inner):
    head, _, alpha = inner.partition("/")
    parts = _split_top(head, " ")
    origin = _parse_colour(parts[0])
    red, green, blue, opacity = origin
    if name.startswith("rgb"):
        channels = {"r": red, "g": green, "b": blue, "alpha": opacity}
        values = [_calc(part, channels) for part in parts[1:4]]
        result = tuple(values)
    else:
        hue, saturation, lightness = _rgb_to_hsl(red, green, blue)
        channels = {
            "h": hue,
            "s": saturation,
            "l": lightness,
            "alpha": opacity,
        }
        values = [_calc(part, channels) for part in parts[1:4]]
        result = _hsl_to_rgb(*values)
    if alpha.strip():
        opacity = _calc(alpha, {"alpha": opacity})
    return (*result, opacity)


def _parse_mix(inner):
    parts = _split_top(inner, ",")
    if len(parts) != 3 or parts[0].replace(" ", "") != "insrgb":
        raise ValueError(inner)
    colours = []
    weights: list[float | None] = []
    for part in parts[1:]:
        match = re.fullmatch(r"(.*?)(?:\s+([\d.]+)%)?", part.strip())
        if match is None:
            raise ValueError(inner)
        colours.append(_parse_colour(match.group(1)))
        weights.append(float(match.group(2)) if match.group(2) else None)
    first_weight, second_weight = weights
    if first_weight is None:
        first_weight = 50.0 if second_weight is None else 100 - second_weight
    if second_weight is None:
        second_weight = 100 - first_weight
    first, second = first_weight, second_weight
    total = first + second
    if not total:
        raise ValueError(inner)
    first, second = first / total, second / total
    (r1, g1, b1, a1), (r2, g2, b2, a2) = colours
    alpha = a1 * first + a2 * second
    if alpha:
        mixed = [
            (c1 * a1 * first + c2 * a2 * second) / alpha
            for c1, c2 in ((r1, r2), (g1, g2), (b1, b2))
        ]
    else:
        mixed = [0.0, 0.0, 0.0]
    return (*mixed, alpha * min(total, 100) / 100)


def _format_colour(red, green, blue, alpha):
    # what reaches the screen: 8-bit channels, so Sass's and the browser's
    # arithmetic agree once rounded the way the paint rounds them
    if round(alpha, 2) == 0:
        return "rgb(0,0,0,0)"
    parts = [str(round(channel)) for channel in (red, green, blue)]
    if round(alpha, 2) != 1:
        parts.append(f"{round(alpha, 2):g}")
    return "rgb(" + ",".join(parts) + ")"


def canonical_colours(value):
    out, index = "", 0
    while index < len(value):
        matched = False
        for name in _COLOUR_FUNCTIONS:
            if value.startswith(name + "(", index) and (
                index == 0
                or not (value[index - 1].isalnum() or value[index - 1] in "-_")
            ):
                end = _closing(value, index + len(name))
                if end < 0:
                    break
                text = value[index : end + 1]
                try:
                    out += _format_colour(*_parse_colour(text))
                except ValueError, ZeroDivisionError, SyntaxError:
                    out += text
                index = end + 1
                matched = True
                break
        if matched:
            continue
        match = _HEX_RE.match(value, index)
        if match and (index == 0 or not value[index - 1].isalnum()):
            out += _format_colour(*_parse_colour(match.group(0)))
            index = match.end()
            continue
        word = re.match(r"[a-z]+", value[index:])
        if (
            word
            and word.group(0) in _NAMED
            and (
                index == 0
                or not (value[index - 1].isalnum() or value[index - 1] in "-_")
            )
        ):
            end = index + len(word.group(0))
            if end == len(value) or not (value[end].isalnum() or value[end] in "-_("):
                out += _format_colour(*_NAMED[word.group(0)])
                index = end
                continue
        out += value[index]
        index += 1
    return out


_CANONICAL_RE = re.compile(r"rgb\((\d+),(\d+),(\d+)((?:,[0-9.]+)?)\)")


def same_paint(left, right):
    # Sass and the browser can land on either side of a .5 channel -- darken()
    # of #ff453a is exactly 236.5 red -- so one 8-bit step is the same paint
    if left == right:
        return True
    if _CANONICAL_RE.sub("rgb()", left) != _CANONICAL_RE.sub("rgb()", right):
        return False
    pairs = zip(
        _CANONICAL_RE.finditer(left), _CANONICAL_RE.finditer(right), strict=True
    )
    return all(
        a.group(4) == b.group(4)
        and all(abs(int(a.group(i)) - int(b.group(i))) <= 1 for i in (1, 2, 3))
        for a, b in pairs
    )


def unscoped(part):
    if DARK_SELECTOR_RE.fullmatch(part.strip()):
        return ":root"
    return DARK_SCOPE_RE.sub("", part)


def parse_colour(text):
    return _parse_colour(norm(text))


def composite(foreground, background):
    red, green, blue, alpha = foreground
    return tuple(
        alpha * channel + (1 - alpha) * under
        for channel, under in zip((red, green, blue), background[:3], strict=True)
    )


def _relative_luminance(rgb):
    def linear(channel):
        channel /= 255
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground, background):
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def scheme_scopes(css):
    declarations = settle(parse(css))
    light = {
        prop: value for _, selector, prop, value in declarations if selector == ROOT
    }
    dark = dict(light)
    dark.update(
        {
            prop: value
            for _, selector, prop, value in declarations
            if DARK_SELECTOR_RE.fullmatch(selector.strip())
        }
    )
    return light, dark


def token_colour(name, scope, *, dark):
    value = resolve(scope[name], scope)
    return parse_colour(pick_dark(value) if dark else value)
