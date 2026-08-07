from odoo.exceptions import AccessError, ValidationError
from odoo.orm.validation import (
    check_method_name,
    check_object_name,
    check_pg_name,
    raise_on_invalid_object_name,
)
from odoo.tests.common import TransactionCase


class TestCheckObjectName(TransactionCase):
    def test_valid_dotted_name(self):
        self.assertTrue(check_object_name("res.partner"))

    def test_valid_underscored_name(self):
        self.assertTrue(check_object_name("my_module.my_model"))

    def test_valid_with_numbers(self):
        self.assertTrue(check_object_name("l10n_mx.tax_rate"))

    def test_rejects_uppercase(self):
        self.assertFalse(check_object_name("Res.Partner"))

    def test_rejects_spaces(self):
        self.assertFalse(check_object_name("res partner"))

    def test_rejects_hyphens(self):
        self.assertFalse(check_object_name("res-partner"))

    def test_rejects_empty(self):
        self.assertFalse(check_object_name(""))

    def test_rejects_lone_dot(self):
        self.assertFalse(check_object_name("."))
        self.assertFalse(check_object_name(".."))
        self.assertFalse(check_object_name("..."))

    def test_rejects_leading_dot(self):
        self.assertFalse(check_object_name(".res"))
        self.assertFalse(check_object_name(".res.partner"))

    def test_rejects_trailing_dot(self):
        self.assertFalse(check_object_name("res."))
        self.assertFalse(check_object_name("res.partner."))

    def test_rejects_consecutive_dots(self):
        self.assertFalse(check_object_name("res..partner"))
        self.assertFalse(check_object_name("a..b..c"))

    def test_rejects_leading_digit(self):
        self.assertFalse(check_object_name("1invalid"))
        self.assertTrue(check_object_name("res.1invalid"))

    def test_accepts_leading_underscore(self):
        self.assertTrue(check_object_name("_internal"))
        self.assertTrue(check_object_name("module._internal"))


class TestRegistrationValidatorsSurviveOptO(TransactionCase):
    def test_validate_rec_name_rejects_unknown_field(self):
        from odoo.orm.registration import _validate_rec_name

        cls = type(
            "FakeModel",
            (),
            {
                "_name": "fake.model",
                "_rec_name": "no_such_field",
                "_fields": {},
            },
        )
        with self.assertRaises(TypeError):
            _validate_rec_name(cls)

    def test_validate_active_name_rejects_unknown_field(self):
        from odoo.orm.registration import _validate_active_name

        cls = type(
            "FakeModel",
            (),
            {
                "_name": "fake.model",
                "_active_name": "active",
                "_fields": {},
            },
        )
        with self.assertRaises(TypeError):
            _validate_active_name(cls)

    def test_validate_active_name_rejects_unsupported_name(self):
        from odoo.orm.registration import _validate_active_name

        cls = type(
            "FakeModel",
            (),
            {
                "_name": "fake.model",
                "_active_name": "is_active",
                "_fields": {"is_active": object()},
            },
        )
        with self.assertRaises(TypeError):
            _validate_active_name(cls)

    def test_add_to_registry_rejects_non_definition(self):
        from odoo.orm.registration import add_to_registry

        with self.assertRaises(TypeError):
            add_to_registry(self.env.registry, type("NotAModel", (), {}))

    def test_setup_detects_circular_inherits(self):
        from odoo.orm.registration import _setup

        cls = self.env.registry["res.partner"]
        original_done = cls._setup_done__
        cls._setup_done__ = False
        cls._setup_in_progress__ = True
        try:
            with self.assertRaises(TypeError) as ctx:
                _setup(cls, self.env)
            self.assertIn("Circular _inherits", str(ctx.exception))
        finally:
            cls._setup_in_progress__ = False
            cls._setup_done__ = original_done


class TestRaiseOnInvalidObjectName(TransactionCase):
    def test_valid_name_no_error(self):
        raise_on_invalid_object_name("res.partner")

    def test_invalid_name_raises(self):
        with self.assertRaises(ValueError):
            raise_on_invalid_object_name("Invalid Name!")


class TestCheckPgName(TransactionCase):
    def test_valid_simple(self):
        check_pg_name("my_table")

    def test_valid_with_dollar(self):
        check_pg_name("my_table$1")

    def test_rejects_too_long(self):
        with self.assertRaises(ValidationError):
            check_pg_name("a" * 64)

    def test_accepts_63_chars(self):
        check_pg_name("a" * 63)

    def test_rejects_starting_with_number(self):
        with self.assertRaises(ValidationError):
            check_pg_name("1invalid")

    def test_rejects_special_chars(self):
        with self.assertRaises(ValidationError):
            check_pg_name("my-table")

    def test_rejects_uppercase(self):
        with self.assertRaises(ValidationError):
            check_pg_name("MyTable")
        with self.assertRaises(ValidationError):
            check_pg_name("ALL_CAPS")
        with self.assertRaises(ValidationError):
            check_pg_name("camelCase")


class TestCheckMethodName(TransactionCase):
    def test_public_method_allowed(self):
        check_method_name("read")

    def test_private_method_blocked(self):
        with self.assertRaises(AccessError):
            check_method_name("_private_method")

    def test_dunder_method_blocked(self):
        with self.assertRaises(AccessError):
            check_method_name("__dunder__")

    def test_init_blocked(self):
        with self.assertRaises(AccessError):
            check_method_name("init")

    def test_public_with_numbers(self):
        check_method_name("action_confirm_2")

    def test_private_with_embedded_newline_blocked(self):
        with self.assertRaises(AccessError):
            check_method_name("_secret\nx")
