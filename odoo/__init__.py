"""Odoo root package.

This package deliberately imports **nothing** at import time.

Historically it had no ``__init__.py`` at all, and its four public names were
*assigned* onto the namespace-package module object by ``odoo/init.py`` as an
import side effect::

    odoo.SUPERUSER_ID = SUPERUSER_ID
    odoo._ = _
    odoo._lt = _lt
    odoo.Command = Command

Those are the most-imported symbols in the product (``_`` at ~1215 addon sites,
``Command`` ~633, ``SUPERUSER_ID`` ~119) and that arrangement cost three things:

* ``from odoo import _`` raised ImportError unless something had already
  imported ``odoo.init`` -- which happens only as a side effect of importing
  ``odoo.orm``, ``odoo.modules`` or ``odoo.cli.command``. It worked by import
  order, not by construction.
* mypy reported ``[attr-defined]`` for every one of them, so the most-used API
  in the codebase was unverifiable.
* Feeding those assignments meant ``odoo/init.py`` had to import
  ``odoo.tools.translate`` eagerly, which pulls lxml, babel, markupsafe,
  psycopg and werkzeug. Measured: ``import odoo.orm.components.model_graph``
  -- the largest module in the package ADR-0002 calls "pure Python ... testable
  without an Environment, Registry, or database" -- loaded **827** modules
  including all five. With the names resolved lazily here instead, the same
  import loads **133**, and of the five only babel survives. The purity claim
  is now observable through a plain import rather than only through the
  ``sys.modules`` stub in ``odoo/_testing_bootstrap.py``.

  Reproduce both halves with (63 is this interpreter's own baseline)::

      python -c 'import sys; import odoo.orm.components.model_graph; print(len(sys.modules))'

  babel is NOT fixed here and the number should not be read as though it were:
  it arrives because ``odoo/orm/__init__.py`` ends with ``import odoo.init``.
  See the note in ``tooling/ratchet/baselines/ruff.json``.

``__init__.pyi`` carries the static declarations. It is load-bearing: a module
with ``__getattr__`` makes mypy accept *any* attribute, which would silently
mask real errors (it hid four genuine ``Module has no attribute "evented"``
reports when this was first measured). The stub restores exact checking.
"""

from typing import TYPE_CHECKING

__all__ = ["SUPERUSER_ID", "Command", "_", "_lt", "evented"]

#: True when running under the gevent-based long-polling server. Set here so it
#: always exists: ``_monkeypatches/site.py`` flips it during startup, but that
#: module is only imported because ``patch_init()`` sees ``site`` in
#: ``sys.modules``. Under ``python -S`` it never ran, and the five bare
#: ``odoo.evented`` readers raised AttributeError while a sixth
#: (``db/__init__.py``) defensively used ``hasattr`` -- the asymmetry that shows
#: the invariant was never established.
evented: bool = False

if TYPE_CHECKING:
    from odoo.orm.primitives import SUPERUSER_ID as SUPERUSER_ID
    from odoo.orm.primitives import Command as Command
    from odoo.tools.translate import _ as _
    from odoo.tools.translate import _lt as _lt


def __getattr__(name: str):
    if name in ("SUPERUSER_ID", "Command"):
        from odoo.orm import primitives

        return getattr(primitives, name)
    if name in ("_", "_lt"):
        from odoo.tools import translate

        return getattr(translate, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
