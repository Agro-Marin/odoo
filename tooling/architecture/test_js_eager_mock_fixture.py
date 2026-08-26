import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import js_eager_mock_fixture as gate


def write(tmp_path, addon, name, body):
    d = tmp_path / addon / "static" / "tests" / "unit" / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")
    return tmp_path


FOREIGN_IMPORT = (
    'import { PosConfig } from "@point_of_sale/../tests/unit/data/pos_config.data";\n'
)


class TestReported:
    def test_a_foreign_records_assignment_at_module_scope(self, tmp_path):
        write(
            tmp_path,
            "pos_x",
            "pos_config.data.js",
            FOREIGN_IMPORT + "PosConfig._records = PosConfig._records.map((r) => r);\n",
        )
        found = gate.measure([tmp_path])
        assert [f.binding for f in found] == ["PosConfig"]
        assert found[0].shape == "_records at module scope"

    def test_push_and_splice_are_the_same_mutation(self, tmp_path):
        write(
            tmp_path,
            "pos_x",
            "a.data.js",
            FOREIGN_IMPORT + "PosConfig._records.push({});\n",
        )
        write(
            tmp_path,
            "pos_y",
            "b.data.js",
            FOREIGN_IMPORT + "PosConfig._records.splice(0, 1);\n",
        )
        assert len(gate.measure([tmp_path])) == 2

    def test_patching_a_shared_list_with_an_array(self, tmp_path):
        write(
            tmp_path,
            "pos_x",
            "m.data.js",
            'import { hootPosModels } from "@point_of_sale/../tests/unit/data/x";\n'
            "patch(hootPosModels, [...hootPosModels, Thing]);\n",
        )
        found = gate.measure([tmp_path])
        assert [f.shape for f in found] == ["patch() of the imported binding itself"]


class TestNotReported:
    def test_a_wrapped_mutation_is_the_whole_point_of_the_gate(self, tmp_path):
        write(
            tmp_path,
            "pos_x",
            "pos_config.data.js",
            FOREIGN_IMPORT
            + "export const applyXRecords = () => {\n"
            + "    PosConfig._records = PosConfig._records.map((r) => r);\n};\n",
        )
        assert gate.measure([tmp_path]) == []

    def test_an_own_addon_binding_leaks_into_nobody(self, tmp_path):
        write(
            tmp_path,
            "pos_x",
            "pos_config.data.js",
            'import { PosConfig } from "@pos_x/../tests/unit/data/pos_config.data";\n'
            "PosConfig._records = [];\n",
        )
        assert gate.measure([tmp_path]) == []

    def test_prototype_extension_composes_through_super(self, tmp_path):
        write(
            tmp_path,
            "pos_x",
            "p.data.js",
            FOREIGN_IMPORT
            + "patch(PosConfig.prototype, {\n    f() { return 1; },\n});\n",
        )
        assert gate.measure([tmp_path]) == []

    def test_helper_object_extension_is_the_same_shape_as_a_prototype(self, tmp_path):
        # im_livechat and website extend @mail's mailDataHelpers this way.
        write(
            tmp_path,
            "pos_x",
            "h.data.js",
            'import { mailDataHelpers } from "@mail/../tests/mock_server/mail_mock_server";\n'
            "patch(mailDataHelpers, {\n    _process(store) { super._process(store); },\n});\n",
        )
        assert gate.measure([tmp_path]) == []

    def test_an_equality_comparison_is_not_an_assignment(self, tmp_path):
        write(
            tmp_path,
            "pos_x",
            "c.data.js",
            FOREIGN_IMPORT + "PosConfig._records == other;\n",
        )
        assert gate.measure([tmp_path]) == []


class TestContract:
    def test_an_empty_tree_is_refused_rather_than_reported_as_zero(self, tmp_path):
        with pytest.raises(RuntimeError):
            gate.measure([tmp_path])

    def test_the_repo_reads_zero(self):
        assert gate.measure([gate.ROOT / "addons"]) == []
