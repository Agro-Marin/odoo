from odoo.exceptions import AccessDenied
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.bus.tests.common import channel_keys


@tagged("post_install", "-at_install")
class TestCollaborationChannels(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["html_editor.converter.test"].create(
            {
                "html": "<p>collaborative body</p>",
            }
        )
        cls.admin = cls.env.ref("base.user_admin")
        cls.plain = new_test_user(
            cls.env,
            login="collab_plain_user",
            groups="base.group_user",
        )

    def _channel(self, res_id=None, model="html_editor.converter.test", field="html"):
        return f"editor_collaboration:{model}:{field}:{res_id or self.record.id}"

    def _subscribe(self, user, channels):
        return channel_keys(
            self.env,
            self.env["ir.websocket"]
            .with_user(user)
            ._build_bus_channel_list(
                channels,
            ),
        )

    def _editor_channels(self, keys):
        return [key for key in keys if len(key) > 1 and key[1] == "editor_collaboration"]

    def test_authorised_user_gets_the_collaboration_channel(self):
        keys = self._subscribe(self.admin, [self._channel()])
        self.assertIn(
            (
                self.env.registry.db_name,
                "editor_collaboration",
                "html_editor.converter.test",
                "html",
                self.record.id,
            ),
            keys,
        )

    def test_public_user_is_denied(self):
        public = self.env.ref("base.public_user")
        with self.assertRaises(AccessDenied):
            self.env["ir.websocket"].with_user(public)._build_bus_channel_list(
                [self._channel()],
            )

    def test_user_without_document_access_is_skipped(self):
        keys = self._subscribe(self.plain, [self._channel()])
        self.assertFalse(self._editor_channels(keys))

    def test_missing_document_is_skipped(self):
        keys = self._subscribe(self.admin, [self._channel(res_id=99999999)])
        self.assertFalse(self._editor_channels(keys))

    def test_malformed_channel_is_ignored(self):
        keys = self._subscribe(self.admin, ["editor_collaboration:garbage"])
        self.assertFalse(self._editor_channels(keys))

    def test_non_string_channels_are_preserved(self):
        keys = self._subscribe(self.admin, [("custom", "channel")])
        self.assertIn(("custom", "channel"), keys)
