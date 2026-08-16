import re
from pathlib import Path

import pytest
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_web_machine_doc")
HERE = Path(__file__).resolve().parent
WEB_DOC = ROOT / "addons" / "web" / "machine_doc_v1"
ARCHITECTURE = WEB_DOC / "ARCHITECTURE.md"

NOT_A_GATE = {
    "js_imports": "a shared import parser the gates call, not a gate — no main()",
}


def gates_scanning_web() -> set[str]:

    found = set()
    for path in sorted(HERE.glob("js_*.py")):
        if path.stem.startswith("test_") or path.stem in NOT_A_GATE:
            continue
        source = path.read_text(encoding="utf8")
        if re.search(r'"addons"\s*/\s*"web"|addons/web', source):
            found.add(path.stem)
    return found


class TestGateCoverage:
    def test_the_derivation_finds_a_plausible_number_of_gates(self):
        gates = gates_scanning_web()
        assert len(gates) >= 15, sorted(gates)

    def test_the_map_names_every_gate_that_scans_web(self):
        text = ARCHITECTURE.read_text(encoding="utf8")
        missing = sorted(g for g in gates_scanning_web() if g not in text)
        assert not missing, (
            "addons/web/machine_doc_v1/ARCHITECTURE.md does not name "
            f"{missing}. A reader is told to read this map first, so a gate it "
            "omits is a contract they will trip over rather than work with."
        )

    def test_the_map_names_no_gate_that_does_not_exist(self):
        text = ARCHITECTURE.read_text(encoding="utf8")
        named = set(re.findall(r"`(js_[a-z_]+)\.py`", text))
        absent = sorted(g for g in named if not (HERE / f"{g}.py").is_file())
        assert not absent, f"named but not on disk: {absent}"

    @pytest.mark.parametrize("module", sorted(NOT_A_GATE))
    def test_every_excused_module_is_still_not_a_gate(self, module):
        path = HERE / f"{module}.py"
        assert path.is_file(), f"{module} no longer exists — drop the entry"
        assert "def main(" not in path.read_text(encoding="utf8"), (
            f"{module} grew a main() — it is a gate now, drop the excuse"
        )


class TestDeclaredContracts:
    CONTRACTS = {
        "views/view_config.js": "js_env_config_surface",
        "views/arch_info.js": "js_arch_info_surface",
        "fields/field_record_contract.js": "js_field_record_surface",
    }

    @pytest.mark.parametrize(("source", "gate"), sorted(CONTRACTS.items()))
    def test_the_map_pairs_each_contract_with_its_gate(self, source, gate):
        text = ARCHITECTURE.read_text(encoding="utf8")
        assert source in text, f"{source} is not named by the map"
        assert gate in text, f"{gate} is not named by the map"

    @pytest.mark.parametrize("source", sorted(CONTRACTS))
    def test_each_contract_file_exists(self, source):
        assert (ROOT / "addons" / "web" / "static" / "src" / source).is_file()

    def test_the_field_handle_is_documented_where_widgets_are(self):
        text = ARCHITECTURE.read_text(encoding="utf8")
        assert "field_handle.js" in text
        assert "prototype getter" in text
        assert "super.setup()" in text
