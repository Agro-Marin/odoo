import computed_default as cd
import pytest


def _tree(tmp_path, files):
    root = tmp_path / "addons"
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


def _fields(tmp_path, files):
    return [shape.field for shape in cd.measure([_tree(tmp_path, files)])]


FLEET = (
    "from odoo import fields, models\n"
    "class Vehicle(models.Model):\n"
    '    _name = "fleet.vehicle"\n'
    "    range_unit = fields.Selection(\n"
    '        [("km", "km"), ("mi", "mi")],\n'
    '        compute="_compute_range_unit",\n'
    "        store=True,\n"
    "        readonly=False,\n"
    "        {default}\n"
    "        required=True,\n"
    "    )\n"
)


def test_an_editable_stored_compute_with_a_truthy_default_is_the_shape(tmp_path):
    body = FLEET.format(default='default="km",')
    assert _fields(tmp_path, {"fleet/models/fleet_vehicle.py": body}) == [
        "fleet.vehicle.range_unit"
    ]


def test_the_same_field_declaring_precompute_instead_is_not(tmp_path):
    body = FLEET.format(default="precompute=True,")
    assert _fields(tmp_path, {"fleet/models/fleet_vehicle.py": body}) == []


@pytest.mark.parametrize("default", ["False", "None", "0", '""', "[]"])
def test_a_falsy_default_is_skipped_by_create_and_is_not_the_shape(tmp_path, default):
    body = FLEET.format(default=f"default={default},")
    assert _fields(tmp_path, {"fleet/models/fleet_vehicle.py": body}) == []


def test_a_callable_default_is_the_shape(tmp_path):
    body = FLEET.format(default="default=lambda self: self.env.company.unit,")
    assert _fields(tmp_path, {"fleet/models/fleet_vehicle.py": body}) == [
        "fleet.vehicle.range_unit"
    ]


@pytest.mark.parametrize(
    "attrs",
    [
        'compute="_c", store=True, default="x"',
        'compute="_c", readonly=False, default="x"',
        'related="a.b", store=True, readonly=False, default="x"',
        'store=True, readonly=False, default="x"',
    ],
)
def test_readonly_unstored_related_or_uncomputed_fields_are_not_the_shape(
    tmp_path, attrs
):
    body = f'class M(models.Model):\n    _name = "m"\n    f = fields.Char({attrs})\n'
    assert _fields(tmp_path, {"mod/models/m.py": body}) == []


def test_a_default_an_extension_adds_to_another_module_s_compute_is_the_shape(tmp_path):
    base = (
        "class Vehicle(models.Model):\n"
        '    _name = "fleet.vehicle"\n'
        '    fuel_type = fields.Selection(compute="_compute_fuel_type", store=True, readonly=False)\n'
    )
    extension = (
        "class Vehicle(models.Model):\n"
        '    _inherit = "fleet.vehicle"\n'
        '    fuel_type = fields.Selection(default="diesel")\n'
    )
    shapes = cd.measure(
        [
            _tree(
                tmp_path,
                {
                    "fleet/models/fleet_vehicle.py": base,
                    "l10n_be_fleet/models/fleet.py": extension,
                },
            )
        ]
    )
    assert [(s.field, s.default) for s in shapes] == [
        ("fleet.vehicle.fuel_type", "'diesel'")
    ]
    assert shapes[0].path.endswith("l10n_be_fleet/models/fleet.py")


def test_tests_and_migrations_are_out_of_scope(tmp_path):
    body = FLEET.format(default='default="km",')
    assert (
        _fields(
            tmp_path,
            {
                "fleet/tests/test_vehicle.py": body,
                "fleet/migrations/1.0/post-migrate.py": body,
                "fleet/models/__init__.py": "",
            },
        )
        == []
    )


def test_a_tree_with_no_python_source_is_refused(tmp_path):
    root = tmp_path / "addons"
    root.mkdir()
    (root / "README.md").write_text("not source\n")
    with pytest.raises(cd.NoSource):
        cd.measure([root])


def test_reviewed_and_pending_fields_pass_an_unlisted_one_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "REVIEWED", {"a.reviewed": "keeps the stored value"})
    monkeypatch.setattr(cd, "PENDING", frozenset({"a.pending"}))
    shapes = [
        cd.Shape("a.reviewed", "'x'", "p", 1),
        cd.Shape("a.pending", "'x'", "p", 2),
        cd.Shape("a.new", "'x'", "p", 3),
    ]
    unlisted, stale = cd.split(shapes)
    assert [s.field for s in unlisted] == ["a.new"]
    assert stale == []


def test_a_listed_field_that_no_longer_has_the_shape_is_stale(monkeypatch):
    monkeypatch.setattr(cd, "REVIEWED", {"a.fixed": "keeps the stored value"})
    monkeypatch.setattr(cd, "PENDING", frozenset({"a.pending"}))
    assert cd.split([cd.Shape("a.pending", "'x'", "p", 1)]) == ([], ["a.fixed"])
    assert cd.split([cd.Shape("a.pending", "'x'", "p", 1)], full_workspace=False) == (
        [],
        [],
    )


def test_no_field_is_both_reviewed_and_pending():
    assert not set(cd.REVIEWED) & cd.PENDING


def test_every_reviewed_field_carries_a_reason():
    assert all(reason.strip() for reason in cd.REVIEWED.values())


def test_the_real_tree_holds_only_listed_fields():
    unlisted, stale = cd.split(
        cd.measure(), full_workspace=cd.in_full_workspace(cd.ROOT)
    )
    assert unlisted == [], "\n".join(map(str, unlisted))
    assert stale == []
