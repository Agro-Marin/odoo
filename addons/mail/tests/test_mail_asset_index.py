"""The ``core/common/_models.js`` side-effect index must list every model file.

``store_service.js`` declares relations by *string* — ``fields.One("res.partner")``
— and ``makeStore()`` resolves those names by iterating ``modelRegistry``. A model
class only reaches that registry when its module is evaluated, and esbuild cannot
see a string, so nothing links ``store_service`` to ``res_partner_model``. The
index exists to force that evaluation.

Its header says "keep this list aligned with ``core/common/*_model.js``", and until
now that was a convention with no enforcement. A forgotten entry is invisible in
the backend bundle (something else usually imports the model) and surfaces only in a
satellite bundle that pulls ``store_service`` transitively -- as a runtime
``Error: No target model X exists`` during service startup on the public page, which
names the model but not the reason.

This test turns the convention into a structural check: it fails in the suite, at
the file that was added, instead of in a browser on a page nobody was testing.

It reads the tree, not the registry, so it needs no database and no bundle.
"""

import pathlib

from odoo.tests import BaseCase, tagged

# ``…/addons/mail/tests/`` -> ``…/addons/mail/static/src/core/common``
CORE_COMMON = (
    pathlib.Path(__file__).resolve().parents[1] / "static" / "src" / "core" / "common"
)
INDEX = CORE_COMMON / "_models.js"


def _indexed_modules():
    """Specifiers imported for side effects by ``_models.js``.

    Parsed rather than regexed on the *statement* level: every line in the file is
    a bare ``import "./x.js";``, so splitting on quotes is exact here, and a future
    named import would show up as an unexpected entry rather than being silently
    accepted.
    """
    out = set()
    for line in INDEX.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line.startswith("import "):
            continue
        # ``import "./activity_model.js";`` -> ``activity_model.js``
        spec = line.split('"')[1]
        out.add(spec.removeprefix("./"))
    return out


@tagged("mail_asset_index", "post_install", "-at_install")
class TestModelsIndexIsComplete(BaseCase):
    def test_every_model_file_is_indexed(self):
        """A ``*_model.js`` in ``core/common/`` that the index misses would only
        fail at runtime, in whichever satellite bundle happens to load the store
        without also importing that model."""
        on_disk = {p.name for p in CORE_COMMON.glob("*_model.js")}
        self.assertTrue(on_disk, f"no *_model.js found under {CORE_COMMON}")
        missing = sorted(on_disk - _indexed_modules())
        self.assertFalse(
            missing,
            "these model files are not imported by core/common/_models.js, so the "
            "classes never register and `makeStore()` raises "
            f"'No target model X exists' in bundles that omit them: {missing}",
        )

    def test_index_lists_nothing_that_is_gone(self):
        """The mirror of the above: a stale entry is a broken import, which fails
        the whole bundle rather than one model."""
        indexed = _indexed_modules()
        stale = sorted(name for name in indexed if not (CORE_COMMON / name).is_file())
        self.assertFalse(
            stale, f"core/common/_models.js imports files that do not exist: {stale}"
        )

    def test_every_indexed_file_registers_a_model(self):
        """The index is for side effects only. A file that registers nothing does
        not belong here -- it would be dead weight in every bundle that includes
        the store, and its presence would suggest the list means something it
        does not."""
        without_register = []
        for name in sorted(_indexed_modules()):
            path = CORE_COMMON / name
            if not path.is_file():
                continue  # reported by test_index_lists_nothing_that_is_gone
            if ".register()" not in path.read_text(encoding="utf8"):
                without_register.append(name)
        self.assertFalse(
            without_register,
            "these files are imported by _models.js but call no `.register()`, so "
            f"they add nothing to modelRegistry: {without_register}",
        )
