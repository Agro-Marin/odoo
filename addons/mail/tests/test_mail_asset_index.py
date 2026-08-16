import pathlib

from odoo.tests import BaseCase, tagged

CORE_COMMON = (
    pathlib.Path(__file__).resolve().parents[1] / "static" / "src" / "core" / "common"
)
INDEX = CORE_COMMON / "_models.js"


def _indexed_modules():
    out = set()
    for line in INDEX.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line.startswith("import "):
            continue
        spec = line.split('"')[1]
        out.add(spec.removeprefix("./"))
    return out


@tagged("mail_asset_index", "post_install", "-at_install")
class TestModelsIndexIsComplete(BaseCase):
    def test_every_model_file_is_indexed(self):
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
        indexed = _indexed_modules()
        stale = sorted(name for name in indexed if not (CORE_COMMON / name).is_file())
        self.assertFalse(
            stale, f"core/common/_models.js imports files that do not exist: {stale}"
        )

    def test_every_indexed_file_registers_a_model(self):
        without_register = []
        for name in sorted(_indexed_modules()):
            path = CORE_COMMON / name
            if not path.is_file():
                continue
            if ".register()" not in path.read_text(encoding="utf8"):
                without_register.append(name)
        self.assertFalse(
            without_register,
            "these files are imported by _models.js but call no `.register()`, so "
            f"they add nothing to modelRegistry: {without_register}",
        )
