import importlib
import sys
from unittest import mock

import pytest

from odoo.libs import accel, native
from odoo.libs._field_access import _fallback


class TestNativeRequired:
    @pytest.mark.parametrize(
        ("environ", "expected"),
        [
            ({}, False),
            ({"CI": "true"}, True),
            ({"CI": "false"}, False),
            ({"ODOO_REQUIRE_NATIVE": "1"}, True),
            ({"ODOO_REQUIRE_NATIVE": "0", "CI": "true"}, False),
            ({"ODOO_REQUIRE_NATIVE": "", "CI": "true"}, False),
        ],
    )
    def test_explicit_setting_wins_over_ci(self, environ, expected):
        assert native.native_required(environ) is expected


class TestTheSeamFallsBack:
    def test_without_the_extension_every_name_is_the_pure_python_twin(self):
        try:
            with mock.patch.dict(sys.modules, {"odoo_rust": None}):
                facade = importlib.reload(sys.modules["odoo.libs._field_access"])
                seam = importlib.reload(accel)
                assert seam.NATIVE is False
                assert seam.csv_export is seam.csv_export_python
                assert seam.rows_to_dicts is seam.rows_to_dicts_python
                assert seam.fast_clone is seam.fast_clone_python
                assert seam.origin_ids is seam.origin_ids_python
                assert facade.batch_cache_get is _fallback.batch_cache_get
                assert seam.batch_cache_get is _fallback.batch_cache_get
                assert seam.to_prefetch_ids is _fallback.to_prefetch_ids
        finally:
            # outside the patch, so the extension is importable again
            importlib.reload(sys.modules["odoo.libs._field_access"])
            importlib.reload(accel)

    def test_with_the_extension_every_name_is_native(self):
        pytest.importorskip("odoo_rust")
        assert accel.NATIVE is True
        for name in ("csv_export", "rows_to_dicts", "fast_clone", "origin_ids"):
            assert getattr(accel, name).__module__.startswith("odoo_rust"), name
        assert accel.batch_cache_get is not _fallback.batch_cache_get

    def test_the_four_pure_twins_agree_with_the_extension(self):
        pytest.importorskip("odoo_rust")
        headers = ["a", "b"]  # the native csv_export takes a list of headers
        rows: list[list[object]] = [["=x", None], [b"y", False]]
        assert accel.csv_export_python(headers, rows) == accel.csv_export(
            headers, [list(r) for r in rows]
        )
        names = ("a", "b")  # the native rows_to_dicts takes a tuple of names
        assert accel.rows_to_dicts_python(names, [(1, 2)]) == accel.rows_to_dicts(
            names, [(1, 2)]
        )
        blob = {"a": [1, (2, 3)], "b": {"c": "d"}}
        assert accel.fast_clone_python(blob) == accel.fast_clone(blob)
        assert accel.origin_ids_python((1, 0, 3)) == accel.origin_ids((1, 0, 3))
