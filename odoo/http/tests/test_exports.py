import types

import odoo.http


def test_all_names_resolve():
    missing = [n for n in odoo.http.__all__ if not hasattr(odoo.http, n)]
    assert not missing, f"odoo.http.__all__ names missing from the module: {missing}"


def test_all_has_no_duplicates():
    dupes = {n for n in odoo.http.__all__ if odoo.http.__all__.count(n) > 1}
    assert not dupes, f"duplicate names in odoo.http.__all__: {dupes}"


def test_every_public_name_is_declared_in_all():
    """The other direction, which nothing checked.

    `__init__` re-exports the package's public API, so a name it binds is one
    it means to publish -- and a name it publishes but does not declare is
    invisible to `from odoo.http import *`, to a type checker, and to anyone
    reading `__all__` to learn the surface. Two shipped that way: the openapi
    builders were never re-exported at all while `__init__` and the README both
    claimed every symbol was, and `_session_identifier_re` was re-exported
    without being declared.
    """
    declared = set(odoo.http.__all__)
    published = {
        name
        for name, value in vars(odoo.http).items()
        if not name.startswith("__") and not isinstance(value, types.ModuleType)
    }
    undeclared = sorted(published - declared)
    assert not undeclared, (
        f"reachable as odoo.http.<name> but absent from __all__: {undeclared}. "
        f"Declare them, or stop re-exporting them from __init__."
    )
