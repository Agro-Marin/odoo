import base64
import re

from odoo.tests import TransactionCase, tagged

# WCAG 2.2 SC 1.4.3 (text) and SC 1.4.11 (non-text / focus indicators).
WCAG_AA_TEXT = 4.5
WCAG_NON_TEXT = 3.0


def _relative_luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(component) for component in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(fg, bg):
    lighter, darker = sorted(
        (_relative_luminance(fg), _relative_luminance(bg)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _parse_color(css_value):
    """Parse `#rgb`, `#rrggbb` and `rgb()`/`rgba()` into ((r, g, b), alpha)."""
    css_value = css_value.strip()
    hex_match = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", css_value)
    if hex_match:
        digits = hex_match.group(1)
        if len(digits) == 3:
            digits = "".join(d * 2 for d in digits)
        return [int(digits[i : i + 2], 16) for i in (0, 2, 4)], 1.0
    fn_match = re.fullmatch(r"rgba?\(([^)]*)\)", css_value, re.IGNORECASE)
    if not fn_match:
        raise ValueError(f"not a colour: {css_value!r}")
    numbers = [float(n) for n in re.findall(r"-?[\d.]+", fn_match.group(1))]
    if len(numbers) < 3:
        raise ValueError(f"not a colour: {css_value!r}")
    return numbers[:3], (numbers[3] if len(numbers) > 3 else 1.0)


def _composite(fg, alpha, bg):
    return [alpha * f + (1 - alpha) * b for f, b in zip(fg, bg, strict=True)]


@tagged("-at_install", "post_install")
class TestScssDesignSystem(TransactionCase):
    """Invariants of the compiled backend stylesheet.

    These guard regressions that are invisible in the SCSS sources and only show
    up in the compiled bundle or in the browser's cascade.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = cls._compiled("web.assets_backend")

    @classmethod
    def _compiled(cls, bundle_name):
        """Compile a bundle and return its CSS."""
        cls.env["ir.qweb"]._get_asset_bundle(bundle_name, css=True, js=False).css()
        attachment = cls.env["ir.attachment"].search(
            [("url", "=like", f"/web/assets/%/{bundle_name}%.css")], limit=1
        )
        if not attachment:
            raise AssertionError(f"{bundle_name} produced no CSS attachment")
        return base64.b64decode(attachment.datas).decode()

    def _rules(self, selector):
        """Bodies of every rule whose (possibly grouped) selector list holds `selector`."""
        pattern = r"(?:^|[}\s;])([^{}@]*" + re.escape(selector) + r"[^{}]*)\{([^}]*)\}"
        return [body for _, body in re.findall(pattern, self.css, re.MULTILINE)]

    def _rule(self, selector, containing=None):
        """Body of the last matching rule, optionally the last one declaring `containing`."""
        bodies = [
            b for b in self._rules(selector) if containing is None or containing in b
        ]
        self.assertTrue(
            bodies, f"no rule found for {selector} (containing {containing!r})"
        )
        return bodies[-1]

    def _page_background(self):
        """First `--body-bg` in the bundle: light mode, emitted before the dark override."""
        match = re.search(r"--body-bg:\s*([^;}]+)", self.css)
        self.assertTrue(match, "--body-bg is not defined")
        return _parse_color(match.group(1))[0]

    def test_opacity_vars_do_not_inherit(self):
        """`--bg-opacity` / `--text-opacity` must be registered non-inheriting.

        They are set by utilities such as `.bg-transparent` (`--bg-opacity: 0`).
        Because `o-print-color()` reads them through `var(--bg-opacity, 1)`, an
        inherited value silently erases the background/colour of every nested
        `.bg-*` / `.text-*` element: the `var()` fallback only applies when the
        property is unset, and an inherited `0` counts as set.
        """
        for name in ("--bg-opacity", "--text-opacity"):
            match = re.search(r"@property\s*" + name + r"\s*\{([^}]*)\}", self.css)
            self.assertTrue(match, f"@property {name} is not declared")
            self.assertIn("inherits:false", match.group(1).replace(" ", ""))

    def test_text_utilities_meet_wcag_aa(self):
        """Semantic text colours must be readable on the webclient background."""
        background = self._page_background()
        failures = []
        for name in ("primary", "success", "info", "warning", "danger"):
            declaration = self._rule(f".text-{name}", containing="--color:")
            colour = re.search(
                r"--color:\s*(RGBA?\([^)]*\))", declaration, re.IGNORECASE
            )
            self.assertTrue(colour, f".text-{name} has no --color declaration")
            rgb, alpha = _parse_color(colour.group(1))
            ratio = _contrast_ratio(_composite(rgb, alpha, background), background)
            if ratio < WCAG_AA_TEXT:
                failures.append(f".text-{name}: {ratio:.2f}:1")
        self.assertFalse(
            failures, f"below WCAG AA ({WCAG_AA_TEXT}:1): {', '.join(failures)}"
        )

    def test_text_bg_pairs_meet_wcag_aa(self):
        """`.text-bg-*` ships a foreground and a background together, so the pair
        it ships must be legible on its own.

        Bootstrap picks the foreground with `color-contrast()`, which returns the
        first candidate over `$min-contrast-ratio`. That global is 3 here, so the
        pair can ship at ~3.7:1; `.text-bg-*` overrides it to the AA text
        threshold instead.
        """
        failures = []
        for name in (
            "primary",
            "secondary",
            "success",
            "info",
            "warning",
            "danger",
            "light",
            "dark",
        ):
            body = self._rule(f".text-bg-{name}", containing="--color:")
            fg = re.search(r"--color:\s*(RGBA?\([^)]*\))", body, re.IGNORECASE)
            self.assertTrue(fg, f".text-bg-{name} declares no foreground")
            # Bootstrap paints the surface as RGBA(var(--<name>-rgb), …).
            channels = re.search(rf"--{name}-rgb:\s*([\d\s,]+)", self.css)
            self.assertTrue(channels, f"--{name}-rgb is not defined")
            surface = [float(c) for c in channels.group(1).split(",")]
            fg_rgb, fg_alpha = _parse_color(fg.group(1))
            ratio = _contrast_ratio(_composite(fg_rgb, fg_alpha, surface), surface)
            if ratio < WCAG_AA_TEXT:
                failures.append(f".text-bg-{name}: {ratio:.2f}:1")
        self.assertFalse(
            failures, f"below WCAG AA ({WCAG_AA_TEXT}:1): {', '.join(failures)}"
        )

    def test_focus_ring_is_opaque_and_visible(self):
        """The focus outline must clear 3:1 against the page it is drawn on.

        A translucent ring composites towards the background and drops below the
        threshold, which is what `rgba($o-brand-primary, .5)` used to do.
        """
        background = self._page_background()
        outline = re.search(
            r"outline:\s*[\d.]+px\s+solid\s+(rgba?\([^)]*\)|#[0-9a-fA-F]{3,6})",
            self._rule("a:focus-visible"),
            re.IGNORECASE,
        )
        self.assertTrue(outline, "no focus outline colour found")
        rgb, alpha = _parse_color(outline.group(1))
        self.assertEqual(alpha, 1.0, "focus ring colour must be opaque")
        ratio = _contrast_ratio(_composite(rgb, alpha, background), background)
        self.assertGreaterEqual(
            ratio, WCAG_NON_TEXT, f"focus ring contrast {ratio:.2f}:1"
        )

    def test_no_cascade_layers(self):
        """The bundle is unlayered; a stray `@layer` silently reorders everything.

        Normal declarations inside a layer lose to every unlayered rule whatever
        their specificity, and `!important` ones win over every unlayered
        `!important` — so a single wrapped block changes the cascade globally.
        """
        layers = set(re.findall(r"@layer\s+([\w-]+)", self.css))
        self.assertFalse(layers, f"unexpected cascade layer(s): {sorted(layers)}")

    def test_color_scheme_values_are_recognised(self):
        """`color-scheme` only acts on a fixed keyword set.

        Anything else parses as a `<custom-ident>`, so it neither errors nor
        applies - the declaration silently degrades to `normal`. The print
        bundle shipped `bright` that way.
        """
        allowed = {"normal", "light", "dark", "only light", "only dark", "light dark"}
        # The print bundle carries its own palette and is where `bright` shipped,
        # so checking only the backend would leave this guard vacuous.
        for bundle in ("web.assets_backend", "web.assets_web_print"):
            css = self.css if bundle == "web.assets_backend" else self._compiled(bundle)
            declared = {
                value.strip()
                for value in re.findall(r"[;{]color-scheme:\s*([^;}]+)", css)
            }
            self.assertTrue(declared, f"{bundle}: no color-scheme declaration")
            self.assertFalse(
                declared - allowed,
                f"{bundle}: unrecognised color-scheme {sorted(declared - allowed)}",
            )

    def _keyframes(self):
        """(name, body) for every `@keyframes`, brace-matched so it works minified."""
        blocks = []
        for match in re.finditer(r"@keyframes\s+([\w-]+)\s*\{", self.css):
            depth, index = 0, match.end() - 1
            while index < len(self.css):
                if self.css[index] == "{":
                    depth += 1
                elif self.css[index] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            blocks.append((match.group(1), self.css[match.end() : index]))
        return blocks

    def test_keyframes_use_animation_timing_function(self):
        """`transition-timing-function` inside `@keyframes` is inert."""
        keyframes = self._keyframes()
        self.assertTrue(keyframes, "no @keyframes parsed - the matcher is broken")
        offenders = [n for n, body in keyframes if "transition-timing-function" in body]
        self.assertFalse(
            offenders, f"@keyframes using transition-timing-function: {offenders}"
        )

    def test_odoo_keyframes_are_namespaced(self):
        """Odoo-owned keyframes carry an `o-`/`o_` prefix.

        The bundle is shared with website themes and third-party CSS, where bare
        names like `pulse`, `flash` or `bounceIn` collide.
        """
        known_foreign = (
            "fa-",
            "bs-",
            "progress-bar-stripes",
            "placeholder-glow",
            "placeholder-wave",
        )
        names = set(re.findall(r"@keyframes\s+([\w-]+)", self.css))
        unprefixed = sorted(
            n
            for n in names
            if not n.startswith(("o-", "o_")) and not n.startswith(known_foreign)
        )
        self.assertNotIn("pulse", unprefixed)
        self.assertNotIn("flash", unprefixed)
        self.assertNotIn("bounceIn", unprefixed)
