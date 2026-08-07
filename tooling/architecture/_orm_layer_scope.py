"""The ORM layer scope shared by the runtime-seam gates.

``env_surface_check`` and ``pool_surface_check`` ask the same question about two
different seams: which ORM module reached Layer 3, and from which layer. They
therefore need the same answer to "what is Layer N", and they used to carry two
byte-identical ``SCOPE`` dicts and two byte-identical ``iter_scope_files``. Both
comments claimed the pair was "deliberately identical so the two reports are
comparable line for line" -- a property nothing enforced, and which had already
lapsed: they diverged on ``Reach.is_private`` (dunder handling) and on whether
``--check`` was required to fail.

Worse, both copies were **incomplete in the same way**, and the gap was the
whole point of the gates. Of the top-level ``odoo/orm/*.py`` modules, eight were
in neither ``SCOPE`` nor ``orm/runtime``:

    __init__  _recordset  _typing  constants  decorators  helpers
    model_test_env  registration

``layer_check`` had already been through exactly this. Its
``orm-helpers-and-registration-stay-below-runtime`` contract exists because
"four were in no LAYERING contract at all ... 1296 of 1987 lines, ~65%", and
``helpers.py`` matters most because "it is imported by 11 Layer-2 mixins, so
anything it imports is reachable from Layer 2 without Layer 2 importing it".
That closed the *import* channel. The ``self.env`` / ``self.pool`` channel --
the one these gates exist for, because it produces no import edge at all --
stayed open in the same modules. Measured when this module landed,
``registration.py`` was reaching three private ``Registry`` members while
``layer_check`` reported the contract clean at zero, because registration.py
imports ``odoo.orm.runtime`` nowhere.

So the scope lives here once, with an explicit exempt list, and
:func:`unclassified_modules` lets each gate's suite assert the list stays
complete. A hand-maintained coverage list is the part that rots; this is the
same guard ``layer_check.test_core_source_covers_every_core_package`` and
``package_index_check.test_every_core_readme_is_classified`` apply to theirs.
"""

from __future__ import annotations

from pathlib import Path

#: Scanned ORM modules and packages, and the layer each one sits at.
#:
#: Layer assignments follow ``layer_check``'s contracts, which are the
#: authoritative statement of the layering:
#:
#: * Layer 0 -- ``orm-layer0-is-foundational`` source
#:   (primitives, parsing, validation, constants, _typing).
#: * Layer 1 -- ``orm-layer1-below-models-and-runtime`` (fields, domain) and
#:   ``orm-seams-stay-below-models-and-runtime`` (_recordset, decorators).
#: * Layer 2 -- ``orm-models-below-runtime`` (models) plus the two modules
#:   ``orm-helpers-and-registration-stay-below-runtime`` pins below runtime.
#:   ``registration.py`` reaches Layers 0-2 and ``helpers.py`` reaches only
#:   ``orm.models.base``, so Layer 2 is the honest label for both.
#: * components -- the strictest expectation of all: it may touch the runtime
#:   seams for nothing whatsoever.
SCOPE: dict[str, str] = {
    "orm/__init__.py": "Layer 0",
    "orm/_typing.py": "Layer 0",
    "orm/constants.py": "Layer 0",
    "orm/primitives.py": "Layer 0",
    "orm/parsing.py": "Layer 0",
    "orm/validation.py": "Layer 0",
    "orm/_recordset.py": "Layer 1",
    "orm/decorators.py": "Layer 1",
    "orm/fields": "Layer 1",
    "orm/domain": "Layer 1",
    "orm/helpers.py": "Layer 2",
    "orm/registration.py": "Layer 2",
    "orm/models": "Layer 2",
    "orm/components": "components",
}

#: The far side of the seam. ``orm/runtime`` OWNS ``Environment`` and
#: ``Registry``; reaching your own internals is not a cross-layer reach.
RUNTIME_PACKAGE = "runtime"

#: In ``odoo/orm/`` but deliberately outside the scope, with the reason.
#: Listed rather than merely absent, so :func:`unclassified_modules` can force
#: the choice for anything new.
EXEMPT: dict[str, str] = {
    "orm/model_test_env.py": (
        "The DB-free test harness. It CONSTRUCTS Environment, Transaction and "
        "Registry by design, so every reach it makes is the thing it exists to "
        "do. layer_check exempts it from "
        "orm-helpers-and-registration-stay-below-runtime for the same reason."
    ),
}


def iter_scope_files(core: Path) -> list[tuple[Path, str]]:
    """``[(path, layer), ...]`` for every file in :data:`SCOPE`.

    Test files are skipped: tests legitimately reach across any boundary, and
    both gates' pins are about production reach.
    """
    out: list[tuple[Path, str]] = []
    for rel, layer in SCOPE.items():
        target = core / rel
        if target.is_dir():
            paths = sorted(target.rglob("*.py"))
        elif target.is_file():
            paths = [target]
        else:
            continue
        for path in paths:
            parts = path.relative_to(core).parts
            if (
                "tests" in parts
                or "__pycache__" in parts
                or path.name.startswith("test_")
            ):
                continue
            out.append((path, layer))
    return out


def unclassified_modules(core: Path) -> list[str]:
    """Members of ``odoo/orm/`` that are neither scoped, exempt, nor runtime.

    The completeness guard. A new top-level ORM module, or a new subpackage,
    cannot silently escape both seam gates: it either gets a layer in
    :data:`SCOPE` or an argued entry in :data:`EXEMPT`.
    """
    orm = core / "orm"
    if not orm.is_dir():
        return []
    classified = set(SCOPE) | set(EXEMPT) | {f"orm/{RUNTIME_PACKAGE}"}
    missing: list[str] = []
    for child in sorted(orm.iterdir()):
        if child.name in ("__pycache__", "tests"):
            continue
        if child.is_dir():
            if not (child / "__init__.py").is_file():
                continue
            rel = f"orm/{child.name}"
        elif child.suffix == ".py":
            rel = f"orm/{child.name}"
        else:
            continue
        if rel not in classified:
            missing.append(rel)
    return missing
