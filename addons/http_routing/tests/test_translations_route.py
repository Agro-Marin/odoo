# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json

from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestWebsiteTranslations(HttpCase):
    """``/website/translations`` is ``auth="public"``: what it serves must come
    from the server-side allow-list, never from the query string.
    """

    EP = "/website/translations"

    def _modules(self, url):
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        return set(json.loads(response.content).get("modules", {}))

    def test_serves_the_frontend_allow_list(self):
        # "web" is the floor every stack contributes
        # (``_get_translation_frontend_modules_name``); other modules add to it.
        self.assertIn("web", self._modules(self.EP))

    def test_caller_supplied_mods_cannot_widen_the_bundle(self):
        # ``mods`` used to be appended to the allow-list, so an anonymous
        # visitor chose what the route served -- and, through it, the cache key
        # of ``_get_web_translations_hash`` (see below, that is the sharp part).
        # Modules opt in through ``_get_translation_frontend_modules_name`` /
        # ``_get_translation_frontend_modules_domain``, not through a query
        # parameter.
        baseline = self._modules(self.EP)
        widened = self._modules(self.EP + "?mods=base,mail,web_tour")
        self.assertEqual(widened, baseline)

    def test_unknown_mods_do_not_mint_cache_entries(self):
        # Every distinct module list keys its own entry in
        # ``ir.http._get_web_translations_hash``'s ormcache, which lives in the
        # shared 8192-slot "default" LRU: an unauthenticated caller able to pick
        # the list can evict the registry's ACL, record-rule and xmlid caches
        # with a few thousand requests. The served list -- hence the cache key
        # -- must not depend on the query string.
        lru = self.env.registry.ormcache_lrus["default"]
        self.url_open(self.EP)  # warm
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
        # Same corollary from the client's side: the ETag-like hash a browser
        # caches on must not shift because someone appended ?mods=...
        plain = json.loads(self.url_open(self.EP).content)
        with_mods = json.loads(self.url_open(self.EP + "?mods=base").content)
        self.assertEqual(plain["hash"], with_mods["hash"])
