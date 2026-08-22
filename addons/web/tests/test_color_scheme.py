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
        user = new_test_user(
            self.env, "bob", groups="base.group_user", email="bob@test.com"
        )
        user.res_users_settings_id.write({"color_scheme": "light"})
        self.authenticate(user.login, user.login)
        self.opener.cookies["color_scheme"] = "dark"
        response = self.url_open("/odoo")
        self.assertEqual(response.cookies.get("color_scheme"), "light")

    def test_system_preference_ships_both_bundles(self):
        html = self._open_webclient(color_scheme="system").text
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn("prefers-color-scheme: light", html)

    def test_explicit_preference_ships_one_bundle(self):
        html = self._open_webclient(color_scheme="dark").text
        self.assertNotIn("prefers-color-scheme", html)
        self.assertIn("assets_web_dark", html)

    def test_document_carries_the_dark_scheme(self):
        html = self._open_webclient(color_scheme="dark").text
        self.assertIn('data-color-scheme="dark"', html)

    def test_document_carries_the_light_scheme(self):
        html = self._open_webclient(color_scheme="light").text
        self.assertIn('data-color-scheme="light"', html)

    def test_system_preference_states_no_scheme_server_side(self):
        user = new_test_user(
            self.env, "bob", groups="base.group_user", email="bob@test.com"
        )
        user.res_users_settings_id.write({"color_scheme": "system"})
        self.authenticate(user.login, user.login)
        self.opener.cookies["color_scheme"] = "dark"
        html = self.url_open("/odoo").text
        self.assertNotIn("data-color-scheme", html.split("<head", 1)[0])

    def test_system_preference_sets_the_attribute_client_side(self):
        html = self._open_webclient(color_scheme="system").text
        self.assertIn("documentElement.dataset.colorScheme", html)
        self.assertLess(
            html.index("documentElement.dataset.colorScheme"),
            html.index("/web/assets/"),
        )

    def test_system_preference_resolves_the_cookie_before_the_bundles(self):
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
        user = self._promoted_user()
        self.authenticate(user.login, user.login)
        self.url_open("/odoo")
        user.invalidate_recordset()
        self.assertTrue(user.res_users_settings_id)


@tagged("post_install", "-at_install", "web_color_scheme")
class TestDarkBundles(TransactionCase):
    def _compile(self, bundle):
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
        self._compile("web.assets_backend_dark")


@tagged("post_install", "-at_install", "web_color_scheme")
class TestTokenLayer(TransactionCase):
    EXPECTED = {
        "--gray-100": ("#f8fafc", "#0B1120"),
        "--o-bg-view": ("white", "#151D2E"),
    }

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
        match = re.search(r"\[data-color-scheme=[\"']?dark[\"']?\]", css)
        self.assertIsNotNone(match, f"{bundle} must publish the dark scheme")
        return self._declarations_at(css, match.start())

    def _settled_dark_root(self, bundle):
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
        root = self._settled_root("web.assets_web")
        for name in self.BOOTSTRAP_ALIASES:
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
        for name, match in self._tokens("web.assets_frontend", self.EXPECTED).items():
            self.assertIsNotNone(match, f"{name} must be emitted on the frontend")
