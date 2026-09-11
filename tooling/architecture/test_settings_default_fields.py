import pytest
import settings_default_fields as sdf


def _tree(tmp_path, files):
    root = tmp_path / "addons"
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


def _targets(tmp_path, files, **kwargs):
    return [o.target for o in sdf.measure([_tree(tmp_path, files)], **kwargs)]


VERSION = (
    "class Version(models.Model):\n"
    '    _name = "hr.version"\n'
    "    mobile_subscription = fields.Float()\n"
)


def _settings(field, model="hr.version"):
    return (
        "class Settings(models.TransientModel):\n"
        '    _inherit = "res.config.settings"\n'
        f'    {field} = fields.Float(default_model="{model}")\n'
    )


def test_a_settings_default_naming_a_renamed_field_is_an_offender(tmp_path):
    files = {
        "hr/models/version.py": VERSION,
        "be/models/settings.py": _settings("default_mobile"),
    }
    assert _targets(tmp_path, files) == ["hr.version.mobile"]


def test_a_settings_default_naming_a_declared_field_is_not(tmp_path):
    files = {
        "hr/models/version.py": VERSION,
        "be/models/settings.py": _settings("default_mobile_subscription"),
    }
    assert _targets(tmp_path, files) == []


def test_fields_from_inherited_parents_and_delegations_count(tmp_path):
    files = {
        "mixin/models/mixin.py": (
            "class Mixin(models.AbstractModel):\n"
            '    _name = "mixin.cost"\n'
            "    internet = fields.Float()\n"
        ),
        "partner/models/partner.py": (
            "class Partner(models.Model):\n"
            '    _name = "res.partner"\n'
            "    lang = fields.Char()\n"
        ),
        "hr/models/version.py": (
            "class Version(models.Model):\n"
            '    _name = "hr.version"\n'
            '    _inherit = ["mixin.cost"]\n'
            '    _inherits = {"res.partner": "partner_id"}\n'
            '    partner_id = fields.Many2one("res.partner")\n'
        ),
        "be/models/settings.py": _settings("default_internet")
        + _settings("default_lang").split("\n", 2)[2]
        + _settings("default_create_date").split("\n", 2)[2],
    }
    assert _targets(tmp_path, files) == []


def test_a_default_model_added_by_an_extension_is_checked(tmp_path):
    files = {
        "hr/models/version.py": VERSION,
        "base/models/settings.py": (
            "class Settings(models.TransientModel):\n"
            '    _name = "res.config.settings"\n'
            "    default_mobile = fields.Float()\n"
        ),
        "be/models/settings.py": _settings("default_mobile"),
    }
    assert _targets(tmp_path, files) == ["hr.version.mobile"]


def test_an_undeclared_model_counts_only_in_the_full_workspace(tmp_path):
    files = {"be/models/settings.py": _settings("default_mobile", model="hr.version")}
    assert _targets(tmp_path / "partial", files) == []
    assert _targets(tmp_path / "full", files, full_workspace=True) == [
        "hr.version.mobile"
    ]


def test_tests_and_migrations_are_out_of_scope(tmp_path):
    files = {
        "hr/models/version.py": VERSION,
        "be/tests/test_settings.py": _settings("default_mobile"),
        "be/migrations/1.1/settings.py": _settings("default_mobile"),
    }
    assert _targets(tmp_path, files) == []


def test_a_tree_with_no_python_source_is_refused(tmp_path):
    root = tmp_path / "addons"
    root.mkdir()
    (root / "README.md").write_text("not source\n")
    with pytest.raises(sdf.NoSource):
        sdf.measure([root])


def test_the_real_tree_holds_no_offender():
    offenders = sdf.measure(full_workspace=sdf.in_full_workspace(sdf.ROOT))
    assert offenders == [], "\n".join(map(str, offenders))
