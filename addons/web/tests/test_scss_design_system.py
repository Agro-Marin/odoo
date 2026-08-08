import base64
import re
from itertools import pairwise

from odoo.tests import TransactionCase, tagged

# The dark scheme is a bundle of its own, not a media query inside the light one,
# so anything asserted about colour has to be asserted against it separately.
DARK_BUNDLE = "web.assets_web_dark"

# WCAG 2.2 SC 1.4.3 (text) and SC 1.4.11 (non-text / focus indicators).
WCAG_AA_TEXT = 4.5
WCAG_NON_TEXT = 3.0

# The list view's column header, spelled out rather than matched on the `thead`
# tag: any installed addon may style a `thead` of its own, and the last such
# rule won — `web_cohort`'s, which declares only a background.
LIST_HEADER = ".o_list_renderer .o_list_table thead th"


#: Viewport RFS interpolates up to. Bootstrap builds `calc(<rem> + <vw>)` so the
#: pair resolves to exactly the requested size here, which makes the declared
#: ramp recoverable from the compiled bundle without re-deriving `$rfs-factor`.
RFS_REFERENCE_WIDTH = 1200
ROOT_FONT_SIZE = 16


def _font_size_px(css_value):
    """Resolve a heading `font-size` to px, plain `rem` or RFS `calc()` alike."""
    css_value = css_value.strip()
    calc = re.fullmatch(r"calc\(\s*([\d.]+)rem\s*\+\s*([\d.]+)vw\s*\)", css_value)
    if calc:
        rem, vw = (float(g) for g in calc.groups())
        return rem * ROOT_FONT_SIZE + vw * RFS_REFERENCE_WIDTH / 100
    rem = re.fullmatch(r"([\d.]+)rem", css_value)
    if not rem:
        raise ValueError(f"not a font size: {css_value!r}")
    return float(rem.group(1)) * ROOT_FONT_SIZE


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


def _matching_paren(css_value, open_index):
    """Index of the `)` closing the `(` at `open_index`, or -1 if unbalanced."""
    depth = 0
    for index in range(open_index, len(css_value)):
        if css_value[index] == "(":
            depth += 1
        elif css_value[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _top_level_comma(css_value):
    """Index of the first comma outside any parentheses, or -1."""
    depth = 0
    for index, char in enumerate(css_value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            return index
    return -1


def _resolve_var_fallbacks(css_value):
    """Substitute every `var(--x, fallback)` with its fallback.

    The utilities carry their opacity as `RGBA(r, g, b, var(--text-opacity, 1))`
    so a surface can retune it; unset - which `@property … inherits:false`
    guarantees at the top of a cascade - the browser uses the fallback, and that
    is the colour the declaration ships.

    Parsed by balanced scan rather than by regex: a fallback is itself a CSS
    value and may be a function call (`var(--o-text-muted, rgba(51, 65, 85,
    .76))`) or another `var()`. A `[^()]*` fallback pattern matches neither, so
    the token survived unresolved and `_parse_color` rejected the whole
    declaration as "not a colour" - the design system reads as broken when only
    the reader is. A `var(--x)` with no fallback stays verbatim: it resolves to
    nothing here, and keeping the token makes the resulting error name it.
    """
    out = []
    index = 0
    while index < len(css_value):
        if not css_value.startswith("var(", index):
            out.append(css_value[index])
            index += 1
            continue
        end = _matching_paren(css_value, index + 3)
        if end == -1:
            out.append(css_value[index:])
            break
        inner = css_value[index + 4 : end]
        comma = _top_level_comma(inner)
        if comma == -1:
            out.append(css_value[index : end + 1])
        else:
            out.append(_resolve_var_fallbacks(inner[comma + 1 :].strip()))
        index = end + 1
    return "".join(out)


def _parse_color(css_value):
    """Parse `#rgb`, `#rrggbb` and `rgb()`/`rgba()` into ((r, g, b), alpha)."""
    css_value = _resolve_var_fallbacks(css_value.strip())
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


def _declaration(css, prop):
    """Value declared for `prop`, or None. Works on a rule body or a whole bundle.

    Anchored at a declaration boundary because a substring test does not
    distinguish a property from every property ending in it: `color` matches
    `background-color`, which was enough to pick `.o_cohort_view thead` - a rule
    that declares a background and no text colour - as the list header.
    """
    match = re.search(rf"(?:^|[;{{])\s*{re.escape(prop)}\s*:\s*([^;}}]+)", css)
    return match.group(1).strip() if match else None


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

    def _matches(self, selector, css=None):
        """`(selector list, body)` of every rule whose selector list holds `selector`.

        The leading delimiter is a *lookbehind*: consuming it instead meant the
        `}` closing one rule was eaten by that rule's own match, so a rule
        directly abutting it in minified CSS could never start a match. Adjacent
        rules are the norm once minified, and `.btn-primary,.btn-fill-primary{…}`
        - the only one carrying the button's colours - sat right behind another.
        """
        pattern = (
            r"(?:^|(?<=[}\s;]))([^{}@]*" + re.escape(selector) + r"[^{}]*)\{([^}]*)\}"
        )
        haystack = self.css if css is None else css
        return re.findall(pattern, haystack, re.MULTILINE)

    def _rule(self, selector, declaring=None, css=None):
        """Body of the last matching rule, optionally the last one declaring `declaring`.

        "Last" resolves ties the way the cascade does, but only among rules that
        are in the same cascade context. Substring matching answers
        `.text-primary` with every rule whose selector list *mentions* it, and in
        a bundle that carries both schemes the last of those is
        `:root[data-color-scheme=dark] a.text-primary:hover`. Measured against
        the light `--body-bg` it reads 2.17:1, so the gate reported a contrast
        regression the product does not have: a dark-scheme hover tone is not the
        declaration under test.

        So among the candidates that declare what the caller asked for, prefer
        those whose selector list holds `selector` as a whole comma-separated
        part - the base rule, `.text-primary` or `h1,.h1`. Selectors that only
        ever appear compounded keep the looser match, which is why the
        preference is applied after the `declaring` filter and not before it:
        `h1` has a base rule of its own, but the one carrying `letter-spacing`
        groups it with other levels.
        """
        candidates = [
            (selectors, body)
            for selectors, body in self._matches(selector, css=css)
            if declaring is None or _declaration(body, declaring) is not None
        ]
        exact = [
            (selectors, body)
            for selectors, body in candidates
            if any(part.strip() == selector for part in selectors.split(","))
        ]
        bodies = [body for _, body in (exact or candidates)]
        self.assertTrue(
            bodies, f"no rule found for {selector} (declaring {declaring!r})"
        )
        return bodies[-1]

    def _page_background(self):
        """First `--body-bg` in the bundle: light mode, emitted before the dark override."""
        value = _declaration(self.css, "--body-bg")
        self.assertTrue(value, "--body-bg is not defined")
        return _parse_color(value)[0]

    def test_subdued_text_meets_wcag_aa_in_both_schemes(self):
        """Subdued text must reach for the muted token, not a step of the ramp.

        The two palettes do not agree on what a given step means. Light reads
        `$o-gray-500` as a mid grey; dark inverts the ramp, where the same step
        is a divider tone. Every list-view column header and form group title
        took it literally, so they were legible in light (4.55:1) and not in dark
        (2.48:1).

        The list header is the canonical consumer and the one the regression hit,
        so it is what this measures - in both schemes, since checking only the
        light bundle is exactly what missed it.
        """
        failures = []
        for scheme, css in (("light", self.css), ("dark", self._compiled(DARK_BUNDLE))):
            page = _declaration(css, "--body-bg")
            self.assertTrue(page, f"{scheme}: --body-bg is not defined")
            background = _parse_color(page)[0]

            body = self._rule(LIST_HEADER, declaring="color", css=css)
            colour = _declaration(body, "color")
            rgb, alpha = _parse_color(colour)

            ratio = _contrast_ratio(_composite(rgb, alpha, background), background)
            if ratio < WCAG_AA_TEXT:
                failures.append(f"{scheme}: {colour} on {page} = {ratio:.2f}:1")
        self.assertFalse(
            failures, f"below WCAG AA ({WCAG_AA_TEXT}:1): {', '.join(failures)}"
        )

    def test_check_input_boundary_is_perceivable_in_both_schemes(self):
        """An unchecked box is identified by its boundary alone, so it needs 3:1.

        SC 1.4.11 covers "visual information required to identify user interface
        components", which a checkbox border is and a divider is not - but
        Bootstrap points `$form-check-input-border` at `$border-color`, the
        divider tone. Unchecked boxes sat at 1.48:1 in light and 1.26:1 in dark.

        Measured against both surfaces a checkbox actually sits on: the page and
        the view/card behind most forms. In dark the card is the *lighter* of the
        two, so testing only the page background would be the looser check.
        """
        failures = []
        for scheme, css in (("light", self.css), ("dark", self._compiled(DARK_BUNDLE))):
            body = self._rule(".form-check-input", declaring="border", css=css)
            border = re.search(
                r"\bsolid\s+(#[0-9a-fA-F]{3,6}|rgba?\([^)]*\))",
                _declaration(body, "border"),
                re.IGNORECASE,
            )
            self.assertTrue(
                border, f"{scheme}: .form-check-input declares no border colour"
            )
            rgb, alpha = _parse_color(border.group(1))

            for surface in ("--body-bg", "--card-bg"):
                value = _declaration(css, surface)
                self.assertTrue(value, f"{scheme}: {surface} is not defined")
                # `white` and friends are keywords `_parse_color` does not take.
                background = (
                    [255, 255, 255] if value == "white" else _parse_color(value)[0]
                )
                ratio = _contrast_ratio(_composite(rgb, alpha, background), background)
                if ratio < WCAG_NON_TEXT:
                    failures.append(
                        f"{scheme}: {border.group(1)} on {surface} "
                        f"({value}) = {ratio:.2f}:1"
                    )
        self.assertFalse(
            failures, f"below SC 1.4.11 ({WCAG_NON_TEXT}:1): {', '.join(failures)}"
        )

    def _heading_size_px(self, level):
        """Effective px of `h<level>`, read from its own `h_,.h_` rule."""
        match = re.search(
            rf"(?:^|[;}}])h{level},\.h{level}\{{([^}}]*)\}}", self.css, re.MULTILINE
        )
        self.assertTrue(match, f"h{level} declares no rule")
        size = re.search(r"(?:^|;)font-size:\s*([^;}]+)", match.group(1))
        self.assertTrue(size, f"h{level} declares no font-size")
        return _font_size_px(size.group(1))

    def test_heading_scale_is_a_single_ratio(self):
        """Every step of the ramp must be the same visual interval.

        Hand-picked sizes drift: the ramp stepped 1.29, 1.27, 1.15 then 1.09, so
        h4/h5/h6 sat within 1.4px of each other and read as one size while the
        top of the scale carried no weight. A single ratio is what makes the
        levels distinguishable without checking them by eye.
        """
        sizes = [self._heading_size_px(level) for level in range(1, 7)]
        ratios = [big / small for big, small in pairwise(sizes)]

        self.assertAlmostEqual(
            min(ratios),
            max(ratios),
            delta=0.02,
            msg=f"heading ratios drift: {[round(r, 3) for r in ratios]}",
        )

    def test_headings_are_optically_tracked(self):
        """Tracking must tighten as the heading grows, and never loosen.

        Inter is spaced for text sizes, so a display-size heading set at its
        default tracking reads loose. The correction is optical, so what has to
        hold is the direction: no level may be tracked looser than a smaller one.
        """
        tracking = []
        for level in range(1, 7):
            body = self._rule(f"h{level}", declaring="letter-spacing")
            declared = re.search(r"(?:^|;)letter-spacing:\s*(-?[\d.]+)em", body)
            self.assertTrue(declared, f"h{level} declares no em letter-spacing")
            tracking.append(float(declared.group(1)))

        self.assertLess(max(tracking), 0, f"headings are not tracked in: {tracking}")
        self.assertEqual(
            tracking,
            sorted(tracking),
            f"tracking must not loosen as headings grow: {tracking}",
        )

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
            colour = _declaration(
                self._rule(f".text-{name}", declaring="--color"), "--color"
            )
            rgb, alpha = _parse_color(colour)
            ratio = _contrast_ratio(_composite(rgb, alpha, background), background)
            if ratio < WCAG_AA_TEXT:
                failures.append(f".text-{name}: {ratio:.2f}:1")
        self.assertFalse(
            failures, f"below WCAG AA ({WCAG_AA_TEXT}:1): {', '.join(failures)}"
        )

    def test_action_colour_is_readable_as_text(self):
        """`$o-action` is a fill, but `$link-color` and `.text-action` are text.

        The enterprise palette tunes the accent for fills and shipped it straight
        into both, so every link in the webclient rendered at 2.43:1 - the same
        trap `$o-theme-text-colors` exists to avoid for the theme colours, which
        is why the action colour has a text variant of its own.

        Both surfaces matter: links sit on the view background as well as on the
        page background behind it.
        """
        backgrounds = {"page": self._page_background()}
        view = _declaration(self.css, "--o-view-background-color")
        backgrounds["view"] = _parse_color(view)[0] if view else [255, 255, 255]

        link = _declaration(self.css, "--link-color")
        self.assertTrue(link, "--link-color is not defined")
        candidates = {"--link-color": _parse_color(link)}

        action = self._rule(".text-action", declaring="--color")
        candidates[".text-action"] = _parse_color(_declaration(action, "--color"))

        failures = []
        for label, (rgb, alpha) in candidates.items():
            for surface, background in backgrounds.items():
                ratio = _contrast_ratio(_composite(rgb, alpha, background), background)
                if ratio < WCAG_AA_TEXT:
                    failures.append(f"{label} on {surface}: {ratio:.2f}:1")
        self.assertFalse(
            failures, f"below WCAG AA ({WCAG_AA_TEXT}:1): {', '.join(failures)}"
        )

    def test_filled_button_labels_meet_wcag_aa(self):
        """A filled button ships its own label, so the pair must be legible.

        `$o-btns-bs-override` hardcodes the label colour rather than deriving it,
        so a palette is free to pair white text with a fill it does not contrast
        against - the enterprise brand did, at 3.96:1 on the most-used control in
        the product. `$o-brand-primary-filled` exists to keep that pair honest
        while the brand hue itself stays free for surfaces that carry no text.
        """
        failures = []
        for name in ("primary", "secondary"):
            body = self._rule(f".btn-{name}", declaring="--btn-bg")
            fill = _declaration(body, "--btn-bg")
            label = _declaration(body, "--btn-color")
            self.assertTrue(label, f".btn-{name} declares no --btn-color")
            fill_rgb, fill_alpha = _parse_color(fill)
            self.assertEqual(fill_alpha, 1.0, f".btn-{name} fill must be opaque")
            label_rgb, label_alpha = _parse_color(label)
            ratio = _contrast_ratio(
                _composite(label_rgb, label_alpha, fill_rgb), fill_rgb
            )
            if ratio < WCAG_AA_TEXT:
                failures.append(f".btn-{name}: {label} on {fill} = {ratio:.2f}:1")
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
            body = self._rule(f".text-bg-{name}", declaring="--color")
            fg = _declaration(body, "--color")
            # Bootstrap paints the surface as RGBA(var(--<name>-rgb), …).
            channels = _declaration(self.css, f"--{name}-rgb")
            self.assertTrue(channels, f"--{name}-rgb is not defined")
            surface = [float(c) for c in channels.split(",")]
            fg_rgb, fg_alpha = _parse_color(fg)
            ratio = _contrast_ratio(_composite(fg_rgb, fg_alpha, surface), surface)
            if ratio < WCAG_AA_TEXT:
                failures.append(f".text-bg-{name}: {ratio:.2f}:1")
        self.assertFalse(
            failures, f"below WCAG AA ({WCAG_AA_TEXT}:1): {', '.join(failures)}"
        )

    # `o-focus-ring()` emits `var(--o-ring-color, <default>)` so a surface can
    # retune the ring it hosts; the default is what the group captures.
    _RING_COLOUR = (
        r"outline:\s*[\d.]+px\s+solid\s+"
        r"(?:var\(\s*--o-ring-color\s*,\s*)?(rgba?\([^)]*\)|#[0-9a-fA-F]{3,6})"
    )

    def _ring_default(self):
        outline = re.search(
            self._RING_COLOUR, self._rule("a:focus-visible"), re.IGNORECASE
        )
        self.assertTrue(outline, "no focus outline colour found")
        return _parse_color(outline.group(1))

    def test_focus_ring_is_opaque_and_visible(self):
        """The focus outline must clear 3:1 against the page it is drawn on.

        A translucent ring composites towards the background and drops below the
        threshold, which is what `rgba($o-brand-primary, .5)` used to do.
        """
        background = self._page_background()
        rgb, alpha = self._ring_default()
        self.assertEqual(alpha, 1.0, "focus ring colour must be opaque")
        ratio = _contrast_ratio(_composite(rgb, alpha, background), background)
        self.assertGreaterEqual(
            ratio, WCAG_NON_TEXT, f"focus ring contrast {ratio:.2f}:1"
        )

    def test_focus_ring_is_visible_on_the_navbar(self):
        """SC 1.4.11 measures the ring against its *adjacent* colours.

        `outline-offset` draws the ring clear of the control, on whatever the
        host surface is - so the page background is not the only backdrop that
        matters. The navbar is the one webclient surface far from it: on
        community it is `$o-brand-odoo`, where the default ring scored 1.11:1.
        It is expected to retune `--o-ring-color`; this checks the value it
        picks actually clears the threshold against itself.
        """
        navbar = self._rule(".o_main_navbar", declaring="--o-ring-color")
        declared = _declaration(navbar, "--o-ring-color")
        ring, ring_alpha = _parse_color(declared)
        self.assertEqual(ring_alpha, 1.0, "navbar ring colour must be opaque")

        background = _declaration(navbar, "background")
        self.assertTrue(background, ".o_main_navbar declares no background")
        surface = re.search(r"#[0-9a-fA-F]{3,6}|rgba?\([^)]*\)", background)
        self.assertTrue(surface, ".o_main_navbar declares no background colour")
        surface_rgb, surface_alpha = _parse_color(surface.group())
        self.assertEqual(surface_alpha, 1.0, "navbar background must be opaque")

        ratio = _contrast_ratio(ring, surface_rgb)
        self.assertGreaterEqual(
            ratio,
            WCAG_NON_TEXT,
            f"focus ring {declared} on navbar {surface.group()}: {ratio:.2f}:1",
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

    # Stacks reach the browser both as `font-family:` and as the custom
    # properties backing it (`--font-sans-serif`, `--headings-font-family`, …).
    _FONT_DECLARATION = re.compile(r"[\w-]*font[\w-]*\s*:\s*([^;{}]+)", re.IGNORECASE)
    # Every generic family a stack may terminate in.
    _GENERICS = frozenset(
        [
            "serif",
            "sans-serif",
            "monospace",
            "cursive",
            "fantasy",
            "system-ui",
            "ui-serif",
            "ui-sans-serif",
            "ui-monospace",
            "ui-rounded",
            "math",
            "emoji",
            "fangsong",
        ]
    )

    def _font_stacks(self, css=None):
        """Every font declaration naming a generic family, as a family list.

        Containment rather than "ends with": the stacks deliberately trail emoji
        fonts behind the generic, so keying on the last entry matches nothing.
        """
        for match in self._FONT_DECLARATION.finditer(
            css if css is not None else self.css
        ):
            families = [f.strip() for f in match.group(1).split(",")]
            if len(families) > 1 and self._GENERICS.intersection(
                f.lower() for f in families
            ):
                yield families

    def test_font_stacks_list_no_family_twice(self):
        """A repeated family is unreachable, and marks a mis-built stack.

        `$o-headings-font-family` read `"Inter", "SF Pro Display", "Inter", …`
        because it nested `$o-system-fonts` (which already leads with "Inter")
        inside another list, and the report bundle's sans-serif stack carried
        the Noto fallback twice - `o-add-unicode-support-font()` inserted it at
        the requested index *and* again at the generic family.
        """
        for bundle in ("web.assets_backend", "web.report_assets_common"):
            css = self.css if bundle == "web.assets_backend" else self._compiled(bundle)
            stacks = list(self._font_stacks(css))
            self.assertTrue(stacks, f"{bundle}: no font stacks found to check")
            for families in stacks:
                lowered = [f.lower() for f in families]
                repeated = {f for f in lowered if lowered.count(f) > 1}
                self.assertFalse(
                    repeated,
                    f"{bundle}: {sorted(repeated)} listed more than once; every "
                    f"entry between the copies is dead:\n  {', '.join(families)}",
                )

    def test_only_emoji_fonts_follow_the_generic_family(self):
        """A generic family always resolves, so a real family behind it is dead.

        Emoji fonts sit there on purpose - they are only ever consulted per
        glyph - so they are the sole exception.
        """
        allowed = re.compile(r"emoji|symbol", re.IGNORECASE)
        for families in self._font_stacks():
            first_generic = next(
                i for i, f in enumerate(families) if f.lower() in self._GENERICS
            )
            for family in families[first_generic + 1 :]:
                self.assertRegex(
                    family,
                    allowed,
                    f"{family!r} sits behind a generic family and is unreachable:"
                    f"\n  {', '.join(families)}",
                )

    def test_monospace_stack_is_the_design_system_one(self):
        """Bootstrap's `$font-family-monospace` must be mapped like the sans one.

        Unmapped, `<code>`/`<pre>`/`--font-monospace` rendered in Bootstrap's
        default stack while the components reading `$o-font-family-monospace`
        used a different one - two monospace faces in the same UI.
        """
        declared = _declaration(self.css, "--font-monospace")
        self.assertTrue(declared, "--font-monospace is not defined")
        self.assertIn(
            "Odoo Unicode Support Noto",
            declared,
            "--font-monospace is not the stack built by "
            "o-add-unicode-support-font(); it is Bootstrap's default",
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
