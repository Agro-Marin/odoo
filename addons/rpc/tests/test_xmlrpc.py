import collections
import datetime
import time

import odoo
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.http import _request_stack
from odoo.service import common as auth
from odoo.service import model
from odoo.tests import common
from odoo.tools import DotDict, mute_logger
from odoo.tools.misc import ReadonlyDict

from odoo.addons.base.tests.common import SavepointCaseWithUserDemo


class ReadonlyDictSubclass(ReadonlyDict):
    pass


class TestExternalAPI(SavepointCaseWithUserDemo):
    def test_call_kw(self):
        partner = self.env["res.partner"].create({"name": "MyPartner1"})
        args = (partner.ids, ["name"])
        kwargs = {"context": {"test": True}}
        model.call_kw(self.env["res.partner"], "read", args, kwargs)
        self.assertEqual(kwargs, {"context": {"test": True}})


@common.tagged("post_install", "-at_install")
class TestXMLRPC(common.HttpCase):
    def setUp(self):
        super().setUp()
        self.admin_uid = self.env.ref("base.user_admin").id

        ml_xml = mute_logger("odoo.addons.rpc.controllers.xmlrpc")
        ml_xml.__enter__()
        self.addCleanup(ml_xml.__exit__)

        ml_json = mute_logger("odoo.addons.rpc.controllers.jsonrpc")
        ml_json.__enter__()
        self.addCleanup(ml_json.__exit__)

    def xmlrpc(self, model, method, *args, **kwargs):
        return self.xmlrpc_object.execute_kw(
            common.get_db_name(), self.admin_uid, "admin", model, method, args, kwargs
        )

    def test_01_xmlrpc_login(self):
        db_name = common.get_db_name()
        uid = self.xmlrpc_common.login(db_name, "admin", "admin")
        self.assertEqual(uid, self.admin_uid)

    def test_xmlrpc_ir_model_search(self):
        o = self.xmlrpc_object
        db_name = common.get_db_name()
        ids = o.execute(db_name, self.admin_uid, "admin", "ir.model", "search", [])
        self.assertIsInstance(ids, list)
        ids = o.execute(db_name, self.admin_uid, "admin", "ir.model", "search", [], {})
        self.assertIsInstance(ids, list)

    def test_xmlrpc_datetime(self):
        m = self.env.ref("base.model_res_device_log")
        self.env["ir.model.access"].create(
            {
                "name": "w/e",
                "model_id": m.id,
                "perm_read": True,
                "perm_create": True,
            }
        )

        now = datetime.datetime.now()
        ids = self.xmlrpc(
            "res.device.log",
            "create",
            {"session_identifier": "abc", "first_activity": now, "revoked": False},
        )
        [r] = self.xmlrpc(
            "res.device.log",
            "read",
            ids,
            ["first_activity"],
        )
        self.assertEqual(r["first_activity"], now.isoformat(" ", "seconds"))

    def test_xmlrpc_read_group(self):
        self.xmlrpc_object.execute(
            common.get_db_name(),
            self.admin_uid,
            "admin",
            "res.partner",
            "formatted_read_group",
            [],
            ["parent_id"],
            ["color:sum"],
        )

    def test_xmlrpc_name_search(self):
        self.xmlrpc_object.execute(
            common.get_db_name(),
            self.admin_uid,
            "admin",
            "res.partner",
            "name_search",
            "admin",
        )

    def test_xmlrpc_html_field(self):
        sig = '<p>bork bork bork <span style="font-weight: bork">bork</span><br></p>'
        r = self.env["res.users"].create(
            {"name": "bob", "login": "bob", "signature": sig}
        )
        self.assertEqual(str(r.signature), sig)
        [x] = self.xmlrpc("res.users", "read", r.id, ["signature"])
        self.assertEqual(x["signature"], sig)

    def test_xmlrpc_frozendict_marshalling(self):
        self.env.ref("base.user_admin").tz = "Europe/Brussels"
        ctx = self.xmlrpc_object.execute(
            common.get_db_name(),
            self.admin_uid,
            "admin",
            "res.users",
            "context_get",
        )
        self.assertEqual(ctx["lang"], "en_US")
        self.assertEqual(ctx["tz"], "Europe/Brussels")

    def test_xmlrpc_fields_get_marshalling(self):
        fields = self.xmlrpc(
            "res.partner", "fields_get", ["parent_id"], ["type", "context"]
        )
        self.assertEqual(fields["parent_id"]["type"], "many2one")
        self.assertEqual(fields["parent_id"]["context"], {})

    def test_xmlrpc_readonly_dict_subclass_marshalling(self):
        self.patch(
            self.registry["res.users"],
            "context_get",
            odoo.api.model(lambda *_: ReadonlyDictSubclass({"lang": "en_US"})),
        )
        self.assertEqual(self.xmlrpc("res.users", "context_get"), {"lang": "en_US"})

    def test_xmlrpc_defaultdict_marshalling(self):
        self.patch(
            self.registry["res.users"],
            "context_get",
            odoo.api.model(lambda *_: collections.defaultdict(int)),
        )
        self.assertEqual(self.xmlrpc("res.users", "context_get"), {})

    def test_xmlrpc_remove_control_characters(self):
        record = self.env["res.users"].create(
            {
                "name": "bob with a control character: \x03",
                "login": "bob",
            }
        )
        self.assertEqual(record.name, "bob with a control character: \x03")
        [record_data] = self.xmlrpc("res.users", "read", record.id, ["name"])
        self.assertEqual(record_data["name"], "bob with a control character: ")

    def test_jsonrpc_read_group(self):
        self._json_call(
            common.get_db_name(),
            self.admin_uid,
            "admin",
            "res.partner",
            "formatted_read_group",
            [],
            ["parent_id"],
            ["color:sum"],
        )

    def test_jsonrpc_name_search(self):
        self._json_call(
            common.get_db_name(),
            self.admin_uid,
            "admin",
            "res.partner",
            "name_search",
            "admin",
        )

    def _json_call(self, *args):
        self.url_open(
            f"{self.base_url()}/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "id": None,
                "method": "call",
                "params": {"service": "object", "method": "execute", "args": args},
            },
        )

    def _read_attachment(self, raw, fields, **kwargs):
        attachment = self.env["ir.attachment"].create({"name": "n", "raw": raw})
        [values] = self.xmlrpc(
            "ir.attachment", "read", attachment.ids, fields, **kwargs
        )
        return values

    def test_xmlrpc_attachment_raw_is_base64(self):
        values = self._read_attachment(b"\x01\x09", ["raw"])
        self.assertEqual(
            values["raw"],
            "AQk=",
            "raw must be base64-encoded on read; sending it as text loses the "
            "control characters the marshaller strips, silently corrupting the value",
        )

    def test_xmlrpc_attachment_raw_accepts_non_utf8_content(self):
        # a PNG header: valid file content, invalid UTF-8
        values = self._read_attachment(b"\x89PNG\r\n\x1a\n", ["raw"])
        self.assertEqual(values["raw"], "iVBORw0KGgo=")

    def test_xmlrpc_attachment_raw_and_datas_agree(self):
        values = self._read_attachment(b"\x89PNG\r\n\x1a\n", ["raw", "datas"])
        self.assertEqual(
            values["raw"],
            values["datas"],
            "raw and datas hold the same bytes, so they must serialize the same way",
        )

    def test_xmlrpc_attachment_bin_size_is_not_base64(self):
        values = self._read_attachment(
            b"\x89PNG\r\n\x1a\n", ["raw"], context={"bin_size": True}
        )
        self.assertEqual(values["raw"], "8.00 bytes")


@common.tagged("post_install", "-at_install")
class TestAPIKeys(common.HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._user = cls.env["res.users"].create(
            {
                "name": "Bylan",
                "login": "byl",
                "password": "ananananan",
                "tz": "Australia/Eucla",
            }
        )

    def setUp(self):
        super().setUp()

        def get_json_data():
            raise ValueError("There is no json here")

        self.http_request_key = self.canonical_tag
        fake_req = DotDict(
            {
                "httprequest": DotDict(
                    {
                        "environ": {"REMOTE_ADDR": "localhost"},
                        "cookies": {common.TEST_CURSOR_COOKIE_NAME: self.canonical_tag},
                        "args": {},
                    }
                ),
                "cookies": {common.TEST_CURSOR_COOKIE_NAME: self.canonical_tag},
                "session": {"identity-check-last": time.time()},
                "geoip": {},
                "get_json_data": get_json_data,
            }
        )
        _request_stack.push(fake_req)
        self.addCleanup(_request_stack.pop)

    def test_trivial(self):
        uid = auth.dispatch(
            "authenticate", [self.env.cr.dbname, "byl", "ananananan", {}]
        )
        self.assertEqual(uid, self._user.id)

        ctx = model.dispatch(
            "execute_kw",
            [self.env.cr.dbname, uid, "ananananan", "res.users", "context_get", []],
        )
        self.assertEqual(ctx["tz"], "Australia/Eucla")

    def test_wrongpw(self):
        uid = auth.dispatch("authenticate", [self.env.cr.dbname, "byl", "aws", {}])
        self.assertFalse(uid)
        with self.assertRaises(AccessDenied):
            model.dispatch(
                "execute_kw",
                [
                    self.env.cr.dbname,
                    self._user.id,
                    "aws",
                    "res.users",
                    "context_get",
                    [],
                ],
            )

    def test_key(self):
        env = self.env(user=self._user)
        r = (
            env["res.users.apikeys.description"]
            .create(
                {
                    "name": "a",
                }
            )
            .action_generate_key()
        )
        k = r["context"]["default_key"]

        uid = auth.dispatch(
            "authenticate", [self.env.cr.dbname, "byl", "ananananan", {}]
        )
        self.assertEqual(uid, self._user.id)

        uid = auth.dispatch("authenticate", [self.env.cr.dbname, "byl", k, {}])
        self.assertEqual(uid, self._user.id)

        ctx = model.dispatch(
            "execute_kw", [self.env.cr.dbname, uid, k, "res.users", "context_get", []]
        )
        self.assertEqual(ctx["tz"], "Australia/Eucla")

        api_key = model.call_kw(
            model=self.env["res.users.apikeys.description"],
            name="create",
            args=[{"name": "Name of the key"}],
            kwargs={},
        )
        self.assertTrue(isinstance(api_key, int))

    def test_delete(self):
        env = self.env(user=self._user)
        env["res.users.apikeys.description"].create(
            {
                "name": "b",
            }
        ).action_generate_key()
        env["res.users.apikeys.description"].create(
            {
                "name": "b",
            }
        ).action_generate_key()
        env["res.users.apikeys.description"].create(
            {
                "name": "b",
            }
        ).action_generate_key()
        k0, k1, k2 = env["res.users.apikeys"].search([])

        k0.remove()
        self.assertFalse(k0.exists())

        k1.with_user(self.env.ref("base.user_admin")).remove()
        self.assertFalse(k1.exists())

        u = self.env["res.users"].create(
            {
                "name": "a",
                "login": "a",
                "group_ids": self.env.ref("base.group_user").ids,
            }
        )
        with self.assertRaises(AccessError):
            k2.with_user(u).remove()

    def test_disabled(self):
        env = self.env(user=self._user)
        k = (
            env["res.users.apikeys.description"]
            .create(
                {
                    "name": "b",
                }
            )
            .action_generate_key()["context"]["default_key"]
        )

        self._user.active = False

        with self.assertRaises(AccessDenied):
            model.dispatch(
                "execute_kw",
                [
                    self.env.cr.dbname,
                    self._user.id,
                    "ananananan",
                    "res.users",
                    "context_get",
                    [],
                ],
            )

        with self.assertRaises(AccessDenied):
            model.dispatch(
                "execute_kw",
                [self.env.cr.dbname, self._user.id, k, "res.users", "context_get", []],
            )

    # -- programmatic key management -------------------------------------

    def _expiration(self):
        return odoo.fields.Datetime.now() + datetime.timedelta(hours=1)

    def _make_key(self, name, user=None):
        return (
            self.env["res.users.apikeys.description"]
            .with_user(user or self._user)
            .create({"name": name})
            .action_generate_key()["context"]["default_key"]
        )

    def _enable_programmatic_keys(self, enabled=True, limit=None):
        ICP = self.env["ir.config_parameter"]
        ICP.set_param("base.enable_programmatic_api_keys", "1" if enabled else "0")
        if limit is not None:
            ICP.set_param("base.programmatic_api_keys_limit", str(limit))

    def test_apikey_programmatic_management_is_opt_in(self):
        self._enable_programmatic_keys(False)
        key = self._make_key("first")
        Apikeys = self.env["res.users.apikeys"].with_user(self._user)
        with self.assertRaisesRegex(UserError, "not enabled"):
            Apikeys.generate(key, None, "second", self._expiration())
        with self.assertRaisesRegex(UserError, "not enabled"):
            Apikeys.revoke(key)

    def test_apikey_is_renewed_over_rpc(self):
        self._enable_programmatic_keys()
        db = self.env.cr.dbname
        first = self._make_key("first")

        second = model.dispatch(
            "execute_kw",
            [
                db,
                self._user.id,
                first,
                "res.users.apikeys",
                "generate",
                [first, None, "second", self._expiration()],
            ],
        )
        self.assertNotEqual(second, first)
        self.assertEqual(
            self.env["res.users.apikeys"]
            .search([("user_id", "=", self._user.id)])
            .mapped("name"),
            ["first", "second"],
        )

        # the new key authenticates on its own
        ctx = model.dispatch(
            "execute_kw",
            [db, self._user.id, second, "res.users", "context_get", []],
        )
        self.assertEqual(ctx["tz"], "Australia/Eucla")

        # and it can retire itself, which is the point of a rotation
        self.assertTrue(
            model.dispatch(
                "execute_kw",
                [db, self._user.id, second, "res.users.apikeys", "revoke", [second]],
            )
        )
        with self.assertRaises(AccessDenied):
            model.dispatch(
                "execute_kw",
                [db, self._user.id, second, "res.users", "context_get", []],
            )

        # the key it was issued from is untouched
        ctx = model.dispatch(
            "execute_kw",
            [db, self._user.id, first, "res.users", "context_get", []],
        )
        self.assertEqual(ctx["tz"], "Australia/Eucla")

    def test_apikey_generate_accepts_a_serialized_expiration_date(self):
        self._enable_programmatic_keys()
        first = self._make_key("first")
        expiration = self._expiration().replace(microsecond=0)
        second = (
            self.env["res.users.apikeys"]
            .with_user(self._user)
            .generate(first, None, "second", odoo.fields.Datetime.to_string(expiration))
        )
        self.assertEqual(
            self.env["res.users.apikeys"]
            .search([("user_id", "=", self._user.id), ("name", "=", "second")])
            .expiration_date,
            expiration,
        )
        self.assertTrue(second)

    def test_apikey_generation_is_capped(self):
        self._enable_programmatic_keys(limit=2)
        first = self._make_key("first")
        Apikeys = self.env["res.users.apikeys"].with_user(self._user)
        Apikeys.generate(first, None, "second", self._expiration())
        with self.assertRaisesRegex(UserError, "Limit of 2"):
            Apikeys.generate(first, None, "third", self._expiration())

    def test_apikey_generate_refuses_a_key_of_another_user(self):
        self._enable_programmatic_keys()
        other = self.env["res.users"].create(
            {"name": "Otro", "login": "otro", "password": "anananana"}
        )
        stranger = self._make_key("stranger", user=other)
        with self.assertRaises(AccessDenied):
            self.env["res.users.apikeys"].with_user(self._user).generate(
                stranger, None, "second", self._expiration()
            )
