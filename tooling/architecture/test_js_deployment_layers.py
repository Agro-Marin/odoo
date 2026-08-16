from pathlib import Path

import js_deployment_layers as jdl
import pytest


def test_every_layer_ships_somewhere():
    assert jdl.LAYER_BUNDLES
    for layer, bundles in jdl.LAYER_BUNDLES.items():
        assert bundles, f"{layer} ships nowhere, so nothing may ever import it"


def test_common_is_the_only_layer_shipping_everywhere():
    everywhere = {
        layer
        for layer, b in jdl.LAYER_BUNDLES.items()
        if b == {jdl.BACKEND, jdl.PUBLIC, jdl.PORTAL}
    }
    assert everywhere == {"common"}


def test_web_and_public_are_disjoint():
    assert not (jdl.LAYER_BUNDLES["web"] & jdl.LAYER_BUNDLES["public"])


def test_public_web_and_web_portal_overlap_only_in_the_backend():
    assert jdl.LAYER_BUNDLES["public_web"] & jdl.LAYER_BUNDLES["web_portal"] == {
        jdl.BACKEND
    }


def test_layer_of_finds_a_segment_anywhere_in_the_path():
    assert jdl.layer_of("core/common/store_service.js") == "common"
    assert jdl.layer_of("discuss/core/public_web/thread_model_patch.js") == "public_web"
    assert jdl.layer_of("chatter/web_portal/chatter.js") == "web_portal"


def test_layer_of_ignores_names_that_merely_contain_a_layer():
    assert jdl.layer_of("core/commonly/x.js") is None
    assert jdl.layer_of("model/record.js") is None
    assert jdl.layer_of("views/web_extra/x.js") is None


def test_layer_of_does_not_match_a_bare_filename():
    assert jdl.layer_of("utils/web.js") is None


@pytest.mark.parametrize(
    ("spec", "addon", "rel", "expected"),
    [
        ("@mail/core/web/x", "im_livechat", "core/common/y.js", "mail/core/web/x"),
        ("./z", "mail", "core/common/y.js", "mail/core/common/z"),
        ("../web/z", "mail", "core/common/y.js", "mail/core/web/z"),
        ("@odoo/owl", "mail", "core/common/y.js", None),
        ("@web/../lib/x", "mail", "core/common/y.js", None),
        ("luxon", "mail", "core/common/y.js", None),
        ("../../../x", "mail", "core/y.js", None),
    ],
)
def test_resolve(spec, addon, rel, expected):
    assert jdl.resolve(spec, addon, rel) == expected


def _tree(tmp_path: Path, files: dict[str, str]):
    out = []
    for key, source in files.items():
        addon, _, rel = key.partition(":")
        src = tmp_path / "addons" / addon / "static" / "src"
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf8")
        out.append((addon, src, path))
    return out


FORBIDDEN = [
    ("common", "public_web"),
    ("common", "web_portal"),
    ("common", "web"),
    ("common", "public"),
    ("public_web", "web_portal"),
    ("public_web", "web"),
    ("public_web", "public"),
    ("web_portal", "public_web"),
    ("web_portal", "web"),
    ("web_portal", "public"),
    ("web", "public"),
    ("public", "web_portal"),
    ("public", "web"),
]

ALLOWED = [
    ("common", "common"),
    ("public_web", "common"),
    ("public_web", "public_web"),
    ("web_portal", "common"),
    ("web_portal", "web_portal"),
    ("web", "common"),
    ("web", "public_web"),
    ("web", "web_portal"),
    ("web", "web"),
    ("public", "common"),
    ("public", "public_web"),
    ("public", "public"),
]


@pytest.mark.parametrize(("src_layer", "target_layer"), FORBIDDEN)
def test_forbidden_edges_are_reported(tmp_path, src_layer, target_layer):
    files = _tree(
        tmp_path,
        {
            f"mail:{src_layer}/a.js": f'import "@mail/{target_layer}/b";\n',
            f"mail:{target_layer}/b.js": "export const b = 1;\n",
        },
    )
    new, known = jdl.check(files)
    assert not known
    assert len(new) == 1, f"{src_layer} -> {target_layer} should be a violation"
    assert new[0].module_layer == src_layer
    assert new[0].imports_layer == target_layer
    assert new[0].missing, "a violation must name the contexts that would break"


@pytest.mark.parametrize(("src_layer", "target_layer"), ALLOWED)
def test_allowed_edges_are_silent(tmp_path, src_layer, target_layer):
    files = _tree(
        tmp_path,
        {
            f"mail:{src_layer}/a.js": f'import "@mail/{target_layer}/b";\n',
            f"mail:{target_layer}/b.js": "export const b = 1;\n",
        },
    )
    new, _ = jdl.check(files)
    assert not new, f"{src_layer} -> {target_layer} is legal and must not fire"


def test_the_two_lists_together_cover_every_ordered_pair():
    layers = sorted(jdl.LAYER_BUNDLES)
    every = {(a, b) for a in layers for b in layers}
    assert set(FORBIDDEN) | set(ALLOWED) == every


def test_cross_addon_edges_are_governed(tmp_path):
    files = _tree(
        tmp_path,
        {
            "im_livechat:common/a.js": 'import "@mail/core/web/b";\n',
            "mail:core/web/b.js": "export const b = 1;\n",
        },
    )
    new, _ = jdl.check(files)
    assert len(new) == 1
    assert new[0].module == "im_livechat/common/a"
    assert new[0].imports == "mail/core/web/b"


def test_relative_imports_are_governed(tmp_path):
    files = _tree(
        tmp_path,
        {
            "mail:core/common/a.js": 'import "../web/b";\n',
            "mail:core/web/b.js": "export const b = 1;\n",
        },
    )
    new, _ = jdl.check(files)
    assert len(new) == 1
    assert new[0].imports_layer == "web"


def test_type_only_imports_create_no_edge(tmp_path):
    files = _tree(
        tmp_path,
        {
            "mail:core/common/a.js": (
                '/** @import { X } from "@mail/core/web/b" */\n'
                '// import "@mail/core/web/b";\n'
                "export const a = 1;\n"
            ),
            "mail:core/web/b.js": "export const b = 1;\n",
        },
    )
    new, _ = jdl.check(files)
    assert not new


def test_unlayered_directories_are_not_governed():
    for rel in ("model/record.js", "webclient/webclient.js", "views/fields/x.js"):
        assert jdl.layer_of(rel) is None, rel


def test_known_violations_is_empty():
    assert jdl.KNOWN_VIOLATIONS == ()
    for k in jdl.KNOWN_VIOLATIONS:  # pragma: no cover - guards a future entry
        assert k.reason.strip()
