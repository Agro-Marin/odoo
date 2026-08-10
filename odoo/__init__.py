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
