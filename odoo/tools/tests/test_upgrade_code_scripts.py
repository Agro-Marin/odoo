"""Properties every ``odoo/upgrade_code`` script must have, whatever it rewrites.

These scripts rewrite source **in place** in whatever checkout ``--addons-path``
points at, and two of the three audited in 2026-08 were found to corrupt the
tree they ran on (see ``odoo/cli/upgrade_code.py``'s module docstring). The
per-script suites pin what each one *means*; this one pins what none of them may
do, so a new script inherits the floor without anyone remembering to ask:

* it must be discoverable — the CLI selects by ``{version}-{nn}-{name}.py`` and
  a name it cannot parse is skipped in silence;
* it must expose ``upgrade(file_manager)``;
* it must leave Python that still parses and XML that still parses, which is the
  exact class of defect the bare-regex rewrites produced;
* it must be idempotent, because a script that is not can be run twice by
  accident and compound its own damage.
"""

import ast
import importlib.util
import pathlib
import re
from itertools import starmap

import pytest
from lxml import etree

UPGRADE_DIR = pathlib.Path(__file__).resolve().parents[2] / "upgrade_code"
SCRIPTS = sorted(UPGRADE_DIR.glob("*.py"))
SCRIPT_IDS = [p.name for p in SCRIPTS]

# `17.5-00-example.py` computes a rewrite and deliberately never assigns it
# back: it is the fixture `base/tests/test_cli.py` runs `--dry-run` against, and
# two tests there fail the moment it dirties a file. Its substitutions are an
# API demonstration, so a version range that swept it up would mangle every
# `models/*.py` for nothing. Named here rather than left to pass silently.
INERT_BY_DESIGN = {"17.5-00-example.py"}

# `{version}-{nn}-{name}.py`. `get_upgrade_code_scripts` partitions on the first
# `-` and feeds the head to `parse_version`, so a name shaped otherwise is not
# rejected — it is silently never selected.
SCRIPT_NAME_RE = re.compile(r"^\d+\.\d+-\d\d-[a-z0-9-]+\.py$")

PY_SOURCE = """\
from odoo import api, fields, models
from odoo.http import request, route


class AccountMove(models.Model):
    _name = "account.move"
    _description = "Entry"

    name = fields.Char(string="Tree view label")
    line_ids = fields.One2many("account.move.line", "move_id")

    @api.depends("line_ids")
    def _compute_total(self):
        for move in self:
            move.total = sum(move.line_ids.mapped("amount"))

    def action_open(self):
        return {
            "type": "ir.actions.act_window",
            "view_mode": "tree,form",
            "context": {"tree_view_ref": "account.view_move_tree"},
            "domain": [("date", ">", "2024-01-01")],
        }
"""

CONTROLLER_SOURCE = """\
from odoo.http import Controller, request, route


class Portal(Controller):
    @route("/my/orders", type="json", auth="user")
    def orders(self, **kw):
        return request.env["sale.order"].search_read([])

    @route("/my/quotes", type="json", auth="user", website=True)
    def quotes(self, **kw):
        return {"cr": request.env.cr.dbname}
"""

VIEW_XML = """\
<odoo>
    <record id="view_move_tree" model="ir.ui.view">
        <field name="name">account.move.tree</field>
        <field name="arch" type="xml">
            <tree string="Entries">
                <field name="name"/>
            </tree>
        </field>
    </record>
    <record id="action_move" model="ir.actions.act_window">
        <field name="view_mode">tree,form</field>
        <field name="domain">[('date', '&gt;', '2024-01-01')]</field>
    </record>
</odoo>
"""

DATA_XML = """\
<odoo>
    <record id="rule_move" model="ir.rule">
        <field name="name">move rule</field>
        <field name="domain_force">[('date', '&gt;', context_today())]</field>
    </record>
    <record id="filter_recent" model="ir.filters">
        <field name="domain">[('create_date', '&gt;', context_today() - relativedelta(days=3))]</field>
    </record>
</odoo>
"""

PO_SOURCE = """\
msgid ""
msgstr ""
"Project-Id-Version: Odoo Server 18.0\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"

#. module: account
#: model:ir.model.fields,field_description:account.field_account_move__name
msgid "Number"
msgstr "Numero"
"""


SQL_CONSTRAINT_SOURCE = """\
from odoo import fields, models


class Team(models.Model):
    _name = "crm.team"
    _sql_constraints = [
        ("code_uniq", "unique(code)", "The code must be unique"),
    ]

    code = fields.Char()
"""

DEPRECATED_PROPERTIES_SOURCE = """\
from odoo import models


class Lead(models.Model):
    _name = "crm.lead"

    def read_them(self):
        # a comment mentioning self._cr must not be rewritten
        note = "the literal ._context must not be rewritten either"
        self._cr.execute("SELECT 1")
        return self._uid, self._context, note
"""

L10N_PO_SOURCE = """\
msgid ""
msgstr ""
"Project-Id-Version: Odoo Server 18.0\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"

#. module: l10n_mx
#: model:account.tax.group,name:l10n_mx.tax_group_iva_16
msgid "IVA 16%"
msgstr "IVA 16%"
"""

L10N_DATA_XML = """\
<odoo>
    <record id="tax_group_iva_16" model="account.tax.group">
        <field name="name">IVA 16%</field>
    </record>
</odoo>
"""

TAX_TEMPLATE_CSV = """\
id,name,amount,type_tax_use,amount_type,children_tax_ids,repartition_line_ids/document_type,repartition_line_ids/repartition_type,repartition_line_ids/factor_percent,repartition_line_ids/tag_ids
tax_iva_16,IVA 16%,16.0,sale,percent,,invoice,tax,100,+IVA
,,,,,,refund,tax,100,-IVA
"""

TAX_REPORT_XML = """\
<odoo>
    <record id="tax_report" model="account.report">
        <field name="name">Tax report</field>
        <field name="country_id" ref="base.mx"/>
        <record id="tax_report_line" model="account.report.expression">
            <field name="engine">tax_tags</field>
            <field name="formula">IVA</field>
        </record>
    </record>
</odoo>
"""

FISCAL_POSITION_CSV = """\
id,name,country_id/id,auto_apply,tax_ids/tax_src_id,tax_ids/tax_dest_id
fiscal_position_mx,Domestic,base.mx,1,tax_iva_16,tax_iva_0
"""

FP_TAX_CSV = """\
id,name,amount,type_tax_use
tax_iva_16,IVA 16%,16.0,sale
"""


# Every script filters by path, so the corpus has to carry a file each one will
# actually pick up. `test_every_script_bites_the_corpus` pins that: a fixture
# that stopped reaching a script would leave its parseability and idempotence
# checks passing while comparing nothing.
CORPUS = {
    "addons/account/models/account_move.py": PY_SOURCE,
    "addons/account/models/crm_team.py": SQL_CONSTRAINT_SOURCE,
    "addons/crm/models/crm_lead.py": DEPRECATED_PROPERTIES_SOURCE,
    "addons/account/controllers/portal.py": CONTROLLER_SOURCE,
    "addons/account/views/account_move_views.xml": VIEW_XML,
    "addons/account/data/account_data.xml": DATA_XML,
    "addons/account/i18n/es.po": PO_SOURCE,
    "addons/l10n_mx/i18n/es_MX.po": L10N_PO_SOURCE,
    "addons/l10n_mx/data/account_data.xml": L10N_DATA_XML,
    "addons/l10n_mx/data/tax_report.xml": TAX_REPORT_XML,
    "addons/l10n_mx/data/template/account.tax-mx.csv": TAX_TEMPLATE_CSV,
    "addons/l10n_mx/data/template/account.fiscal.position-mx.csv": FISCAL_POSITION_CSV,
    "addons/l10n_mx/data/template/account.tax-generic.csv": FP_TAX_CSV,
}


class FakeFile:
    """Stands in for ``cli.upgrade_code.FileAccessor``, dirty tracking included."""

    def __init__(self, path: str, content: str) -> None:
        self.path = pathlib.Path(path)
        self.addon = pathlib.Path(path).parents[-2]
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


class FakeFileManager:
    """Stands in for ``cli.upgrade_code.FileManager``."""

    def __init__(self, corpus: dict[str, str] | None = None) -> None:
        source = CORPUS if corpus is None else corpus
        self._files = list(starmap(FakeFile, source.items()))

    def __iter__(self):
        return iter(self._files)

    def __len__(self) -> int:
        return len(self._files)

    def get_file(self, path):
        return next((f for f in self._files if str(f.path) == str(path)), None)

    def print_progress(self, current, total=None, file_name="") -> None:
        pass

    def snapshot(self) -> dict[str, str]:
        return {str(f.path): f.content for f in self._files}


def load_script(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(f"upgrade_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_directory_is_not_empty():
    """A gate that silently measures nothing passes forever."""
    assert SCRIPTS, f"no upgrade_code scripts found under {UPGRADE_DIR}"


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_the_name_is_one_the_cli_can_select(script):
    assert SCRIPT_NAME_RE.match(script.name), (
        f"{script.name} does not match {SCRIPT_NAME_RE.pattern}; "
        "get_upgrade_code_scripts would never select it and would not say so"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_the_script_exposes_upgrade(script):
    module = load_script(script)
    assert callable(getattr(module, "upgrade", None)), (
        f"{script.name} has no upgrade(); migrate() would raise AttributeError "
        "halfway through a run"
    )
    # Read the code object, not `inspect.signature`: these scripts annotate the
    # parameter with a name imported under `if TYPE_CHECKING`, so resolving the
    # annotation raises NameError under PEP 649's lazy evaluation.
    code = module.upgrade.__code__
    params = list(code.co_varnames[: code.co_argcount])
    assert params == ["file_manager"], (
        f"{script.name}.upgrade takes {params}, not (file_manager)"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_the_rewrite_leaves_parseable_python_and_xml(script):
    manager = FakeFileManager()
    load_script(script).upgrade(manager)
    for name, content in manager.snapshot().items():
        if name.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as exc:
                pytest.fail(
                    f"{script.name} produced unparseable Python in {name}: {exc}"
                )
        elif name.endswith(".xml"):
            try:
                etree.fromstring(content.encode())
            except etree.XMLSyntaxError as exc:
                pytest.fail(f"{script.name} produced unparseable XML in {name}: {exc}")


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_the_rewrite_is_idempotent(script):
    """Running a script twice must equal running it once.

    Nothing stops a second run — the CLI has no record of what it applied — and
    a rewrite that keeps biting compounds its own damage. Everything here is
    substitution, so the fixed point should be reached on the first pass.
    """
    module = load_script(script)
    first = FakeFileManager()
    module.upgrade(first)
    once = first.snapshot()

    second = FakeFileManager(once)
    module.upgrade(second)
    assert second.snapshot() == once, f"{script.name} keeps rewriting its own output"


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_every_script_bites_the_corpus(script):
    """Each script must actually rewrite something here.

    Without this the suite above is vacuous for any script the fixtures stop
    reaching: "the output still parses" and "a second run changes nothing" are
    both trivially true of a script that did nothing. Measured while building
    this file — the first corpus reached three of the nine, and the other six
    were passing on air.
    """
    manager = FakeFileManager()
    load_script(script).upgrade(manager)
    dirty = [f for f in manager if f.dirty]
    if script.name in INERT_BY_DESIGN:
        assert not dirty, (
            f"{script.name} is pinned inert by base/tests/test_cli.py; it must "
            "not start rewriting files"
        )
        return
    assert dirty, (
        f"{script.name} changed nothing in the corpus, so every other property "
        "asserted about it here is vacuous; add a fixture it selects"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPT_IDS)
def test_an_empty_file_manager_is_survivable(script):
    """`--glob` routinely selects nothing; that is not an error."""
    load_script(script).upgrade(FakeFileManager({}))
