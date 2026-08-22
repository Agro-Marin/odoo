import json
import os
import re
from pathlib import Path

from odoo.fields import Command
from odoo.tests import HttpCase, tagged
from odoo.tools.misc import file_path

from odoo.addons.mail.tests.common import mail_new_test_user

CONTRACT_FILE = "mail/static/tests/mock_server/contract/store_shapes.js"
CONTRACT_HEADER = """\
/* eslint-disable -- generated file; the body must stay strict JSON (see below)
 * and prettier's trailing commas would break the python json.loads parse. */
/* Store serialization contract — DO NOT EDIT BY HAND.
 *
 * Field-name sets per (scenario, Store model), shared by:
 * - python: mail/tests/test_mock_server_contract.py (real controllers)
 * - js: mail/static/tests/mock_server_contract.test.js (hoot mock server)
 *
 * Regenerate (after an intentional Store protocol change) with:
 *   MAIL_STORE_CONTRACT_REGEN=1 odoo-bin -d <bare mail db> \\
 *       --test-tags mail_store_contract --stop-after-init
 * (the db must have only mail's dependency closure installed), then re-run
 * both the python tag and the hoot suite `@mail/mock_server/contract`
 * before committing.
 *
 * The body between the braces must remain strict JSON (the python test
 * parses it with json.loads); only this comment may precede it.
 */
export default """

GATED_MODELS = [
    "DataResponse",
    "MessageReactions",
    "Store",
    "discuss.channel",
    "discuss.channel.member",
    "ir.attachment",
    "mail.followers",
    "mail.message",
    "mixin.mail.thread",
    "res.partner",
]


def payload_shape(payload):
    shape = {}
    for model_name, records in payload.items():
        if model_name not in GATED_MODELS:
            continue
        if isinstance(records, dict):
            keys = set(records)
        else:
            keys = {key for record in records for key in record}
        shape[model_name] = sorted(keys)
    return shape


def contract_path():
    root, _, relative = CONTRACT_FILE.partition("/static/")
    return Path(file_path(root + "/static")) / relative


def read_contract():
    try:
        content = contract_path().read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"export default (\{.*\});", content, flags=re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(1))


def write_contract(scenarios):
    body = json.dumps(
        {"gated_models": GATED_MODELS, "scenarios": scenarios},
        indent=4,
        sort_keys=True,
    )
    path = contract_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONTRACT_HEADER + body + ";\n", encoding="utf-8")


@tagged("post_install", "-at_install", "mail_controller", "mail_store_contract")
class TestMockServerContract(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_anna = mail_new_test_user(
            cls.env,
            login="contract_anna",
            name="Anna Contract",
            groups="base.group_user",
        )
        cls.user_bob = mail_new_test_user(
            cls.env,
            login="contract_bob",
            name="Bob Contract",
            groups="base.group_user",
        )
        cls.channel = cls.env["discuss.channel"].create(
            {
                "name": "Contract Channel",
                "channel_type": "channel",
                "channel_member_ids": [
                    Command.create({"partner_id": cls.user_anna.partner_id.id}),
                    Command.create({"partner_id": cls.user_bob.partner_id.id}),
                ],
            }
        )
        channel_anna = cls.channel.with_user(cls.user_anna)
        channel_bob = cls.channel.with_user(cls.user_bob)
        cls.message = channel_anna.message_post(
            body="Hello world",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        cls.message_with_attachment = channel_bob.message_post(
            body="With attachment",
            attachments=[("contract.txt", b"contract data")],
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        channel_anna.message_post(
            body="A reply",
            parent_id=cls.message.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        cls.env["mail.message.reaction"].sudo().create(
            [
                {
                    "message_id": cls.message.id,
                    "content": "\U0001f44d",
                    "partner_id": cls.user_anna.partner_id.id,
                },
                {
                    "message_id": cls.message.id,
                    "content": "\U0001f44d",
                    "partner_id": cls.user_bob.partner_id.id,
                },
                {
                    "message_id": cls.message.id,
                    "content": "\U0001f602",
                    "partner_id": cls.user_bob.partner_id.id,
                },
            ]
        )
        cls.record = cls.env["res.partner"].create({"name": "Contract Customer"})
        cls.record.message_subscribe(partner_ids=cls.user_bob.partner_id.ids)
        cls.env["ir.attachment"].create(
            {
                "name": "chatter.txt",
                "raw": b"chatter data",
                "res_model": "res.partner",
                "res_id": cls.record.id,
            }
        )

    def _run_scenarios(self):
        self.authenticate("contract_anna", "contract_anna")
        payloads = {
            "init_messaging": self.make_jsonrpc_request(
                "/mail/data", {"fetch_params": ["init_messaging"]}
            ),
            "channels_as_member": self.make_jsonrpc_request(
                "/mail/data", {"fetch_params": ["channels_as_member"]}
            ),
            "chatter_thread": self.make_jsonrpc_request(
                "/mail/data",
                {
                    "fetch_params": [
                        [
                            "mixin.mail.thread",
                            {
                                "thread_model": "res.partner",
                                "thread_id": self.record.id,
                                "request_list": ["followers", "attachments"],
                            },
                        ]
                    ]
                },
            ),
            "channel_messages": self.make_jsonrpc_request(
                "/discuss/channel/messages",
                {"channel_id": self.channel.id, "fetch_params": {"limit": 30}},
            )["data"],
            "channel_members": self.make_jsonrpc_request(
                "/discuss/channel/members",
                {"channel_id": self.channel.id, "known_member_ids": []},
            ),
            "message_post": self.make_jsonrpc_request(
                "/mail/message/post",
                {
                    "thread_model": "discuss.channel",
                    "thread_id": self.channel.id,
                    "post_data": {
                        "body": "posted from contract",
                        "message_type": "comment",
                        "subtype_xmlid": "mail.mt_comment",
                    },
                },
            )["store_data"],
            "get_or_create_chat": self.make_jsonrpc_request(
                "/mail/action",
                {
                    "fetch_params": [
                        [
                            "/discuss/get_or_create_chat",
                            {"partners_to": [self.user_bob.partner_id.id]},
                            "contract-data-id",
                        ]
                    ]
                },
            ),
        }
        return {name: payload_shape(payload) for name, payload in payloads.items()}, (
            payloads
        )

    def test_store_shapes(self):
        shapes, payloads = self._run_scenarios()

        channels = payloads["channels_as_member"]["discuss.channel"]
        self.assertIn(
            ("Contract Channel", "channel"),
            {(c.get("name"), c.get("channel_type")) for c in channels},
        )
        posted = payloads["message_post"]["mail.message"]
        self.assertTrue(
            any("posted from contract" in str(m.get("body")) for m in posted)
        )

        if os.environ.get("MAIL_STORE_CONTRACT_REGEN"):
            self.assertTrue(
                self._is_bare_mail_registry(),
                "The contract must be regenerated on a database with only "
                "mail's dependency closure installed (the mock server only "
                "mirrors mail).",
            )
            write_contract(shapes)
            return
        contract = read_contract()
        self.assertIsNotNone(
            contract,
            f"{CONTRACT_FILE} is missing or unparseable; regenerate it with "
            "MAIL_STORE_CONTRACT_REGEN=1 (see module docstring).",
        )
        expected = contract["scenarios"]
        exact = self._is_bare_mail_registry()
        self.maxDiff = None
        self.assertEqual(
            sorted(shapes),
            sorted(expected),
            "Scenario list drifted from the committed contract.",
        )
        drift_msg = (
            "Store payload shape for '%s' drifted from " + CONTRACT_FILE + ". "
            "If the python change is intentional, regenerate the contract "
            "file and make the JS mock server (static/tests/mock_server/) "
            "match."
        )
        for scenario, expected_shape in expected.items():
            with self.subTest(scenario=scenario):
                if exact:
                    self.assertEqual(
                        shapes[scenario], expected_shape, drift_msg % scenario
                    )
                else:
                    for model_name, expected_fields in expected_shape.items():
                        actual = shapes[scenario].get(model_name)
                        self.assertIsNotNone(
                            actual,
                            f"model '{model_name}' missing: " + drift_msg % scenario,
                        )
                        self.assertFalse(
                            set(expected_fields) - set(actual),
                            f"fields removed on '{model_name}': "
                            + drift_msg % scenario,
                        )

    STORE_NEUTRAL_MODULES = frozenset(
        {
            "api_doc",
            "auth_passkey",
            "auth_signup",
            "auth_totp",
            "auth_totp_mail",
            "base_import",
            "base_import_module",
            "base_install_request",
            "google_gmail",
            "iap",
            "iap_mail",
            "mail_bot",
            "microsoft_outlook",
            "phone_validation",
            "privacy_lookup",
            "rpc",
            "sms",
            "snailmail",
            "web_tour",
            "web_unsplash",
        }
    )

    def _is_bare_mail_registry(self):
        modules = self.env["ir.module.module"].search([("state", "=", "installed")])
        by_name = {module.name: module for module in modules}
        closure, todo = set(), ["mail"]
        while todo:
            name = todo.pop()
            if name in closure or name not in by_name:
                continue
            closure.add(name)
            todo += by_name[name].dependencies_id.mapped("name")
        return not (set(by_name) - closure - self.STORE_NEUTRAL_MODULES)
