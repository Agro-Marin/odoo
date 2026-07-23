"""DB-free drift guard for the ``odoo.http`` re-export surface.

The package split (monolithic ``http.py`` → ``odoo/http/``) preserves backward
compatibility through hand-maintained imports + ``__all__`` in ``__init__.py``.
This pins that surface so a future refactor can't silently drop a name that
addons import. Run via ``pytest odoo/http/tests``.
"""

import odoo.http


def test_all_names_resolve():
    missing = [n for n in odoo.http.__all__ if not hasattr(odoo.http, n)]
    assert not missing, f"odoo.http.__all__ names missing from the module: {missing}"


def test_all_has_no_duplicates():
    dupes = {n for n in odoo.http.__all__ if odoo.http.__all__.count(n) > 1}
    assert not dupes, f"duplicate names in odoo.http.__all__: {dupes}"
