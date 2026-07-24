"""Layer-0 unit tests for :mod:`odoo.orm.parsing` and :mod:`odoo.orm.validation`.

Tier-2 suite (real ``import odoo``, no database — run as ``pytest
odoo/orm/tests``).  Both modules are dependency-free leaves that are reachable
from authenticated RPC (field expressions in domains/read_group specs, method
names in call dispatch), so their rejection paths are security-relevant and
must stay locked:

* ``parse_field_expr``: malformed-dot rejection and the bounded LRU cache;
* ``fix_import_export_id_paths``: the ``.id`` / ``:id`` normalization;
* ``check_pg_name``: the 63-char PostgreSQL identifier limit and the
  character whitelist;
* ``check_method_name``: private-method / ``init`` rejection, including the
  newline defense documented in the implementation.
"""

import pytest

from odoo.exceptions import AccessError, ValidationError
from odoo.orm.parsing import (
    _PARSE_CACHE_MAXSIZE,
    fix_import_export_id_paths,
    parse_field_expr,
)
from odoo.orm.validation import (
    check_method_name,
    check_object_name,
    check_pg_name,
    is_manual_name,
)


class TestParseFieldExpr:
    @pytest.mark.parametrize(
        ("expr", "expected"),
        [
            ("name", ("name", None)),
            ("partner_id", ("partner_id", None)),
            ("properties.color", ("properties", "color")),
            # only the FIRST dot splits: the rest belongs to the property part
            ("properties.color.shade", ("properties", "color.shade")),
            ("a.b.c.d", ("a", "b.c.d")),
        ],
    )
    def test_valid_expressions(self, expr, expected):
        assert parse_field_expr(expr) == expected

    @pytest.mark.parametrize(
        "expr",
        [
            "",  # empty
            ".",  # no field, no property
            ".color",  # leading dot: empty field part
            "field.",  # trailing dot: empty property part
            "a..b",  # empty segment between dots
            "a.b..c",  # empty inner segment in the property part
            "a.b.",  # trailing dot after a property path
        ],
    )
    def test_malformed_dot_expressions_rejected(self, expr):
        with pytest.raises(ValueError, match="Invalid field expression"):
            parse_field_expr(expr)

    def test_lru_cache_is_bounded(self):
        # The parsers are RPC-reachable with unbounded distinct inputs; an
        # unbounded cache would be a memory-exhaustion vector.  The cache is
        # observable through functools' cache_info.
        info = parse_field_expr.cache_info()
        assert info.maxsize == _PARSE_CACHE_MAXSIZE
        for i in range(_PARSE_CACHE_MAXSIZE + 500):
            parse_field_expr(f"field_{i}")
        assert parse_field_expr.cache_info().currsize <= _PARSE_CACHE_MAXSIZE


class TestFixImportExportIdPaths:
    @pytest.mark.parametrize(
        ("fieldname", "expected"),
        [
            ("name", ("name",)),
            ("partner_id.id", ("partner_id", ".id")),  # database id
            ("partner_id:id", ("partner_id", "id")),  # external id
            ("partner_id/name", ("partner_id", "name")),  # plain path
            ("line_ids/partner_id.id", ("line_ids", "partner_id", ".id")),
            ("line_ids/partner_id:id", ("line_ids", "partner_id", "id")),
        ],
    )
    def test_normalization(self, fieldname, expected):
        assert fix_import_export_id_paths(fieldname) == expected

    def test_id_substitution_is_token_based(self):
        # ".id"/":id" convert only as a complete trailing designator (end of
        # name or before "/") — a bare prefix match used to mangle
        # "partner_id.identifier" into ('partner_id', '.identifier').
        assert fix_import_export_id_paths("partner_id.identifier") == (
            "partner_id.identifier",
        )
        assert fix_import_export_id_paths("partner_id:idx") == ("partner_id:idx",)
        assert fix_import_export_id_paths("partner_id.id/name") == (
            "partner_id",
            ".id",
            "name",
        )


class TestCheckPgName:
    def test_valid_names_pass(self):
        check_pg_name("res_partner")
        check_pg_name("_private")
        check_pg_name("table$1")  # $ allowed after the first character
        check_pg_name("a" * 63)  # exactly at the PostgreSQL limit

    def test_64_chars_rejected(self):
        with pytest.raises(ValidationError, match="too long"):
            check_pg_name("a" * 64)

    @pytest.mark.parametrize(
        "name",
        [
            "MyTable",  # uppercase: PostgreSQL folds unquoted identifiers
            "1table",  # cannot start with a digit
            "$table",  # cannot start with $
            "res-partner",  # invalid character
            "res partner",  # whitespace
            "res.partner",  # dot is a model-name separator, not a pg name
            "",  # empty
            "name\nx",  # embedded newline
            "name\n\n",  # two trailing newlines ($ only forgives one)
        ],
    )
    def test_invalid_characters_rejected(self, name):
        with pytest.raises(ValidationError, match="Invalid characters"):
            check_pg_name(name)

    def test_trailing_newline_is_rejected(self):
        # The validation regexes anchor with ``\Z``, not ``$`` — in Python
        # ``$`` also matches just before ONE trailing newline, which used to
        # let ``"name\n"`` validate (the exact trap check_method_name defends
        # against explicitly).
        with pytest.raises(ValidationError, match="Invalid characters"):
            check_pg_name("name\n")
        assert check_object_name("res.partner\n") is False

    def test_length_is_checked_after_characters(self):
        # a 64-char name with invalid characters fails on characters first
        with pytest.raises(ValidationError, match="Invalid characters"):
            check_pg_name("A" * 64)


class TestCheckMethodName:
    @pytest.mark.parametrize("name", ["read", "write", "search_read", "create"])
    def test_public_names_pass(self, name):
        assert check_method_name(name) is None

    @pytest.mark.parametrize(
        "name",
        [
            "init",  # blocked by name
            "_private",
            "_",  # bare underscore is still private
            "__init__",
            # newline defense: a ^...$ regex would let "_secret\nx" through
            # ($ matches before a trailing newline; . does not match newline)
            "_secret\nx",
            "_secret\n",
        ],
    )
    def test_private_and_init_rejected(self, name):
        with pytest.raises(AccessError, match="cannot be called remotely"):
            check_method_name(name)

    def test_init_only_matches_exactly(self):
        # "initialize" is a legitimate public name; only "init" is special
        assert check_method_name("initialize") is None


class TestObjectAndManualNames:
    @pytest.mark.parametrize(
        ("name", "ok"),
        [
            ("res.partner", True),
            ("l10n_us.1099_box", True),  # later segments may start with a digit
            ("base", True),
            ("1invalid", False),  # first segment must not start with a digit
            ("Res.Partner", False),  # uppercase folds in PostgreSQL
            ("res..partner", False),  # empty segment
            (".partner", False),
            ("res.partner.", False),
        ],
    )
    def test_check_object_name(self, name, ok):
        assert check_object_name(name) is ok

    def test_is_manual_name(self):
        assert is_manual_name("x_custom_field")
        assert not is_manual_name("custom_field")
