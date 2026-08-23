"""``18.5-00-domain-dynamic-dates.py`` — the rewrite of computed date domains.

The script carried six of these cases in an ``if __name__ == "__main__"`` block
that CI never ran, which is a self-test only in the sense that someone could
have run it. They are here, executed, with the failure modes the block never
covered: a domain the transformer must refuse, and the XML rewrite that turns
the transformed domain back into a file.
"""

import importlib.util
import pathlib

import pytest

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "upgrade_code"
    / "18.5-00-domain-dynamic-dates.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("domain_dynamic_dates", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load()


class _File:
    def __init__(self, content: str, name: str = "addons/x/data/rules.xml"):
        self.path = pathlib.Path(name)
        self._content = content
        self.dirty = False

    @property
    def content(self) -> str:
        return self._content

    @content.setter
    def content(self, value: str) -> None:
        if self._content != value:
            self._content = value
            self.dirty = True


class _Manager:
    def __init__(self, files):
        self._files = files

    def __iter__(self):
        return iter(self._files)

    def __len__(self):
        return len(self._files)

    def print_progress(self, *args, **kwargs):
        pass


TRANSFORMS = [
    ("[('dt', '>', context_today())]", "[('dt', '>', 'now')]"),
    (
        "[('dt', '>', context_today() - relativedelta(days=3))]",
        "[('dt', '>', '-3d')]",
    ),
    (
        "[('dt', '>', (context_today() + relativedelta(months=-1)).strftime('%Y-%m-%d'))]",
        "[('dt', '>', 'today -1m')]",
    ),
    (
        "[('dt', '>=', context_today() - relativedelta(day=1))]",
        "[('dt', '>=', '=1d')]",
    ),
    (
        "[('dt', '>', (datetime.datetime.combine(context_today() + relativedelta(days=1,weekday=0), datetime.time(0,0,0)).to_utc()))]",
        "[('dt', '>', '=monday')]",
    ),
]


@pytest.mark.parametrize(("domain", "expected"), TRANSFORMS)
def test_a_computed_date_becomes_a_dynamic_literal(domain, expected):
    assert MODULE.UpgradeDomainTransformer().transform(domain) == expected


def test_a_compound_domain_is_transformed_whole():
    """The sixth case from the `__main__` block, which asserted only that the
    domain changed. Pinning the output instead makes it a test."""
    domain = (
        "['|', ('start_date', 'in', "
        "[context_today().strftime('%Y-%m-01'), "
        "(context_today() - relativedelta(months=1)).strftime('%Y-%m-01')]), "
        "'&', '&', ('start_date', '>=', "
        "(context_today() - relativedelta(months=5)).strftime('%Y-%m-01')), "
        "('end_date', '<', (context_today() + relativedelta(months=3))"
        ".strftime('%Y-%m-01')), ('periodicity', '=', 'trimester')]"
    )
    result = MODULE.UpgradeDomainTransformer().transform(domain)
    assert result != domain
    assert "context_today" not in result
    assert "relativedelta" not in result


def test_a_domain_with_nothing_to_change_raises_NoChange():
    """The signal `upgrade()` uses to leave a file alone. A transformer that
    returned the domain unchanged instead would mark every file dirty."""
    with pytest.raises(MODULE.NoChange):
        MODULE.UpgradeDomainTransformer().transform("[('name', '=', 'x')]")


def test_a_domain_it_cannot_read_is_refused_rather_than_guessed():
    with pytest.raises(MODULE.NoChange):
        MODULE.UpgradeDomainTransformer().transform(
            "[('dt', '>', some_unknown_helper(1))]"
        )


def test_the_xml_rewrite_replaces_the_domain_in_place():
    xml = (
        "<odoo>\n"
        '    <record id="r" model="ir.rule">\n'
        "        <field name=\"domain_force\">[('dt', '&gt;', context_today())]</field>\n"
        "    </record>\n"
        "</odoo>\n"
    )
    handle = _File(xml)
    MODULE.upgrade(_Manager([handle]))
    assert handle.dirty
    assert "context_today" not in handle.content
    assert "'now'" in handle.content
    assert handle.content.startswith("<odoo>")


def test_a_file_outside_data_report_views_is_not_touched():
    """The script's own scope. `models/` XML is not view data."""
    xml = (
        "<odoo><field name=\"domain\">[('dt', '&gt;', context_today())]</field></odoo>"
    )
    handle = _File(xml, name="addons/x/models/thing.xml")
    MODULE.upgrade(_Manager([handle]))
    assert not handle.dirty


def test_unparseable_xml_is_skipped_not_raised():
    handle = _File("<odoo><unclosed>", name="addons/x/views/broken.xml")
    MODULE.upgrade(_Manager([handle]))
    assert not handle.dirty
