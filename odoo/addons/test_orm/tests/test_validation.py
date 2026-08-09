from odoo.exceptions import AccessError, ValidationError
from odoo.orm.validation import (
    check_object_name,
    check_pg_name,
    is_valid_object_name,
)
from odoo.service.model import get_public_method
from odoo.tests.common import TransactionCase


class TestIsValidObjectName(TransactionCase):
    def test_valid_dotted_name(self):
        self.assertTrue(is_valid_object_name("res.partner"))

    def test_valid_underscored_name(self):
        self.assertTrue(is_valid_object_name("my_module.my_model"))

    def test_valid_with_numbers(self):
        self.assertTrue(is_valid_object_name("l10n_mx.tax_rate"))

    def test_rejects_uppercase(self):
        self.assertFalse(is_valid_object_name("Res.Partner"))

    def test_rejects_spaces(self):
        self.assertFalse(is_valid_object_name("res partner"))

    def test_rejects_hyphens(self):
        self.assertFalse(is_valid_object_name("res-partner"))

    def test_rejects_empty(self):
        self.assertFalse(is_valid_object_name(""))

    def test_rejects_lone_dot(self):
        self.assertFalse(is_valid_object_name("."))
        self.assertFalse(is_valid_object_name(".."))
        self.assertFalse(is_valid_object_name("..."))

    def test_rejects_leading_dot(self):
        self.assertFalse(is_valid_object_name(".res"))
        self.assertFalse(is_valid_object_name(".res.partner"))

    def test_rejects_trailing_dot(self):
        self.assertFalse(is_valid_object_name("res."))
        self.assertFalse(is_valid_object_name("res.partner."))

    def test_rejects_consecutive_dots(self):
        self.assertFalse(is_valid_object_name("res..partner"))
        self.assertFalse(is_valid_object_name("a..b..c"))

    def test_rejects_leading_digit(self):
        self.assertFalse(is_valid_object_name("1invalid"))
        self.assertTrue(is_valid_object_name("res.1invalid"))

    def test_accepts_leading_underscore(self):
        self.assertTrue(is_valid_object_name("_internal"))
        self.assertTrue(is_valid_object_name("module._internal"))


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


class TestCheckObjectName(TransactionCase):
    def test_valid_name_no_error(self):
        check_object_name("res.partner")

    def test_invalid_name_raises(self):
        with self.assertRaises(ValidationError):
            check_object_name("Invalid Name!")


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


class TestPrivateMethodsAreNotCallableRemotely(TransactionCase):
    """The RPC gate is ``service.model.get_public_method``, not a name check.

    These assertions used to run against ``orm.validation.check_method_name``,
    a Layer-0 helper with no production caller that raised the same
    "cannot be called remotely" AccessError and so read as the authoritative
    check. It was strictly weaker: it knew nothing of ``@api.private`` or of
    ``safe_eval``'s unsafe-attribute list, so it ALLOWED ``browse`` -- which
    the real gate blocks. Deleted 2026-08-09; its coverage lives here, against
    the code that actually decides.
    """

    def _method(self, name):
        return get_public_method(self.env["res.partner"], name)

    def test_public_method_allowed(self):
        self._method("read")

    def test_private_method_blocked(self):
        with self.assertRaises(AccessError):
            self._method("_private_method_that_does_not_exist")

    def test_dunder_method_blocked(self):
        with self.assertRaises(AccessError):
            self._method("__init__")

    def test_init_blocked(self):
        """``init`` is public by name; ``@api.private`` on ``BaseModel.init``
        is what blocks it, and the MRO walk covers every addon override."""
        with self.assertRaises(AccessError):
            self._method("init")

    def test_api_private_method_blocked(self):
        with self.assertRaises(AccessError):
            self._method("browse")

    def test_unknown_method_is_an_attribute_error(self):
        with self.assertRaises(AttributeError):
            self._method("no_such_method_at_all")
