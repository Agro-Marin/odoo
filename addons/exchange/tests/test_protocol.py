from odoo.tests.common import tagged

from .common import ExchangeCase


@tagged("post_install", "-at_install")
class TestExchangeProtocol(ExchangeCase):
    def test_a_protocol_is_discovered_by_its_code(self):
        protocols = self.env["exchange.protocol"]._get_protocols()
        self.assertEqual(protocols.get("demo"), "exchange.protocol.demo")

    def test_the_selection_is_derived_not_declared(self):
        codes = dict(self.env["exchange.protocol"]._selection_protocol())
        self.assertEqual(codes.get("demo"), "Demo Counterparty")

    def test_an_unknown_code_names_what_is_known(self):
        with self.assertRaises(LookupError) as caught:
            self.env["exchange.protocol"]._get_protocol("nowhere")
        self.assertIn("demo", str(caught.exception))

    def test_a_protocol_that_declares_no_message_says_so(self):
        with self.assertRaises(NotImplementedError):
            self.env["exchange.protocol"]._prepare_message(self.env["res.partner"])

    def test_sealing_defaults_to_leaving_the_document_alone(self):
        from odoo.libs.documents import Document

        document = Document(b"<x/>", name="x.xml")
        self.assertIs(
            self.env["exchange.protocol"]._seal_message(None, document), document
        )

    def test_an_inbox_is_empty_unless_a_protocol_reads_one(self):
        self.assertEqual(self.env["exchange.protocol"]._read_inbox(self.channel), [])

    def test_document_kinds_are_namespaced_by_their_protocol(self):
        kinds = dict(self.env["exchange.protocol"]._selection_document_kind())
        self.assertEqual(kinds.get("demo.invoice"), "Demo Counterparty: Invoice")
        self.assertEqual(
            kinds.get("demo.classification"), "Demo Counterparty: Classification"
        )

    def test_a_protocol_declaring_no_kind_contributes_none(self):
        kinds = dict(self.env["exchange.protocol"]._selection_document_kind())
        self.assertFalse([key for key in kinds if key.startswith("syngenta.")])

    def test_an_inbox_hands_what_it_read_to_its_own_protocol(self):
        seen = []
        self.channel.is_inbox_enabled = True
        self.channel.with_context(
            demo_inbox=["a", "b"], demo_inbox_seen=seen
        ).action_read_inbox()
        self.assertEqual(seen, [("demo", 2)])

    def test_a_protocol_that_reads_no_inbox_is_never_asked_what_to_do(self):
        seen = []
        self.channel.is_inbox_enabled = True
        self.channel.with_context(demo_inbox_seen=seen).action_read_inbox()
        self.assertEqual(seen, [])
        self.assertTrue(self.channel.date_last_inbox)

    def test_the_inbox_hook_is_per_protocol_not_per_database(self):
        assert_owner = self.env["exchange.protocol"]
        with self.assertRaises(NotImplementedError) as caught:
            assert_owner._add_from_inbox(self.channel, ["x"])
        self.assertIn(
            "two protocols in one database",
            str(caught.exception),
            "the hook sits on the protocol so a second localisation cannot "
            "silently take over the first's inbox",
        )
