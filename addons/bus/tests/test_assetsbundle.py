import odoo.tests


@odoo.tests.tagged("post_install", "-at_install", "assets_bundle")
class BusWebTests(odoo.tests.HttpCase):
    def test_bundle_sends_bus(self):
        self.env["ir.attachment"].search([("name", "ilike", "web.assets_%")]).unlink()
        self.env.registry.clear_cache()

        sendones = []

        def patched_sendone(self, channel, notificationType, message):
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
        self.assertEqual(
            self.url_open(
                "/web/assets/any/web.assets_frontend.min.css", allow_redirects=False
            ).status_code,
            200,
        )

        self.assertEqual(
            len(sendones),
            2,
            "Received %s" % "\n".join("%s - %s" % (tmp[0], tmp[1]) for tmp in sendones),
        )
        for channel, message in sendones:
            self.assertEqual(channel, "broadcast")
            self.assertEqual(len(message), 1)
            self.assertTrue(isinstance(message.get("server_version"), str))
