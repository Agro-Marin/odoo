from . import migration_version_guard as guard


def test_a_script_above_the_released_version_runs():
    assert guard.verdict("1.0.4", "1.0.5", "1.0.5") is None


def test_a_script_at_the_released_version_is_unreachable():
    why = guard.verdict("1.0.4", "1.0.4", "1.0.4")
    assert why and "already released at 1.0.4" in why


def test_a_script_below_the_released_version_is_unreachable():
    why = guard.verdict("1.0.4", "1.0.3", "1.0.5")
    assert why and "already released at 1.0.4" in why


def test_a_script_above_the_new_manifest_version_is_unreachable():
    why = guard.verdict("1.0.4", "1.0.6", "1.0.5")
    assert why and "above the module's own manifest version 1.0.5" in why


def test_a_brand_new_module_never_migrates():
    assert guard.verdict(None, "1.0.1", "1.0.1") is None


def test_the_odoo_series_prefix_is_equivalent_to_the_bare_version():
    # _convert_version prefixes the running series, so both spellings compare.
    assert guard.verdict("19.0.1.0.4", "1.0.5", "1.0.5") is None
    assert guard.verdict("1.0.4", "19.0.1.0.5", "19.0.1.0.5") is None


def test_an_intermediate_directory_still_runs():
    # released 1.0.2, shipping 1.0.5, a 1.0.3 script in between must still run
    assert guard.verdict("1.0.2", "1.0.3", "1.0.5") is None
