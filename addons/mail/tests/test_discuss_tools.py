from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.mail.tools.discuss import Store


@tagged("post_install", "-at_install")
class TestDiscussTools(TransactionCase):
    def test_010_store_dict(self):
        store = Store()
        store.add_model_values("key1", {"id": 1, "test": True})
        self.assertEqual(store.get_result(), {"key1": [{"id": 1, "test": True}]})

    def test_011_store_dict_update_same_id(self):
        store = Store()
        store.add_model_values("key1", {"id": 1, "test": True})
        store.add_model_values("key1", {"id": 1, "test": False, "abc": 1})
        self.assertEqual(
            store.get_result(), {"key1": [{"id": 1, "test": False, "abc": 1}]}
        )

    def test_012_store_dict_update_multiple_ids(self):
        store = Store()
        store.add_model_values("key1", {"id": 1, "test": True})
        store.add_model_values("key1", {"id": 2, "test": True})
        store.add_model_values("key1", {"id": 2, "test": False, "abc": 1})
        self.assertEqual(
            store.get_result(),
            {"key1": [{"id": 1, "test": True}, {"id": 2, "test": False, "abc": 1}]},
        )

    def test_040_store_invalid(self):
        store = Store()
        with self.assertRaises(AttributeError):
            store.add_model_values("key1", True)

    def test_042_store_invalid_missing_id(self):
        store = Store()
        with self.assertRaises(AssertionError):
            store.add_model_values("key1", {"test": True})

    def test_060_store_data_empty_val(self):
        store = Store()
        store.add_model_values("key1", {})
        self.assertEqual(store.get_result(), {})

    def test_061_store_data_empty_not_empty(self):
        store = Store()
        store.add_model_values("key1", {})
        store.add_model_values("key2", {"id": 1})
        self.assertEqual(store.get_result(), {"key2": [{"id": 1}]})

    def test_075_store_same_related_field_twice(self):
        user = mail_new_test_user(self.env, login="test_user", name="Test User")
        self.assertEqual(
            Store()
            .add(
                user,
                [
                    Store.One("partner_id", "name"),
                    Store.One("partner_id", "country_id"),
                ],
            )
            .get_result(),
            {
                "res.partner": [
                    {
                        "id": user.partner_id.id,
                        "name": "Test User",
                        "country_id": False,
                    },
                ],
                "res.users": [
                    {"id": user.id, "partner_id": user.partner_id.id},
                ],
            },
        )

    def test_110_store_store_singleton(self):
        store = Store()
        store.add_global_values(test=True)
        self.assertEqual(store.get_result(), {"Store": {"test": True}})

    def test_111_store_store_dict_update(self):
        store = Store()
        store.add_global_values(test=True)
        store.add_global_values(test=False, abc=1)
        self.assertEqual(store.get_result(), {"Store": {"test": False, "abc": 1}})

    def test_140_store_store_invalid_bool(self):
        store = Store()
        with self.assertRaises(AttributeError):
            store.add_model_values("key1", True)

    def test_141_store_store_invalid_list(self):
        store = Store()
        with self.assertRaises(AttributeError):
            store.add_model_values("key1", [{"test": True}])

    def test_160_store_store_data_empty_val(self):
        store = Store()
        store.add_global_values()
        self.assertEqual(store.get_result(), {})

    def test_161_store_store_data_empty_not_empty(self):
        store = Store()
        store.add_global_values()
        store.add_model_values("key2", {"id": 1})
        self.assertEqual(store.get_result(), {"key2": [{"id": 1}]})

    def test_210_store_thread_dict(self):
        store = Store()
        store.add_model_values(
            "mixin.mail.thread", {"id": 1, "model": "res.partner", "test": True}
        )
        self.assertEqual(
            store.get_result(),
            {"mixin.mail.thread": [{"id": 1, "model": "res.partner", "test": True}]},
        )

    def test_211_store_thread_dict_update_same_id(self):
        store = Store()
        store.add_model_values(
            "mixin.mail.thread", {"id": 1, "model": "res.partner", "test": True}
        )
        store.add_model_values(
            "mixin.mail.thread",
            {"id": 1, "model": "res.partner", "test": False, "abc": 1},
        )
        self.assertEqual(
            store.get_result(),
            {
                "mixin.mail.thread": [
                    {"id": 1, "model": "res.partner", "test": False, "abc": 1}
                ]
            },
        )

    def test_212_store_thread_dict_update_multiple_ids(self):
        store = Store()
        store.add_model_values(
            "mixin.mail.thread", {"id": 1, "model": "res.partner", "test": True}
        )
        store.add_model_values(
            "mixin.mail.thread", {"id": 2, "model": "res.partner", "test": True}
        )
        store.add_model_values(
            "mixin.mail.thread",
            {"id": 2, "model": "res.partner", "test": False, "abc": 1},
        )
        self.assertEqual(
            store.get_result(),
            {
                "mixin.mail.thread": [
                    {"id": 1, "model": "res.partner", "test": True},
                    {"id": 2, "model": "res.partner", "test": False, "abc": 1},
                ]
            },
        )

    def test_213_store_thread_dict_update_multiple_models(self):
        store = Store()
        store.add_model_values(
            "mixin.mail.thread", {"id": 1, "model": "res.partner", "test": True}
        )
        store.add_model_values(
            "mixin.mail.thread", {"id": 2, "model": "res.partner", "test": True}
        )
        store.add_model_values(
            "mixin.mail.thread",
            {"id": 2, "model": "discuss.channel", "test": True, "abc": 1},
        )
        store.add_model_values(
            "mixin.mail.thread",
            {"id": 2, "model": "discuss.channel", "test": False, "abc": 2},
        )
        store.add_model_values(
            "mixin.mail.thread", {"id": 1, "model": "res.partner", "test": False}
        )
        self.assertEqual(
            store.get_result(),
            {
                "mixin.mail.thread": [
                    {"id": 1, "model": "res.partner", "test": False},
                    {"id": 2, "model": "res.partner", "test": True},
                    {"id": 2, "model": "discuss.channel", "test": False, "abc": 2},
                ]
            },
        )

    def test_240_store_thread_invalid_bool(self):
        store = Store()
        with self.assertRaises(AttributeError):
            store.add_model_values("mixin.mail.thread", True)

    def test_241_store_thread_invalid_list(self):
        store = Store()
        with self.assertRaises(AttributeError):
            store.add_model_values("mixin.mail.thread", [True])

    def test_242_store_thread_invalid_missing_id(self):
        store = Store()
        with self.assertRaises(AssertionError):
            store.add_model_values("mixin.mail.thread", {"model": "res.partner"})

    def test_243_store_thread_invalid_missing_model(self):
        store = Store()
        with self.assertRaises(AssertionError):
            store.add_model_values("mixin.mail.thread", {"id": 1})

    def test_260_store_thread_data_empty_val(self):
        store = Store()
        store.add_model_values("mixin.mail.thread", {})
        self.assertEqual(store.get_result(), {})

    def test_261_store_thread_data_empty_not_empty(self):
        store = Store()
        store.add_model_values("key1", {})
        store.add_model_values("mixin.mail.thread", {"id": 1, "model": "res.partner"})
        self.assertEqual(
            store.get_result(),
            {"mixin.mail.thread": [{"id": 1, "model": "res.partner"}]},
        )

    def test_350_non_list_extra_fields_copy_when_following_relations(self):
        user = new_test_user(self.env, "test_user_350@example.com")
        store = Store()
        store.add(user, Store.One("partner_id", extra_fields="email"))
        self.assertEqual(
            store.get_result()["res.partner"][0]["email"], "test_user_350@example.com"
        )

    def test_355_single_extra_fields_copy_with_records(self):
        user_a = new_test_user(self.env, "test_user_355_a@example.com")
        user_b = new_test_user(self.env, "test_user_355_b@example.com")
        store = Store()
        store.add(
            user_a + user_b,
            Store.One(
                "partner_id",
                [],
                dynamic_fields=lambda user: ["email"] if user == user_a else [],
                extra_fields=["name"],
            ),
        )
        self.assertEqual(
            store.get_result()["res.partner"][0]["email"], "test_user_355_a@example.com"
        )
        self.assertNotIn("email", store.get_result()["res.partner"][1])
