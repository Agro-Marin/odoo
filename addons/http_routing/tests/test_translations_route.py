import json

from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestWebsiteTranslations(HttpCase):
    EP = "/website/translations"

    def _modules(self, url):
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        return set(json.loads(response.content).get("modules", {}))

    def test_serves_the_frontend_allow_list(self):
        self.assertIn("web", self._modules(self.EP))

    def test_caller_supplied_mods_cannot_widen_the_bundle(self):
        baseline = self._modules(self.EP)
        widened = self._modules(self.EP + "?mods=base,mail,web_tour")
        self.assertEqual(widened, baseline)

    def test_unknown_mods_do_not_mint_cache_entries(self):
        lru = self.env.registry.ormcache_lrus["default"]
        self.url_open(self.EP)
        before = len(lru.snapshot)
        for i in range(25):
            self.url_open(f"{self.EP}?mods=web,probe{i}")
        self.assertEqual(
            len(lru.snapshot),
            before,
            "the public translations route must not let its caller grow the "
            "shared ormcache",
        )

    def test_hash_is_stable_across_mods(self):
        plain = json.loads(self.url_open(self.EP).content)
        with_mods = json.loads(self.url_open(self.EP + "?mods=base").content)
        self.assertEqual(plain["hash"], with_mods["hash"])
