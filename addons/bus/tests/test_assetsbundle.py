import odoo.tests


@odoo.tests.tagged("post_install", "-at_install", "assets_bundle")
class BusWebTests(odoo.tests.HttpCase):
    def test_bundle_sends_bus(self):
        """
        Tests two things:
        - A ``bundle_changed`` message is posted to the bus when a TRACKED
          bundle's assets are (re)generated, i.e. their hash has been
          recomputed and differs from the attachment's
          (``AssetAttachmentStore.TRACKED_BUNDLES``).
        - Non-tracked bundles do NOT broadcast.

        Only ``web.assets_web`` is requested for JS: it is the bundle pages
        actually load (and the only tracked one). ``web.assets_backend`` is a
        component include of it, never built standalone in production — and
        building its standalone LEGACY js would stub out every native-ESM
        file with a loud ``module_syntax_in_legacy_bundle`` error per file.
        """
        # start from a clean slate
        self.env["ir.attachment"].search([("name", "ilike", "web.assets_%")]).unlink()
        self.env.registry.clear_cache()

        sendones = []

        def patched_sendone(self, channel, notificationType, message):
            """Control API and number of messages posted to the bus linked to
            bundle_changed events"""
            if notificationType == "bundle_changed":
                sendones.append((channel, message))

        self.patch(type(self.env["bus.bus"]), "_sendone", patched_sendone)

        self.assertEqual(
            self.url_open(
                "/web/assets/any/web.assets_web.min.js", allow_redirects=False
            ).status_code,
            200,
        )
        self.assertEqual(
            self.url_open(
                "/web/assets/any/web.assets_web.min.css", allow_redirects=False
            ).status_code,
            200,
        )
        # A non-tracked bundle must not broadcast (CSS build: css-only checks
        # keep this free of the legacy-ESM stubbing noise).
        self.assertEqual(
            self.url_open(
                "/web/assets/any/web.assets_frontend.min.css", allow_redirects=False
            ).status_code,
            200,
        )

        # One sendone per generated artifact (JS + CSS) of the tracked bundle.
        self.assertEqual(
            len(sendones),
            2,
            "Received %s" % "\n".join("%s - %s" % (tmp[0], tmp[1]) for tmp in sendones),
        )
        for channel, message in sendones:
            self.assertEqual(channel, "broadcast")
            self.assertEqual(len(message), 1)
            self.assertTrue(isinstance(message.get("server_version"), str))
