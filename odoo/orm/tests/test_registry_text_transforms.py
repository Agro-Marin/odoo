from unittest.mock import Mock

import pytest

from odoo.orm.runtime import _registry_capabilities as capabilities
from odoo.orm.runtime.environment import Environment

DB = "test_registry_text_transforms"


class Capabilities(capabilities._RegistryCapabilitiesMixin):
    pass


@pytest.fixture(autouse=True)
def clear_tables():
    capabilities.clear_text_transforms(DB)
    yield
    capabilities.clear_text_transforms(DB)


def test_cached_tables_are_rebuilt_when_unaccent_availability_changes():
    cursor = Mock(spec=["execute", "fetchone", "dictfetchall"])
    cursor.fetchone.return_value = ("c",)
    cursor.dictfetchall.return_value = [
        {"source": "Æ", "unaccented": "AE", "folded": "ae"},
        {"source": "\ua7ce", "unaccented": "\ua7ce", "folded": "\ua7cf"},
    ]
    first = capabilities._get_text_transforms(cursor, DB, True)
    calls = cursor.execute.call_count
    assert capabilities._get_text_transforms(cursor, DB, True) is first
    assert cursor.execute.call_count == calls
    assert first.unaccent[ord("Æ")] == "AE"
    assert first.ilike is not None
    assert first.ilike[0xA7CE] == "\ua7cf"

    cursor.dictfetchall.return_value = [
        {"source": "Æ", "unaccented": "Æ", "folded": "æ"},
    ]
    second = capabilities._get_text_transforms(cursor, DB, False)
    assert second is not first
    assert second.unaccent == {}
    assert second.ilike is not None
    assert second.ilike[ord("Æ")] == "æ"


def test_libc_normalization_uses_the_database_mapping_without_queries():
    instance = Capabilities()
    instance._ilike_table = {0xA7CE: "\ua7cf", ord("Æ"): "ae"}
    env = Mock(spec=Environment)
    normalize = instance.get_ilike_normalizer(env)
    assert normalize("\ua7ceÆ") == "\ua7cfae"
    env.execute_query.assert_not_called()


def test_contextual_normalization_caches_whole_strings_per_environment():
    instance = Capabilities()
    instance._ilike_table = None
    instance.unaccent = capabilities._identity
    first_env = Mock(spec=Environment)
    first_env.execute_query.return_value = [("ος",)]
    normalize = instance.get_ilike_normalizer(first_env)
    assert normalize("ΟΣ") == "ος"
    assert normalize("ΟΣ") == "ος"
    first_env.execute_query.assert_called_once()

    second_env = Mock(spec=Environment)
    second_env.execute_query.return_value = [("other",)]
    assert instance.get_ilike_normalizer(second_env)("ΟΣ") == "other"
    second_env.execute_query.assert_called_once()


def test_contextual_providers_do_not_expose_a_character_case_table():
    cursor = Mock(spec=["execute", "fetchone", "dictfetchall"])
    cursor.fetchone.return_value = ("i",)
    cursor.dictfetchall.return_value = []
    assert capabilities._get_text_transforms(cursor, DB, False).ilike is None


def test_failed_probes_do_not_publish_partial_tables():
    cursor = Mock(spec=["execute", "fetchone", "dictfetchall"])
    cursor.fetchone.return_value = ("c",)
    cursor.dictfetchall.side_effect = RuntimeError("probe failed")
    with pytest.raises(RuntimeError, match="probe failed"):
        capabilities._get_text_transforms(cursor, DB, True)
    assert DB not in capabilities._TextTables.by_db
