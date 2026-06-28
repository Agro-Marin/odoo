"""Characterization tests for ORM validation functions.

These tests lock down the current behavior of validation.py so that
refactoring (Phase 2: code quality) doesn't accidentally change semantics.
"""

from odoo.exceptions import AccessError, ValidationError
from odoo.orm.validation import (
    check_method_name,
    check_object_name,
    check_pg_name,
    raise_on_invalid_object_name,
)
from odoo.tests.common import TransactionCase


class TestCheckObjectName(TransactionCase):
    """Test model name validation — returns bool (not exception)."""

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
        """Regression: previous regex ``[a-z0-9_.]+`` matched a single dot."""
        self.assertFalse(check_object_name("."))
        self.assertFalse(check_object_name(".."))
        self.assertFalse(check_object_name("..."))

    def test_rejects_leading_dot(self):
        """Regression: previously accepted ``'.res.partner'``."""
        self.assertFalse(check_object_name(".res"))
        self.assertFalse(check_object_name(".res.partner"))

    def test_rejects_trailing_dot(self):
        """Regression: previously accepted ``'res.partner.'``."""
        self.assertFalse(check_object_name("res."))
        self.assertFalse(check_object_name("res.partner."))

    def test_rejects_consecutive_dots(self):
        """Regression: previously accepted ``'res..partner'``."""
        self.assertFalse(check_object_name("res..partner"))
        self.assertFalse(check_object_name("a..b..c"))

    def test_rejects_leading_digit(self):
        """The FIRST segment must start with a letter or underscore (it
        prefixes the generated PostgreSQL table name, an SQL identifier
        which forbids digit-leading names).  Subsequent segments may
        start with a digit because they only join into the table name
        via ``_`` — e.g. ``l10n_us.1099_box`` → table ``l10n_us_1099_box``.
        """
        self.assertFalse(check_object_name("1invalid"))
        self.assertTrue(check_object_name("res.1invalid"))

    def test_accepts_leading_underscore(self):
        """Underscore is allowed as a segment start (matches PG identifier rules)."""
        self.assertTrue(check_object_name("_internal"))
        self.assertTrue(check_object_name("module._internal"))


class TestRegistrationValidatorsSurviveOptO(TransactionCase):
    """Registration-time validators (``_validate_rec_name``,
    ``_validate_active_name``, ``_build_table_objects``, ``add_to_registry``,
    ``_init_model_class_attributes``, ``_prepare_setup``) used to be
    ``assert`` statements that disappeared under ``python -O``.  They are
    now ``raise TypeError`` so the contract holds at every optimization level.

    These tests call the helpers with intentionally malformed inputs and
    expect a ``TypeError`` regardless of ``__debug__``.
    """

    def test_validate_rec_name_rejects_unknown_field(self):
        from odoo.orm.registration import _validate_rec_name
        cls = type("FakeModel", (), {
            "_name": "fake.model",
            "_rec_name": "no_such_field",
            "_fields": {},
        })
        with self.assertRaises(TypeError):
            _validate_rec_name(cls)

    def test_validate_active_name_rejects_unknown_field(self):
        from odoo.orm.registration import _validate_active_name
        cls = type("FakeModel", (), {
            "_name": "fake.model",
            "_active_name": "active",
            "_fields": {},  # 'active' is not present
        })
        with self.assertRaises(TypeError):
            _validate_active_name(cls)

    def test_validate_active_name_rejects_unsupported_name(self):
        from odoo.orm.registration import _validate_active_name
        # Field is present, but the name is neither 'active' nor 'x_active'
        cls = type("FakeModel", (), {
            "_name": "fake.model",
            "_active_name": "is_active",
            "_fields": {"is_active": object()},
        })
        with self.assertRaises(TypeError):
            _validate_active_name(cls)

    def test_add_to_registry_rejects_non_definition(self):
        """``add_to_registry`` must reject a non-MetaModel input even under -O."""
        from odoo.orm.registration import add_to_registry
        with self.assertRaises(TypeError):
            add_to_registry(self.env.registry, type("NotAModel", (), {}))

    def test_setup_detects_circular_inherits(self):
        """``_setup`` must raise on a circular ``_inherits`` chain rather
        than recursing until Python's stack overflows.

        Simulates the cycle by calling ``_setup`` on a class whose
        ``_setup_in_progress__`` marker is already set (the same condition
        the recursion would create at runtime).
        """
        from odoo.orm.registration import _setup
        # Pick any registered model and pretend its setup is mid-flight.
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
    """Test the exception-raising wrapper."""

    def test_valid_name_no_error(self):
        # Should not raise
        raise_on_invalid_object_name("res.partner")

    def test_invalid_name_raises(self):
        with self.assertRaises(ValueError):
            raise_on_invalid_object_name("Invalid Name!")


class TestCheckPgName(TransactionCase):
    """Test PostgreSQL identifier validation — raises ValidationError."""

    def test_valid_simple(self):
        # Should not raise
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
        # PostgreSQL folds unquoted identifiers to lowercase, so accepting
        # ``MyTable`` would silently collide with ``mytable``.  Matches the
        # rule already documented for ``check_object_name``.
        with self.assertRaises(ValidationError):
            check_pg_name("MyTable")
        with self.assertRaises(ValidationError):
            check_pg_name("ALL_CAPS")
        with self.assertRaises(ValidationError):
            check_pg_name("camelCase")


class TestCheckMethodName(TransactionCase):
    """Test RPC method name validation — raises AccessError for private methods."""

    def test_public_method_allowed(self):
        # Should not raise
        check_method_name("read")

    def test_private_method_blocked(self):
        with self.assertRaises(AccessError):
            check_method_name("_private_method")

    def test_dunder_method_blocked(self):
        with self.assertRaises(AccessError):
            check_method_name("__dunder__")

    def test_init_blocked(self):
        """The 'init' method is explicitly blocked for RPC."""
        with self.assertRaises(AccessError):
            check_method_name("init")

    def test_public_with_numbers(self):
        check_method_name("action_confirm_2")

    def test_private_with_embedded_newline_blocked(self):
        """A private name with an embedded newline must still be rejected
        (a regex anchored with ``$``/``.`` would let it slip through)."""
        with self.assertRaises(AccessError):
            check_method_name("_secret\nx")
