"""Store serialization contract between Python controllers and the JS mock server.

The hoot mock server (``static/tests/mock_server/``) hand-mirrors the Python
controllers and the ``Store`` serialization protocol (``tools/discuss.py``).
Nothing pins the two implementations together: a server-side payload change
fails no JS test, and mock-server drift silently invalidates the 100+ hoot
suites built on top of it (audit finding F3).

This test is the Python half of the drift gate:

* a fixed scenario (two users, a channel with messages / attachment /
  reactions / a reply, a chatter record with a follower and an attachment) is
  seeded, then the real routes are called over HTTP;
* for every *gated* Store model in each response, the **exact set of field
  names** (union over records, sorted) is compared against the committed
  expectation file ``static/tests/mock_server/contract/store_shapes.js``.

The JS half (``static/tests/mock_server/contract.test.js``) replays the same
scenario against the mock server and asserts the same field-name sets from the
same committed file. Drift in either implementation therefore fails (at least)
one of the two tests, and the diff names the route, model and fields.

Values are deliberately not snapshotted (ids, datetimes and access tokens are
unstable); only a few hand-picked stable values are asserted inline.

The committed shapes describe a **bare ``mail`` install** (the mock server only
mirrors mail). On a registry where modules outside mail's dependency closure
are installed (im_livechat, ai, ...), downstream ``_to_store`` overrides
legitimately *add* fields, so the test degrades to a containment check: every
committed field must still be present (removals and renames — the dangerous,
silent kind of drift — still fail). On a bare-mail registry the match is exact.

To regenerate the expectation file after an intentional protocol change, run
against a database with only mail's dependency closure installed::

    MAIL_STORE_CONTRACT_REGEN=1 odoo-bin ... \
        --test-tags mail_store_contract --stop-after-init

then re-run the tag without the variable (must pass) and run the hoot suite
``@mail/mock_server/contract`` (must pass too before committing).
"""

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
 * - js: mail/static/tests/mock_server/contract.test.js (hoot mock server)
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

# Store models whose shape is pinned. Models outside this list (res.users,
# res.groups, ...) differ legitimately between a real database and the mock
# server fixtures and are ignored.
GATED_MODELS = [
    "DataResponse",
    "MessageReactions",
    "Store",
    "discuss.channel",
    "discuss.channel.member",
    "ir.attachment",
    "mail.followers",
    "mail.message",
    "mail.thread",
    "res.partner",
]


def payload_shape(payload):
    """Reduce a Store payload to ``{model: sorted union of field names}`` for
    gated models only."""
    shape = {}
    for model_name, records in payload.items():
        if model_name not in GATED_MODELS:
            continue
        if isinstance(records, dict):  # singleton (e.g. "Store")
            keys = set(records)
        else:
            keys = {key for record in records for key in record}
        shape[model_name] = sorted(keys)
    return shape


def contract_path():
    """Absolute path of the contract file (which may not exist yet when
    regenerating for the first time)."""
    root, _, relative = CONTRACT_FILE.partition("/static/")
    return Path(file_path(root + "/static")) / relative


def read_contract():
    """Load the committed expectations from the shared .js module.

    The file is ``<header comment> export default <strict JSON>;`` so that the
    hoot side can import it natively while python reads the JSON body.
    """
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
        # chatter thread: a record with a follower and an attachment
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
        """Call the real routes and return ``{scenario: shape}`` plus the raw
        payloads (for the inline stable-value assertions)."""
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
                            "mail.thread",
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

        # A few stable values (structure tests skip values on purpose; these
        # pin the scenario itself so both sides seed the same thing).
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
                    # Modules outside mail may add fields/models; removals
                    # and renames of the committed mail shape still fail.
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

    # Community modules that auto-install alongside mail but define no Store
    # serialization override (no _to_store / _thread_to_store /
    # _init_messaging / add_global_values). Their presence does not change the
    # gated shapes. If one of them grows a Store override, remove it from this
    # list (its addition then correctly demotes the run to containment mode)
    # and mirror the change in the mock server.
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
        """True when every installed module is either in mail's dependency
        closure or a known Store-neutral auto-install, i.e. the running server
        serializes exactly what the mock server mirrors."""
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
