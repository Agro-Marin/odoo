from odoo import models
from odoo.orm.registration import add_to_registry
from odoo.tests.common import TransactionCase

from odoo.addons.exchange.tools import Verdict

SCRIPT_KEY = "exchange_demo_script"
BATCH_KEY = "exchange_demo_batch"


class ExchangeProtocolDemo(models.AbstractModel):
    _name = "exchange.protocol.demo"
    _inherit = ["exchange.protocol"]
    _description = "Demo Exchange Protocol"
    _protocol_code = "demo"
    _protocol_label = "Demo Counterparty"
    _document_kinds = {"invoice": "Invoice", "classification": "Classification"}

    def _prepare_message(self, transmission):
        from odoo.libs.documents import Document

        return Document(
            f"<demo intent='{transmission.intent}'/>".encode(),
            name=f"demo-{transmission.id}.xml",
        )

    def _check_message(self, transmission):
        return list(self.env.context.get("demo_errors") or [])

    def _send_message(self, transmission, document):
        script = self.env.context.get(SCRIPT_KEY)
        if isinstance(script, Exception):
            raise script
        return script

    def _send_batch(self, transmissions):
        script = self.env.context.get(BATCH_KEY)
        if script is None:
            return super()._send_batch(transmissions)
        if isinstance(script, Exception):
            raise script
        self.env.context["demo_batches"].append(len(transmissions))
        return {
            transmission.id: script.get(index)
            for index, transmission in enumerate(transmissions)
            if script.get(index) is not None
        }

    def _read_verdict(self, transmission):
        return self.env.context.get("demo_poll")

    def _read_inbox(self, channel):
        return list(self.env.context.get("demo_inbox") or [])

    def _add_from_inbox(self, channel, documents):
        self.env.context["demo_inbox_seen"].append(
            (self._protocol_code, len(documents))
        )


class ExchangeSubjectDemo(models.Model):
    _name = "res.partner"
    _inherit = ["res.partner", "mixin.exchange.subject"]

    def _get_exchange_channel(self):
        return self.env.context.get("demo_channel")


class ExchangeCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for model_name in ("res.partner",):
            model_cls = cls.registry[model_name]
            cls.addClassCleanup(
                setattr, model_cls, "_base_classes__", model_cls._base_classes__
            )

        add_to_registry(cls.registry, ExchangeProtocolDemo)
        add_to_registry(cls.registry, ExchangeSubjectDemo)
        cls.registry._setup_models__(cls.env.cr, [])
        cls.addClassCleanup(cls.registry._setup_models__, cls.env.cr, [])
        cls.env = cls.env(context=dict(cls.env.context))

        cls.endpoint = cls.env["api.endpoint.outbound"].create(
            {
                "name": "Demo Counterparty Endpoint",
                "code": "demo_counterparty",
                "category": "tax",
                "endpoint_url": "https://demo.example.com",
                "environment": "test",
            },
        )
        cls.channel = cls.env["exchange.channel"].create(
            {
                "endpoint_id": cls.endpoint.id,
                "protocol": "demo",
                "counterparty": "authority",
            },
        )
        cls.subject = cls.env["res.partner"].create({"name": "Subject Co"})

    def _add_transmission(self, intent="issue", subject=None, kind=""):
        subject = subject or self.subject
        return subject.with_context(demo_channel=self.channel)._add_transmission(
            intent, kind=kind
        )

    def _send(self, transmission, verdict=None, **context):
        return transmission.with_context(
            **{SCRIPT_KEY: verdict}, **context
        ).action_send()

    def _accepted(self, reference="REF-1"):
        return Verdict(state="accepted", reference=reference, message="Accepted")

    def _sent(self, reference="REF-1"):
        return Verdict(state="sent", reference=reference)
