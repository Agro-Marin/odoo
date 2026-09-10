import json
import os
import subprocess

import pytest

from odoo.tools.assets.esbuild import _esbuild_argv, _get_esbuild_path


def _argv(tmp_path, alias_flags, entry):
    return _esbuild_argv(
        _get_esbuild_path(),
        target="es2023",
        out_path=str(tmp_path / "out.js"),
        metafile_path=str(tmp_path / "meta.json"),
        external_specifier_flags=[],
        external_flags=[],
        sourcemap_flags=[],
        alias_flags=alias_flags,
        entry_points=[entry],
    )


def test_the_argv_overrides_every_tsconfig():
    argv = _esbuild_argv(
        "esbuild",
        target="es2023",
        out_path="out.js",
        metafile_path="meta.json",
        external_specifier_flags=[],
        external_flags=[],
        sourcemap_flags=[],
        alias_flags=[],
    )
    assert "--tsconfig-raw={}" in argv


@pytest.mark.skipif(_get_esbuild_path() is None, reason="esbuild is not installed")
def test_a_sibling_tsconfig_cannot_redirect_a_core_spec(tmp_path):
    # The served tree resolves @core to its own copy through the NODE_PATH
    # root the pipeline builds; a sibling repo's tsconfig.json points the
    # same spec at ANOTHER copy, the way every addons repo's tsconfig
    # points "@web/*" at the checkout beside it -- and tsconfig paths
    # outrank NODE_PATH.
    served = tmp_path / "served"
    (served / "core").mkdir(parents=True)
    (served / "core" / "mod.js").write_text("export const marker = 'served';\n")
    other = tmp_path / "other"
    other.mkdir()
    (other / "mod.js").write_text("export const marker = 'other';\n")
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "tsconfig.json").write_text(
        json.dumps(
            {"compilerOptions": {"baseUrl": ".", "paths": {"@core/*": ["../other/*"]}}}
        )
    )
    (sibling / "addon.js").write_text("export { marker } from '@core/mod';\n")
    (served / "entry.js").write_text(
        "import { marker as a } from '@core/mod';\n"
        "import { marker as b } from '../sibling/addon.js';\n"
        "console.log(a, b);\n"
    )
    roots = tmp_path / "roots"
    roots.mkdir()
    (roots / "@core").symlink_to(served / "core", target_is_directory=True)
    argv = _argv(tmp_path, [], "./entry.js")
    subprocess.run(
        argv,
        cwd=served,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "NODE_PATH": str(roots)},
    )
    inputs = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["inputs"]
    mods = sorted(k for k in inputs if k.endswith("mod.js"))
    assert mods == ["core/mod.js"], mods
    assert "other" not in (tmp_path / "out.js").read_text(encoding="utf-8")
