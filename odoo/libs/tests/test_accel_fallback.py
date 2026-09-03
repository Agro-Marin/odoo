import importlib
import sys
from collections.abc import Sequence
from unittest import mock

import pytest

from odoo.libs import accel, native
from odoo.libs._field_access import _fallback

_FIELD_ACCESS = (
    "batch_cache_fill",
    "batch_cache_filter",
    "batch_cache_get",
    "batch_group_ids",
    "sort_ids_by_cache",
    "to_prefetch_ids",
)


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
                seam = importlib.reload(accel)
                assert seam.NATIVE is False
                assert seam.csv_export is seam.csv_export_python
                assert seam.rows_to_dicts is seam.rows_to_dicts_python
                assert seam.fast_clone is seam.fast_clone_python
                assert seam.origin_ids is seam.origin_ids_python
                for name in _FIELD_ACCESS:
                    assert getattr(seam, name) is getattr(_fallback, name), name
        finally:
            # outside the patch, so the extension is importable again
            importlib.reload(accel)

    def test_with_the_extension_every_name_is_native(self):
        pytest.importorskip("odoo_rust")
        assert accel.NATIVE is True
        for name in accel.__all__:
            if name != "NATIVE":
                assert getattr(accel, name).__module__.startswith("odoo_rust"), name

    def test_the_four_pure_twins_agree_with_the_extension(self):
        pytest.importorskip("odoo_rust")
        headers = ["a", None, 3]  # the native csv_export takes a list of headers
        rows: list[Sequence[object]] = [["=x", None, 1.5], (b"y", False, True)]
        assert accel.csv_export_python(headers, rows) == accel.csv_export(headers, rows)
        names = ("a", "b")  # the native rows_to_dicts takes a tuple of names
        assert accel.rows_to_dicts_python(names, [(1, 2)]) == accel.rows_to_dicts(
            names, [(1, 2)]
        )
        blob = {"a": [1, (2, 3)], "b": {"c": "d"}}
        assert accel.fast_clone_python(blob) == accel.fast_clone(blob)
        assert accel.origin_ids_python((1, 0, 3)) == accel.origin_ids((1, 0, 3))
