import json
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.voice_gateway_ml.tools import intent
from odoo.addons.voice_gateway_ml.tools.intent import (
    INTENT_PURPOSE,
    can_interpret,
    interpret_sentence,
)

CHOICES = [
    {"id": "filter:unpaid", "label": "Filter: Sin pagar"},
    {"id": "groupby:user_id", "label": "Group by Vendedor"},
    {"id": "search:partner_id", "label": "Search Cliente for the value"},
]


class FakeRouter:
    def __init__(self, data):
        self.data = data
        self.requests = []

    def run(self, operation, request, company_id):
        self.requests.append((operation, request, company_id))
        return SimpleNamespace(data=self.data)


@tagged("post_install", "-at_install")
class TestInterpretSentence(TransactionCase):
    def _ask(self, data, text="muéstrame lo que no han pagado", choices=CHOICES):
        router = FakeRouter(data)
        with patch.object(intent, "get_router", return_value=router):
            return interpret_sentence(self.env, text, choices), router

    def test_the_model_may_only_answer_with_what_was_offered(self):
        actions, router = self._ask(
            {
                "actions": [
                    {"id": "filter:unpaid", "value": ""},
                    {"id": "button:delete_everything", "value": ""},
                    {"id": "search:partner_id", "value": "Acme"},
                ]
            }
        )
        self.assertEqual(
            actions,
            [
                {"id": "filter:unpaid", "value": ""},
                {"id": "search:partner_id", "value": "Acme"},
            ],
        )
        [(operation, request, company_id)] = router.requests
        self.assertEqual(operation, "chat")
        self.assertEqual(request.purpose, INTENT_PURPOSE)
        self.assertEqual(company_id, self.env.company.id)
        schema_ids = request.response_schema["properties"]["actions"]["items"][
            "properties"
        ]["id"]["enum"]
        self.assertEqual(schema_ids, [choice["id"] for choice in CHOICES])
        self.assertIn("SENTENCE: muéstrame lo que no han pagado", request.prompt)
        self.assertIn("filter:unpaid\tFilter: Sin pagar", request.prompt)

    def test_nothing_said_or_nothing_offered_asks_no_one(self):
        self.assertEqual(self._ask({"actions": []}, text="  ")[1].requests, [])
        self.assertEqual(self._ask({"actions": []}, choices=[])[1].requests, [])
        self.assertEqual(self._ask({"actions": []}, choices="nope")[1].requests, [])

    def test_the_purpose_is_sensitive_so_no_vendor_hears_it_without_a_policy(self):
        purpose = self.env.ref("voice_gateway_ml.purpose_voice_intent")
        self.assertEqual(purpose.key, INTENT_PURPOSE)
        self.assertTrue(purpose.sensitive)
        self.assertFalse(
            self.env["gateway.ml.policy"].search(
                [("purpose_id", "=", purpose.id)], limit=1
            )
        )
        self.assertFalse(can_interpret(self.env))


@tagged("post_install", "-at_install")
class TestIntentRoutes(HttpCase):
    def _call(self, route, **params):
        response = self.url_open(
            route,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
            headers={"Content-Type": "application/json"},
        )
        body = response.json()
        if "error" in body:
            raise AssertionError(body["error"]["data"]["name"])
        return body["result"]

    def test_an_internal_user_without_the_ai_group_may_ask(self):
        new_test_user(self.env, login="voice_ml_user", groups="base.group_user")
        self.authenticate("voice_ml_user", "voice_ml_user")
        self.assertEqual(
            self._call("/voice_gateway_ml/available"), {"available": False}
        )

    def test_a_portal_user_may_not(self):
        new_test_user(self.env, login="voice_ml_portal", groups="base.group_portal")
        self.authenticate("voice_ml_portal", "voice_ml_portal")
        self.assertEqual(
            self._call("/voice_gateway_ml/available"), {"available": False}
        )
        with self.assertRaisesRegex(AssertionError, "AccessError"):
            self._call("/voice_gateway_ml/interpret", text="hola", choices=CHOICES)
