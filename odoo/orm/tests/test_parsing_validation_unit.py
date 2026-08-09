import pytest

from odoo.exceptions import ValidationError
from odoo.orm.parsing import (
    _PARSE_CACHE_MAXSIZE,
    fix_import_export_id_paths,
    parse_field_expr,
)
from odoo.orm.validation import (
    check_object_name,
    check_pg_name,
    is_manual_name,
    is_valid_object_name,
)


class TestParseFieldExpr:
    @pytest.mark.parametrize(
        ("expr", "expected"),
        [
            ("name", ("name", None)),
            ("partner_id", ("partner_id", None)),
            ("properties.color", ("properties", "color")),
            ("properties.color.shade", ("properties", "color.shade")),
            ("a.b.c.d", ("a", "b.c.d")),
        ],
    )
    def test_valid_expressions(self, expr, expected):
        assert parse_field_expr(expr) == expected

    @pytest.mark.parametrize(
        "expr",
        [
            "",
            ".",
            ".color",
            "field.",
            "a..b",
            "a.b..c",
            "a.b.",
        ],
    )
    def test_malformed_dot_expressions_rejected(self, expr):
        with pytest.raises(ValueError, match="Invalid field expression"):
            parse_field_expr(expr)

    def test_lru_cache_is_bounded(self):
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
            ("partner_id.id", ("partner_id", ".id")),
            ("partner_id:id", ("partner_id", "id")),
            ("partner_id/name", ("partner_id", "name")),
            ("line_ids/partner_id.id", ("line_ids", "partner_id", ".id")),
            ("line_ids/partner_id:id", ("line_ids", "partner_id", "id")),
        ],
    )
    def test_normalization(self, fieldname, expected):
        assert fix_import_export_id_paths(fieldname) == expected

    def test_id_substitution_is_token_based(self):
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
        check_pg_name("table$1")
        check_pg_name("a" * 63)

    def test_64_chars_rejected(self):
        with pytest.raises(ValidationError, match="too long"):
            check_pg_name("a" * 64)

    @pytest.mark.parametrize(
        "name",
        [
            "MyTable",
            "1table",
            "$table",
            "res-partner",
            "res partner",
            "res.partner",
            "",
            "name\nx",
            "name\n\n",
        ],
    )
    def test_invalid_characters_rejected(self, name):
        with pytest.raises(ValidationError, match="Invalid characters"):
            check_pg_name(name)

    def test_trailing_newline_is_rejected(self):
        with pytest.raises(ValidationError, match="Invalid characters"):
            check_pg_name("name\n")
        assert is_valid_object_name("res.partner\n") is False

    def test_length_is_checked_after_characters(self):
        with pytest.raises(ValidationError, match="Invalid characters"):
            check_pg_name("A" * 64)


class TestObjectAndManualNames:
    @pytest.mark.parametrize(
        ("name", "ok"),
        [
            ("res.partner", True),
            ("l10n_us.1099_box", True),
            ("base", True),
            ("1invalid", False),
            ("Res.Partner", False),
            ("res..partner", False),
            (".partner", False),
            ("res.partner.", False),
        ],
    )
    def test_is_valid_object_name(self, name, ok):
        assert is_valid_object_name(name) is ok

    @pytest.mark.parametrize(
        ("name", "ok"),
        [
            ("res.partner", True),
            ("base", True),
            ("Res.Partner", False),
            ("res..partner", False),
        ],
    )
    def test_check_object_name_raises_where_the_predicate_is_false(self, name, ok):
        """The raising half of the pair, and the same ValidationError as
        ``check_pg_name`` -- it raised ``ValueError`` under its old name
        ``raise_on_invalid_object_name`` until 2026-08-09."""
        if ok:
            assert check_object_name(name) is None
        else:
            with pytest.raises(ValidationError, match="is not valid"):
                check_object_name(name)

    def test_is_manual_name(self):
        assert is_manual_name("x_custom_field")
        assert not is_manual_name("custom_field")
