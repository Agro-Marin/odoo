import base64
import re

from odoo.tests.common import HttpCase, TransactionCase, tagged

from odoo.addons.base.tests.common import new_test_user

CSS_ERROR_MARKER = "A css error occurred"


@tagged("post_install", "-at_install", "web_color_scheme")
class TestColorScheme(HttpCase):
    def _open_webclient(self, **settings):
        user = new_test_user(
            self.env, "bob", groups="base.group_user", email="bob@test.com"
        )
        if settings:
            user.res_users_settings_id.write(settings)
        self.authenticate(user.login, user.login)
        return self.url_open("/odoo")

    def test_color_scheme_default(self):
        response = self._open_webclient()
        self.assertEqual(response.cookies.get("color_scheme"), "light")

    def test_color_scheme_dark(self):
        response = self._open_webclient(color_scheme="dark")
        self.assertEqual(response.cookies.get("color_scheme"), "dark")

    def test_explicit_setting_beats_cookie(self):
        """The cookie caches what the browser resolved for ``system``; it must
        not override a user who asked for light or dark explicitly."""
        user = new_test_user(
            self.env, "bob", groups="base.group_user", email="bob@test.com"
        )
        user.res_users_settings_id.write({"color_scheme": "light"})
        self.authenticate(user.login, user.login)
        self.opener.cookies["color_scheme"] = "dark"
        response = self.url_open("/odoo")
        self.assertEqual(response.cookies.get("color_scheme"), "light")

    def test_system_preference_ships_both_bundles(self):
        """A `system` user must get both stylesheets behind prefers-color-scheme.

        The browser is the only thing that can resolve `system`, so the server
        cannot pick one. Serving a single bundle means a dark-OS user paints
        light and is then reloaded into dark.
        """
        html = self._open_webclient(color_scheme="system").text
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn("prefers-color-scheme: light", html)

    def test_explicit_preference_ships_one_bundle(self):
        html = self._open_webclient(color_scheme="dark").text
        self.assertNotIn("prefers-color-scheme", html)
        self.assertIn("assets_web_dark", html)

    def test_document_carries_the_dark_scheme(self):
        """The token layer keys off this attribute, so it has to be on the
        document before any stylesheet is read."""
        html = self._open_webclient(color_scheme="dark").text
        self.assertIn('data-color-scheme="dark"', html)

    def test_document_carries_the_light_scheme(self):
        html = self._open_webclient(color_scheme="light").text
        self.assertIn('data-color-scheme="light"', html)

    def test_system_preference_states_no_scheme_server_side(self):
        """The server must not answer an attribute it cannot resolve.

        Which stylesheet applies to a `system` user is decided live by
        `prefers-color-scheme`; the value the server has is whatever the
        browser last cached in the cookie, and the two disagree whenever the OS
        changed theme since the last visit. The attribute is then read against
        the bundle the media query picked, so a stale `dark` selects the dark
        values out of the light sheet. Emitting nothing costs no paint -- the
        inline resolver sets it from the same input the media query uses, in
        the same `<head>` and ahead of every stylesheet.
        """
        user = new_test_user(
            self.env, "bob", groups="base.group_user", email="bob@test.com"
        )
        user.res_users_settings_id.write({"color_scheme": "system"})
        self.authenticate(user.login, user.login)
        self.opener.cookies["color_scheme"] = "dark"
        html = self.url_open("/odoo").text
        self.assertNotIn("data-color-scheme", html.split("<head", 1)[0])

    def test_system_preference_sets_the_attribute_client_side(self):
        """The server cannot resolve `system`, so the inline resolver does —
        and must set the attribute as well as the cookie, before the bundles."""
        html = self._open_webclient(color_scheme="system").text
        self.assertIn("documentElement.dataset.colorScheme", html)
        self.assertLess(
            html.index("documentElement.dataset.colorScheme"),
            html.index("/web/assets/"),
        )

    def test_system_preference_resolves_the_cookie_before_the_bundles(self):
        """The inline resolver must precede the bundle scripts.

        Several modules read the cookie at import time, where nothing later can
        correct them, so it has to be settled before any bundle runs rather
        than fixed up afterwards.
        """
        html = self._open_webclient(color_scheme="system").text
        resolver = html.index("web.layout.colorscheme")
        self.assertLess(resolver, html.index("/web/assets/"))

    def test_explicit_preference_needs_no_resolver(self):
        html = self._open_webclient(color_scheme="dark").text
        self.assertNotIn("web.layout.colorscheme", html)

    def test_system_setting_defers_to_cookie(self):
        user = new_test_user(
            self.env, "bob", groups="base.group_user", email="bob@test.com"
        )
        user.res_users_settings_id.write({"color_scheme": "system"})
        self.authenticate(user.login, user.login)
        self.opener.cookies["color_scheme"] = "dark"
        response = self.url_open("/odoo")
        self.assertEqual(response.cookies.get("color_scheme"), "dark")

    def _promoted_user(self):
        """A user promoted from portal, which is how a user ends up with no
        settings row: ``res.users.create`` makes one only for a user that is
        already internal, and nothing re-makes it on promotion."""
        user = new_test_user(
            self.env, "bob", groups="base.group_portal", email="bob@test.com"
        )
        user.write(
            {
                "group_ids": [
                    (3, self.env.ref("base.group_portal").id),
                    (4, self.env.ref("base.group_user").id),
                ]
            }
        )
        user.invalidate_recordset()
        self.assertFalse(user.res_users_settings_id, "promotion makes no row")
        return user

    def test_preference_saves_without_a_settings_row(self):
        """Saving the Preferences radio must stick, row or no row.

        The radio writes a related field into ``res.users.settings``, and
        ``_inverse_related`` reaches the target by *reading*
        ``res_users_settings_id``: with no row it writes nothing and returns
        ``True``, so the dialog closes on a preference that was never stored.

        ``res.users.write`` materialises the row for any field that lives on
        the settings record, so the write is what makes the row rather than
        something else having had to make it first.
        """
        user = self._promoted_user()

        user.with_user(user).write({"color_scheme": "dark"})
        user.invalidate_recordset()
        self.assertTrue(user.res_users_settings_id, "the write must make the row")
        self.assertEqual(user.color_scheme, "dark")

        self.authenticate(user.login, user.login)
        self.assertEqual(
            self.url_open("/odoo").cookies.get("color_scheme"),
            "dark",
            "the saved preference must reach the served page",
        )

    def test_preference_survives_being_set_at_create(self):
        """A user created with a theme must have it.

        ``_inverse_related`` runs inside ``super().create()``, before
        ``res.users.create`` has made the settings row — so the value went
        nowhere and the user came back on the default, which for a scheme is
        `system` and therefore looks like a plausible answer.
        """
        user = self.env["res.users"].create(
            {
                "login": "created_dark",
                "name": "created dark",
                "color_scheme": "dark",
                "group_ids": [(4, self.env.ref("base.group_user").id)],
            }
        )
        user.invalidate_recordset()
        self.assertEqual(user.color_scheme, "dark")

        self.authenticate(user.login, user.login)
        self.assertEqual(self.url_open("/odoo").cookies.get("color_scheme"), "dark")

    def test_the_boot_also_materialises_the_row(self):
        """Unchanged, and still the reason a preference dialog has something to
        write into: the web client asks ``_find_or_create_for_user`` while
        booting. It is no longer what the save depends on."""
        user = self._promoted_user()
        self.authenticate(user.login, user.login)
        self.url_open("/odoo")
        user.invalidate_recordset()
        self.assertTrue(user.res_users_settings_id)


@tagged("post_install", "-at_install", "web_color_scheme")
class TestDarkBundles(TransactionCase):
    """The dark bundles must assemble and compile without a theme installed.

    ``web`` owns the dark-mode mechanism, so a community-only database has to
    produce dark CSS on its own: every anchor in ``web._dark_mode_variables``
    must resolve, and ``primary_variables.dark.scss`` must be valid SCSS
    against the light palette it answers.

    Only the *addons path* decides whether that is what is being tested.
    ``web_enterprise`` declares ``auto_install: ['web']``, so on a workspace
    with the enterprise checkout on the path it arrives with ``web`` however
    narrow the ``-i`` list is, and this passes having exercised the theme
    rather than the fallback. The guarantee is real where the path is
    community, which is how ``asset_lint.yml`` runs it
    (``--addons-path=odoo/addons,addons``) and is worth reproducing by hand the
    same way rather than by choosing modules.
    """

    def _compile(self, bundle):
        # _get_asset_nodes only assembles a <link> and passes on broken SCSS;
        # css() runs the compiler but swallows a failure into a stub carrying
        # CSS_ERROR_MARKER, so the content is the only honest signal.
        assets = self.env["ir.qweb"]._get_asset_bundle(bundle, css=True, js=False)
        self.assertTrue(assets.stylesheets, f"{bundle} must carry stylesheets")
        css = base64.b64decode(assets.css().datas).decode("utf-8", "replace")
        self.assertNotIn(CSS_ERROR_MARKER, css, f"{bundle} failed to compile")
        return css

    def test_assets_web_dark_compiles(self):
        css = self._compile("web.assets_web_dark")
        self.assertIn(
            "color-scheme:dark",
            css.replace(" ", ""),
            "the dark palette must reach the bundle, not merely compile",
        )

    def test_assets_backend_dark_compiles(self):
        # Variables-only fragment: it carries no declarations of its own, so
        # compiling cleanly is the whole assertion.
        self._compile("web.assets_backend_dark")


@tagged("post_install", "-at_install", "web_color_scheme")
class TestTokenLayer(TransactionCase):
    """The token layer must emit the same palette the SCSS resolved.

    Tokens exist so a declaration can bind through the cascade instead of the
    compile. That only holds if every bundle publishes them, and if the light
    and dark bundles publish their own scheme's values.

    ``--gray-100`` is Bootstrap's, fed from ``$o-gray-100`` and reaching the
    stylesheet unprefixed because every module here sets
    ``$variable-prefix: ""``. It is asserted alongside the Odoo-owned tokens
    because component CSS consumes it directly rather than through an alias.
    """

    #: token -> (light value, dark value). Only tokens web resolves on its own:
    #: asserting a brand-derived value would encode one theme's palette and
    #: fail the moment a theme is installed.
    EXPECTED = {
        "--gray-100": ("#f8fafc", "#0B1120"),
        "--o-bg-view": ("white", "#151D2E"),
    }

    #: Published, and answered per scheme, whatever a theme sets them to.
    SCHEME_SENSITIVE = ("--o-brand-fill", "--o-action", "--o-action-text")

    def _css(self, bundle):
        assets = self.env["ir.qweb"]._get_asset_bundle(bundle, css=True, js=False)
        css = base64.b64decode(assets.css().datas).decode("utf-8", "replace")
        self.assertNotIn(CSS_ERROR_MARKER, css, f"{bundle} failed to compile")
        return css

    def _tokens(self, bundle, names):
        css = self._css(bundle)
        return {
            name: re.search(rf"{re.escape(name)}:\s*([^;}}]+)", css) for name in names
        }

    @staticmethod
    def _declarations_at(css, start, pattern=r"--[\w-]+"):
        """Return the rule's declarations whose property matches *pattern*.

        Custom properties by default, which is what the token comparisons want;
        a caller after a real property (``color-scheme``) says so.
        """
        open_brace = css.index("{", start)
        depth, end = 0, open_brace
        while True:
            if css[end] == "{":
                depth += 1
            elif css[end] == "}":
                depth -= 1
                if not depth:
                    break
            end += 1
        return {
            m.group(1): m.group(2).strip()
            for m in re.finditer(
                rf"({pattern})\s*:\s*([^;}}]+)", css[open_brace + 1 : end]
            )
        }

    def _dark_block(self, bundle):
        css = self._css(bundle)
        # Unquoted: the compiled sheet is minified, so searching for the source
        # form `[data-color-scheme="dark"]` finds nothing and every comparison
        # below passes over an empty dict.
        match = re.search(r"\[data-color-scheme=[\"']?dark[\"']?\]", css)
        self.assertIsNotNone(match, f"{bundle} must publish the dark scheme")
        return self._declarations_at(css, match.start())

    def _settled_dark_root(self, bundle):
        """Every ``:root[data-color-scheme=dark]`` rule merged, as ``_settled_root``.

        ``_dark_block`` reads the first one, which is the token layer's. That was
        the only one until a rule outside ``tokens.scss`` needed to state a dark
        answer at the root -- ``fields.scss`` does, for the input border -- and
        reading only the first scores those as never stated.

        The selector is anchored: ``:root[data-color-scheme=dark] .o_cc4 a`` is a
        descendant rule, not a publication.
        """
        css = re.sub(r"/\*.*?\*/", "", self._css(bundle), flags=re.DOTALL)
        merged = {}
        for match in re.finditer(
            r"(?:^|\})\s*:root\[data-color-scheme=[\"']?dark[\"']?\]\s*\{", css
        ):
            merged.update(self._declarations_at(css, match.end() - 1))
        self.assertTrue(merged, f"{bundle} publishes no dark `:root`")
        return merged

    @classmethod
    def _resolve(cls, value, scope, depth=0):
        """Substitute ``var()`` against *scope* until it stops changing."""
        if depth > 12:
            return value

        def substitute(match):
            name, fallback = match.group(1), match.group(2)
            if name in scope:
                return cls._resolve(scope[name], scope, depth + 1)
            return (
                cls._resolve(fallback.strip(), scope, depth + 1)
                if fallback
                else match.group(0)
            )

        substituted = re.sub(
            r"var\(\s*(--[\w-]+)\s*(?:,([^()]*(?:\([^()]*\)[^()]*)*))?\)",
            substitute,
            value,
        )
        return (
            value
            if substituted == value
            else cls._resolve(substituted, scope, depth + 1)
        )

    def _settled_root(self, bundle):
        """Every document-root rule merged in source order, as the cascade sees it.

        A bundle carries several: Bootstrap's, the token layer's, the alias
        block, and whatever a module adds later — ``html_editor.backend.scss``
        re-states ``--white`` a thousand files after ``tokens.scss``. They all
        score the same, so the last one is in effect, and reading only the
        first reports a value something later supersedes.

        The comments are stripped first because the bundle carries one per
        source file, and a rule preceded by one does not begin at a ``}``. Not
        stripping them was worse than useless here: it excluded *every* commented
        `:root`, so this returned a subset and the assertions built on it passed
        by not looking. ``.fa-bracket-curly :root`` is a different subtree and
        is excluded by requiring nothing before the selector.
        """
        css = re.sub(r"/\*.*?\*/", "", self._css(bundle), flags=re.DOTALL)
        merged = {}
        for match in re.finditer(r"(?:^|\})\s*:root\s*\{", css):
            merged.update(self._declarations_at(css, match.end() - 1))
        self.assertTrue(merged, f"{bundle} publishes no `:root`")
        return merged

    def _token_root(self, bundle):
        css = self._css(bundle)
        roots = (
            self._declarations_at(css, match.start())
            for match in re.finditer(r":root\s*\{", css)
        )
        root = next((r for r in roots if "--o-record-color-1" in r), None)
        self.assertIsNotNone(root, f"{bundle} publishes no token `:root`")
        return root

    def _assert_scheme(self, bundle, index):
        for name, match in self._tokens(bundle, self.EXPECTED).items():
            self.assertIsNotNone(match, f"{name} must be emitted in {bundle}")
            self.assertEqual(
                match.group(1).strip().lower(),
                self.EXPECTED[name][index].lower(),
                f"{name} must carry its own scheme's value in {bundle}",
            )

    def test_light_bundle_tokens(self):
        self._assert_scheme("web.assets_web", 0)

    def test_dark_bundle_tokens(self):
        self._assert_scheme("web.assets_web_dark", 1)

    def test_brand_tokens_answer_per_scheme(self):
        """Whatever palette is installed, the dark bundle must answer the
        brand-derived tokens rather than inheriting the light values."""
        light = self._tokens("web.assets_web", self.SCHEME_SENSITIVE)
        dark = self._tokens("web.assets_web_dark", self.SCHEME_SENSITIVE)
        for name in self.SCHEME_SENSITIVE:
            self.assertIsNotNone(light[name], f"{name} must be emitted in light")
            self.assertIsNotNone(dark[name], f"{name} must be emitted in dark")
            self.assertNotEqual(
                light[name].group(1).strip().lower(),
                dark[name].group(1).strip().lower(),
                f"{name} kept its light value in the dark bundle",
            )

    def test_both_publication_paths_agree(self):
        """The light bundle's dark block must equal the dark bundle's ``:root``.

        These are the two ways the dark palette reaches a stylesheet, and the
        whole point of the token layer is that they are interchangeable: the
        light bundle states the dark answer from ``palette_dark.scss``, the dark
        bundle resolves it by compiling the dark palette. The moment one bundle
        serves both schemes, a property where they disagree paints the wrong
        colour -- while each bundle, read on its own, looks correct.

        They part when a theme changes a light value without stating its dark
        counterpart in its own ``palette_dark.scss``, and the derived ones part
        most easily: ``web_enterprise`` never assigns ``$o-brand-odoo`` in dark,
        it assigns ``$o-enterprise-color`` and lets web's palette derive the
        rest -- a derivation ``tokens.scss`` cannot replay, since it reads
        ``$o-dark-brand-odoo`` by name.

        Which properties count is not a list to maintain, and not the token
        layer's block either: a property belongs to the scheme's answer exactly
        when the two bundles' ``:root`` disagree about it. That is what let this
        find the four shadows, the input border and the brand inside the website
        palette, none of which ``tokens.scss`` publishes. The website palettes,
        the geometry and the font stacks are identical in both and stay silent
        here without being named.

        A property need not be restated to be answered: ``--100`` is
        ``var(--o-gray-100, #f8fafc)``, so it follows whatever answers the ramp
        and the fallback it differs by is unreachable. Both sides are resolved
        before comparing, which is also what a browser does.

        Run it with the theme installed -- the light half of a disagreement is
        web's fallback value, so a community-only database cannot see it.
        """
        light_root = self._settled_root("web.assets_web")
        dark_root = self._settled_root("web.assets_web_dark")
        attribute = self._settled_dark_root("web.assets_web")

        scheme_dependent = {
            name: value
            for name, value in dark_root.items()
            if light_root.get(name) != value
        }
        self.assertTrue(
            scheme_dependent,
            "the two bundles' `:root` agree on everything, which means one of "
            "them did not compile the token layer at all",
        )

        under_dark = light_root | attribute
        missing = sorted(
            name
            for name, value in scheme_dependent.items()
            if name not in attribute
            and self._resolve(light_root.get(name, ""), under_dark)
            != self._resolve(value, dark_root)
        )
        divergent = sorted(
            name
            for name, value in scheme_dependent.items()
            if name in attribute and attribute[name] != value
        )

        self.assertFalse(
            missing,
            f"{len(missing)} scheme-dependent root propert(ies) are never "
            "restated under the dark attribute, so a single stylesheet would "
            "serve the light value in dark mode:\n  " + "\n  ".join(missing),
        )
        self.assertFalse(
            divergent,
            "the dark palette differs between the two bundles that publish it; "
            "a theme changing a light value owes its palette_dark.scss the dark "
            "counterpart:\n"
            + "\n".join(
                f"  {name}: assets_web says {attribute[name]!r}, "
                f"assets_web_dark says {scheme_dependent[name]!r}"
                for name in divergent
            ),
        )

    def test_a_light_bundle_carries_both_color_schemes(self):
        """`color-scheme` must follow the attribute, not the compiling bundle.

        It is what `light-dark()` reads, and `light-dark()` is how a plain
        declaration carries both schemes without a token being invented for a
        colour used once. Set from `$o-webclient-color-scheme` on
        `.o_web_client`, as it was, a light bundle could only ever say `light`,
        so the function was unusable in the one direction that matters.

        Asserted on the *light* bundle: the dark one saying `dark` proves
        nothing, it says `dark` everywhere.
        """
        css = self._css("web.assets_web")
        for selector, expected in (
            (r":root\{[^{}]*--o-record-color-1\b", "light"),
            (r':root\[data-color-scheme="?dark"?\]', "dark"),
        ):
            match = re.search(selector, css)
            self.assertIsNotNone(match, f"{selector} must be emitted")
            self.assertEqual(
                self._declarations_at(css, match.start(), r"color-scheme").get(
                    "color-scheme"
                ),
                expected,
                f"{selector} must state its own scheme",
            )
        match = re.search(r"\.o_web_client\{", css)
        self.assertIsNotNone(match)
        self.assertNotIn(
            "color-scheme",
            self._declarations_at(match.string, match.start(), r"[-\w]+"),
            "`.o_web_client` must not restate the scheme it inherits from :root",
        )

    #: Bootstrap tokens this palette owns, wired to it in the cascade rather
    #: than at compile time. Each is definitional in `bootstrap_overridden.scss`
    #: or derived from it by Bootstrap deterministically.
    BOOTSTRAP_ALIASES = (
        "--gray-100",
        "--gray-900",
        "--white",
        "--primary",
        "--body-color",
        "--emphasis-color",
        "--secondary-bg",
    )

    def test_bootstrap_tokens_follow_the_palette_at_runtime(self):
        """Aliased, not resolved -- and only where Bootstrap wears this palette.

        `$gray-200: $o-gray-200` is already true; said in Sass it produces a
        fixed colour, which is one of the reasons a second bundle exists. As
        `var(--o-gray-200)` the same statement follows the scheme, so these
        need no dark half of their own.

        The frontend is the reason this is guarded: Bootstrap keeps its own
        greys there on purpose, and publishing the alias would quietly move
        `--gray-200` from #e9ecef to #e2e8f0 on every public page.
        """
        root = self._settled_root("web.assets_web")
        for name in self.BOOTSTRAP_ALIASES:
            # A fallback is allowed: `var(--o-white, #fff)` still follows the
            # palette, and is how a file that must define the name regardless
            # defers to it rather than overriding it.
            self.assertRegex(
                root.get(name, ""),
                r"^var\(\s*--o-[\w-]+\s*[,)]",
                f"{name} must reach the palette through the cascade",
            )

        frontend = self._settled_root("web.assets_frontend")
        for name in self.BOOTSTRAP_ALIASES:
            self.assertNotIn(
                "var(--o-",
                frontend.get(name, ""),
                f"{name} must keep Bootstrap's own value on the frontend",
            )

    def test_frontend_publishes_tokens(self):
        # website templates already consume tokens, so the frontend bundle must
        # carry the layer too, not only the backend.
        for name, match in self._tokens("web.assets_frontend", self.EXPECTED).items():
            self.assertIsNotNone(match, f"{name} must be emitted on the frontend")
