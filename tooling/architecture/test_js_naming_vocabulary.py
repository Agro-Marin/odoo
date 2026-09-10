import textwrap
from pathlib import Path

import pytest
from js_naming_vocabulary import (
    CONTRACT_TREES,
    IDIOM,
    PLATFORM_METHODS,
    definitions,
    is_exempt,
    leading_verb,
    measure,
)

SOURCE = textwrap.dedent(
    """
    export class Thing {
        static _retrieveIdFromData(data) {
            return data;
        }
        async fetchThings() {}
        _buildFormData(formData, { force = false, unmute = true }) {
            return formData;
        }
        onClick = (ev) => {
            fillEmpty(ev.target);
            this.deleteThing(ev);
        };
        get validateNothing() {
            return 1;
        }
    }

    export const helpers = {
        buildOpenChatParams: (resModel, id) => ({ resModel, id }),
        locateFile: function (file) {
            return file;
        },
        deleteProperty: (record, name) => delete record[name],
    };

    export function _generateEmojisOnHtml(html) {}
    const makeThing = (x) => x;
    """
)


def _names(text: str = SOURCE) -> set[str]:
    return {name for name, _line in definitions(text)}


@pytest.mark.parametrize(
    "name",
    [
        "_retrieveIdFromData",
        "fetchThings",
        "_buildFormData",
        "onClick",
        "buildOpenChatParams",
        "locateFile",
        "deleteProperty",
        "_generateEmojisOnHtml",
        "makeThing",
    ],
)
def test_every_definition_shape_is_read(name):
    assert name in _names()


@pytest.mark.parametrize("name", ["fillEmpty", "deleteThing", "if", "return"])
def test_a_call_statement_is_not_a_definition(name):
    assert name not in _names()


@pytest.mark.parametrize(
    ("name", "verb"),
    [
        ("_retrieveIdFromData", "retrieve"),
        ("$buildThing", "build"),
        ("fetchThings", "fetch"),
        ("fetch", None),
        ("_", None),
        ("Thing", None),
    ],
)
def test_the_leading_verb_ignores_the_private_prefix(name, verb):
    assert leading_verb(name) == verb


@pytest.mark.parametrize("verb", ["find", "filter", "fetch", "make", "assign"])
def test_javascript_reservations_are_exempt_by_word(verb):
    assert verb in IDIOM
    assert is_exempt(Path("addons/x/static/src/y.js"), f"{verb}Thing", verb)


@pytest.mark.parametrize("name", ["deleteProperty", "locateFile", "fillRect"])
def test_platform_contract_names_are_exempt_by_name(name):
    assert name in PLATFORM_METHODS
    verb = leading_verb(name)
    assert is_exempt(Path("addons/x/static/src/y.js"), name, verb)


def test_the_record_store_owns_delete_and_nothing_else():
    assert "mail/static/src/model/" in CONTRACT_TREES
    model = Path("addons/mail/static/src/model/record_list.js")
    assert is_exempt(model, "deleteNoinv", "delete")
    assert not is_exempt(model, "buildList", "build")
    assert not is_exempt(Path("addons/mail/static/src/core/x.js"), "deleteX", "delete")


def test_measure_reports_the_private_definition(tmp_path):
    (tmp_path / "a.js").write_text(SOURCE)
    found = {v.name for v in measure(tmp_path)}
    assert "_retrieveIdFromData" in found
    assert "_buildFormData" in found
    assert "buildOpenChatParams" in found
    assert "fetchThings" not in found
    assert "locateFile" not in found
    assert "deleteProperty" not in found
    assert "fillEmpty" not in found
