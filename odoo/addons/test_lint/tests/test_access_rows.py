import ast
import tempfile
from collections import defaultdict
from pathlib import Path

from odoo.fields import Domain
from odoo.orm.models.anchors import ANCHOR_KINDS

from . import _access_index as index
from . import lint_case
from odoo.addons.base.models.ir_access import (
    REACH_ANCHOR,
    REACH_KINDS,
    domain_group_tests,
    find_access_cycle,
    parse_access_domain,
)
from odoo.addons.base.models.ir_access_reach import PRINCIPAL_FIELDS

# the methods through which a model decides access in code instead of in rows
_CHECK_OVERRIDES = frozenset({"_check_access", "_has_field_access", "_access_domain"})
# what marks a _search override as one that filters for access
_SEARCH_ACCESS_NAMES = frozenset(
    {
        "bypass_access",
        "_check_access",
        "_filtered_access",
        "has_access",
        "check_access",
        "get_accessible_query",
        "get_inaccessible_owners",
    }
)


def _production(row_or_module) -> bool:
    module = getattr(row_or_module, "module", row_or_module)
    return not module.startswith("test_")


def kind_findings(rows):
    # a guard on a group binds everyone unless it says it binds the members
    return [
        f"{row.where()}: no kind"
        for row in rows
        if row.creates and row.kind not in ("permission", "guard")
    ] + [
        f"{row.where()}: a guard of {row.group} that does not say whom it binds"
        for row in rows
        if row.creates
        and row.kind == "guard"
        and not row.guard_scope
        and (row.group or "").split(".")[-1] != "group_everyone"
    ]


def operation_findings(rows):
    return [
        f"{row.where()}: no operation"
        for row in rows
        if row.creates and not row.operation and not row.verbs
    ]


def domain_findings(rows):
    return [
        f"{row.where()}: {problem}"
        for row in rows
        if row.domain and index.known_model(row.model)
        for problem in index.validate(row.model, row.domain)
    ]


def group_test_findings(rows):
    return [
        f"{row.where()}: reads {', '.join(tests)}"
        for row in rows
        if row.domain and (tests := domain_group_tests(row.domain))
    ]


def coverage_findings(rows, models):
    covered = {row.model for row in rows if row.kind == "permission"}
    return sorted(
        f"{info.defined_in}: {name}"
        for name, info in models.items()
        if info.kind == "model" and name not in covered and _production(info.module)
    )


# the groups that are never held in some companies only: a grant of a user
# type is refused a scope, and everyone is every user everywhere
_UNSCOPED_GROUPS = frozenset(
    {"base.group_user", "base.group_portal", "base.group_public", "base.group_everyone"}
)
_COMPANY_NAMES = frozenset({"company_ids", "company_id"})


def _reads_companies(node) -> bool:
    return any(
        (isinstance(child, ast.Name) and child.id in _COMPANY_NAMES)
        or (isinstance(child, ast.Attribute) and child.attr in _COMPANY_NAMES)
        for child in ast.walk(node)
    )


def _company_paths(row) -> set[str]:
    # the fields a row compares with the principal's companies: its domain's,
    # and for a company reach the anchor it reads
    paths = set()
    if row.reach == "company" and index.known_model(row.model):
        anchor = index.anchors(row.model).get(row.anchor or "company")
        if anchor:
            paths.add(anchor[0])
    if not row.domain:
        return paths
    try:
        found, _problems = index.conditions(index.parse_domain(row.domain))
    except SyntaxError:
        return paths
    return paths | {
        condition.path
        for condition in found
        if condition.operator in ("in", "=", "parent_of", "child_of")
        and _reads_companies(condition.value)
    }


def company_anchor_findings(rows):
    # a model's company guards and its company anchor name the same field, so a
    # grant limited to some companies reaches exactly what a guard would admit
    # there; a guard reading several fields needs the anchor among them
    paths_by_model: defaultdict[str, set[str]] = defaultdict(set)
    where_by_model: dict[str, str] = {}
    for row in rows:
        if (
            row.kind != "guard"
            or not index.known_model(row.model)
            or (row.group or "").split(".")[-1] != "group_everyone"
            or not (paths := _company_paths(row))
        ):
            continue
        paths_by_model[row.model] |= paths
        where_by_model.setdefault(row.model, row.where())
    findings = []
    for model, paths in sorted(paths_by_model.items()):
        anchor = index.company_anchor(model)
        if anchor not in paths:
            findings.append(
                f"{where_by_model[model]}: {model} is guarded by company on "
                f"{', '.join(sorted(paths))}, its company anchor is {anchor or 'none'}"
            )
    return findings


def anchorless_findings(rows, models):
    # the models where a group that can be held in some companies only has a
    # permission, and no company anchor: such a grant applies there to every
    # record while one of its companies is in use
    return sorted(
        {
            f"{info.defined_in}: {row.model}"
            for row in rows
            if row.kind == "permission"
            and (info := models.get(row.model)) is not None
            and info.kind == "model"
            and _production(info.module)
            and index._qualify(row.module, row.group or "") not in _UNSCOPED_GROUPS
            and index.company_anchor(row.model) is None
        }
    )


def cycle_findings(rows, models):
    edges: defaultdict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for name, info in models.items():
        if info.kind == "abstract" or not info.inherits_rules:
            continue
        for parent in info.inherits:
            for operation in index.OPERATIONS.values():
                edges[name, operation].add((parent, operation))
    for row in rows:
        targets = index.access_edges(row)
        for letter, operation in index.OPERATIONS.items():
            if letter in (row.operation or ""):
                edges[row.model, operation].update(targets)
    findings = []
    while cycle := find_access_cycle(edges):
        findings.append(" -> ".join(f"{model}.{op}" for model, op in cycle))
        model, operation = cycle[0]
        edges[model, operation].discard(cycle[1])
    return findings


def override_findings(paths):
    findings = []
    for path in paths:
        try:
            tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for method in node.body:
                if not isinstance(method, ast.FunctionDef):
                    continue
                if method.name in _CHECK_OVERRIDES or (
                    method.name == "_search"
                    and _SEARCH_ACCESS_NAMES
                    & {
                        getattr(child, "id", None) or getattr(child, "attr", None)
                        for child in ast.walk(method)
                    }
                ):
                    findings.append(f"{path}:{method.lineno} {node.name}.{method.name}")
    return findings


def old_format_findings(paths):
    findings = []
    for path in paths:
        name = Path(path).name
        if name.startswith("ir.model.access") and name.endswith(".csv"):
            findings.append(f"{path}: an ir.model.access CSV")
        elif name.endswith(".xml"):
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            findings.extend(
                f"{path}: a {model} record"
                for model in ("ir.rule", "ir.model.access")
                if f'model="{model}"' in text or f"model='{model}'" in text
            )
    return findings


def override_paths():
    return [
        path
        for path in lint_case.module_file_paths()
        if path.endswith(".py")
        and lint_case.is_core_path(path)
        and "/odoo/addons/base/" not in path
        and not any(
            part == "tests" or part.startswith("test_") for part in path.split("/")
        )
        and "/migrations/" not in path
    ]


def _reads_principal(domain: str | None) -> bool:
    # a domain that reads the user: through its names, or through a field
    # whose search reads it (a named predicate says that one)
    if not domain:
        return False
    if not isinstance(parse_access_domain(domain), Domain):
        return True
    try:
        leaves = ast.literal_eval(domain)
    except ValueError, SyntaxError:
        return False
    return any(
        isinstance(leaf, (list, tuple))
        and len(leaf) == 3
        and str(leaf[0]).rsplit(".", 1)[-1] in PRINCIPAL_FIELDS
        for leaf in leaves
    )


def reach_findings(rows):
    # a row that reaches through an anchor its model declares, of a kind its
    # rung can read, with nothing but a fixed filter beside it
    findings = []
    for row in rows:
        if not row.reach:
            continue
        if _reads_principal(row.domain):
            findings.append(
                f"{row.where()}: a reach beside a domain that reads the user"
            )
        if row.reach not in REACH_ANCHOR or not index.known_model(row.model):
            continue
        key = row.anchor or REACH_ANCHOR[row.reach]
        declared = index.anchors(row.model)
        if key not in declared:
            findings.append(f"{row.where()}: {row.model} declares no anchor {key}")
        elif declared[key][1] not in REACH_KINDS[row.reach]:
            findings.append(
                f"{row.where()}: the reach {row.reach} cannot read {key}, a "
                f"{declared[key][1]}"
            )
    return findings


def anchor_findings(models):
    # every declared anchor follows fields the models have, to the model its
    # kind names
    findings = []
    for name, info in sorted(models.items()):
        if info.kind == "abstract" or not _production(info.module):
            continue
        for key, path in info.anchors.items():
            kind = info.anchor_kinds.get(key, key)
            if kind not in ANCHOR_KINDS:
                findings.append(f"{info.defined_in}: {name} anchor {key} has no kind")
                continue
            if not path or path == "id":
                continue
            owner = name
            for part in path.split("."):
                field_info = index.fields_of(owner).get(part)
                if field_info is None:
                    findings.append(
                        f"{info.defined_in}: {name} anchor {key}: {owner}.{part} "
                        f"does not exist"
                    )
                    break
                owner = index.comodel_of(owner, field_info)
                if owner is None:
                    findings.append(
                        f"{info.defined_in}: {name} anchor {key}: {part} is not "
                        f"relational"
                    )
                    break
            else:
                if owner != ANCHOR_KINDS[kind]:
                    findings.append(
                        f"{info.defined_in}: {name} anchor {key} leads to {owner}, "
                        f"not to {ANCHOR_KINDS[kind]}"
                    )
    return findings


def free_domain_findings(rows):
    # a row that still spells its reach out as a domain the principal is read
    # into, where a rung or a named predicate could say it
    return sorted(
        f"{row.where()}: {row.model}"
        for row in rows
        if row.creates and not row.reach and _reads_principal(row.domain)
    )


class TestAccessRows(lint_case.LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = index.rows()
        cls.production_rows = [row for row in cls.rows if _production(row)]

    def test_the_scan_reaches_the_rows_and_the_models(self):
        self.assertGreater(len(self.rows), 3000, "the scan reached almost no row")
        self.assertGreater(len(index.models()), 1000)
        self.assertTrue(
            any(row.path.endswith(".xml") for row in self.rows),
            "the scan reached no ir_access.xml",
        )

    def test_a_reach_reads_an_anchor_its_model_declares(self):
        self.assert_ratchet(
            reach_findings(self.rows),
            "access_reach_anchor",
            "ir.access row(s) whose reach its model cannot read",
            "A row with a reach reads the model's anchor: declare it in "
            "`_access_anchors`, name the anchor the row means, and keep only a fixed "
            "filter in the domain.",
        )

    def test_every_anchor_leads_where_its_kind_says(self):
        self.assert_ratchet(
            anchor_findings(index.models()),
            "access_anchor_valid",
            "declared anchor(s) whose path the models do not follow",
            "An anchor's path follows relational fields to the model its kind "
            "names (owner: res.users, company: res.company...).",
        )

    def test_the_domains_left_over_only_go_down(self):
        self.assert_ratchet(
            free_domain_findings(self.production_rows),
            "access_domain_free",
            "ir.access row(s) spelling their reach out as a domain",
            "Say it as a reach through the model's anchor (reach/anchor), or a "
            "named predicate; a domain that reads the user is what is left when "
            "neither can. The floor only goes down.",
        )

    def test_every_row_declares_its_kind(self):
        self.assert_ratchet(
            kind_findings(self.rows),
            "access_kind_explicit",
            "ir.access row(s) created without a kind",
            "A row is a permission (adds records, OR-ed) or a guard (AND-ed, cannot "
            "be widened): say which in the `kind` column or field.",
        )

    def test_every_row_writes_its_operation(self):
        self.assert_ratchet(
            operation_findings(self.rows),
            "access_rule_mode",
            "ir.access row(s) created without an operation",
            "A row that names no operation would apply to all four: write the "
            "`operation` (a subset of crud) or the `verbs` it is meant for.",
        )

    def test_every_shipped_domain_validates(self):
        self.assert_ratchet(
            domain_findings(self.rows),
            "access_domain_validated",
            "ir.access domain(s) naming what the models do not have",
            "A path, an operator or an 'access' condition the registry cannot "
            "answer fails at load or, worse, decides nothing: fix the domain.",
        )

    def test_no_domain_tests_the_user_s_groups(self):
        self.assert_ratchet(
            group_test_findings(self.rows),
            "access_domain_no_group_test",
            "ir.access domain(s) reading the user's groups in a narrowing way",
            "Membership is the row's group: a domain that reads the user's groups "
            "(other than `in group_ids` or `[] if has_group else D`) "
            "lets a group take records away. Put the rows on the groups.",
        )

    def test_every_model_holds_a_permission(self):
        self.assert_ratchet(
            coverage_findings(self.production_rows, index.models()),
            "access_model_covered",
            "model(s) no permission row names",
            "A model without a permission is readable by the superuser only: ship "
            "the permission rows in the module's security/ir.access.csv.",
        )

    def test_the_access_graph_has_no_cycle(self):
        self.assert_ratchet(
            cycle_findings(self.rows, index.models()),
            "access_delegation_acyclic",
            "cycle(s) through 'access' conditions and delegation",
            "A record's access cannot depend on itself: break the cycle with a "
            "domain that does not go through the 'access' operator.",
        )

    def test_a_company_guard_reads_the_company_anchor(self):
        self.assert_ratchet(
            company_anchor_findings(self.production_rows),
            "access_company_anchor",
            "company guard(s) on a field other than the model's company anchor",
            "Declare `_access_anchors = frozendict({'company': '<path>'})` on the "
            "model, so a grant limited to some companies compiles against the "
            "field its company guard reads.",
        )

    def test_scoped_grants_on_models_without_a_company(self):
        self.assert_ratchet(
            anchorless_findings(self.production_rows, index.models()),
            "access_scope_anchorless",
            "model(s) a scoped grant reaches whole, having no company anchor",
            "A group held in some companies only reaches every record of such a "
            "model while one of them is in use: give the model a company anchor "
            "(a company field, or `_access_anchors`) where its records belong to "
            "a company. The floor only goes down.",
        )

    def test_access_is_decided_in_rows_not_in_code(self):
        self.assert_ratchet(
            override_findings(override_paths()),
            "access_check_override",
            "override(s) deciding access in code outside base",
            "State what a model requires in ir.access rows or in `_access_guard` "
            "(an 'access' condition on the record it belongs to); a scan in code "
            "is what P4 retires.",
        )

    def test_no_module_ships_the_retired_access_format(self):
        self.assert_ratchet(
            old_format_findings(
                path
                for path in lint_case.module_file_paths()
                if lint_case.is_core_path(path)
                and "/migrations/" not in path
                and "/upgrades/" not in path
                and "/static/" not in path
            ),
            "access_retired_format",
            "file(s) shipping ir.model.access lines or ir.rule records",
            "Those models are gone and the loader refuses their data: ship "
            "security/ir.access.csv (id,name,model_id/id,group_id/id,kind,"
            "operation,domain); base's ir_access_convert converts the old rows.",
        )


class TestAccessRowGatesSeeTheirFaults(lint_case.LintCase):
    # each gate reads a planted fault, so a gate that goes blind reads red here

    def _row(self, **values):
        defaults = {
            "module": "planted",
            "xmlid": "planted.row",
            "path": "planted.csv",
            "line": 2,
            "model": "res.partner",
            "group": "base.group_user",
            "kind": "permission",
            "operation": "r",
            "domain": None,
            "creates": True,
        }
        return index.Row(**(defaults | values))

    def test_a_row_without_kind_or_operation(self):
        self.assertEqual(len(kind_findings([self._row(kind=None)])), 1)
        self.assertEqual(len(operation_findings([self._row(operation=None)])), 1)
        self.assertFalse(operation_findings([self._row(operation=None, verbs="post")]))
        self.assertFalse(kind_findings([self._row(kind=None, creates=False)]))
        member_guard = self._row(kind="guard", group="x.group_restricted")
        self.assertEqual(len(kind_findings([member_guard])), 1)
        member_guard.guard_scope = "members"
        self.assertFalse(kind_findings([member_guard]))
        self.assertFalse(
            kind_findings([self._row(kind="guard", group="base.group_everyone")])
        )

    def test_a_domain_the_registry_cannot_answer(self):
        for domain in (
            "[('no_such_field', '=', 1)]",
            "[('company_id.no_such_field', '=', 1)]",
            "[('name', 'no such operator', 1)]",
            "[('name', 'access', 'read')]",
            "[('parent_id', 'any', [('no_such_field', '=', 1)])]",
            "[('parent_id'",
        ):
            with self.subTest(domain=domain):
                self.assertTrue(domain_findings([self._row(domain=domain)]))
        self.assertFalse(
            domain_findings(
                [
                    self._row(
                        domain="[('parent_id', 'access', 'read'), ('name', '!=', 1)]"
                    )
                ]
            )
        )

    def test_a_domain_testing_the_user_s_groups(self):
        self.assertTrue(
            group_test_findings(
                [self._row(domain="[('id', '=', 1)] if user.has_group('x.y') else []")]
            )
        )
        self.assertFalse(
            group_test_findings(
                [self._row(domain="[] if user.has_group('x.y') else [('id', '=', 1)]")]
            )
        )
        self.assertFalse(
            group_test_findings([self._row(domain="[('group_ids', 'in', group_ids)]")])
        )
        self.assertTrue(
            group_test_findings(
                [self._row(domain="['!', ('group_ids', 'in', group_ids)]")]
            )
        )

    def test_a_reach_its_model_cannot_read(self):
        self.assertTrue(reach_findings([self._row(reach="team")]))
        self.assertTrue(reach_findings([self._row(reach="partner", anchor="creator")]))
        self.assertTrue(
            reach_findings(
                [self._row(reach="own", domain="[('user_id', '=', user.id)]")]
            )
        )
        self.assertFalse(reach_findings([self._row(reach="own", anchor="creator")]))
        self.assertFalse(
            reach_findings(
                [self._row(reach="company", domain="[('is_company', '=', True)]")]
            )
        )

    def test_an_anchor_its_path_does_not_follow(self):
        def planted(path, kind):
            # planted on a real model, so its fields are the index's
            return {
                "res.partner": index.ModelInfo(
                    "res.partner",
                    module="planted",
                    anchors={"owner": path},
                    anchor_kinds={"owner": kind},
                )
            }

        self.assertTrue(anchor_findings(planted("no_such_field", "owner")))
        self.assertTrue(anchor_findings(planted("create_uid.partner_id", "owner")))
        self.assertTrue(anchor_findings(planted("create_uid", "no_such_kind")))
        self.assertFalse(anchor_findings(planted("create_uid", "owner")))

    def test_a_domain_left_over(self):
        self.assertTrue(
            free_domain_findings([self._row(domain="[('user_id', '=', user.id)]")])
        )
        self.assertFalse(
            free_domain_findings([self._row(domain="[('active', '=', True)]")])
        )
        self.assertFalse(
            free_domain_findings(
                [self._row(reach="own", domain="[('active', '=', True)]")]
            )
        )

    def test_a_company_guard_on_another_field(self):
        guard = self._row(
            kind="guard",
            group="base.group_everyone",
            model="res.partner",
            domain="[('commercial_partner_id.company_id', 'in', company_ids)]",
        )
        self.assertTrue(company_anchor_findings([guard]))
        guard.domain = "[('company_id', 'in', company_ids)]"
        self.assertFalse(company_anchor_findings([guard]))

    def test_a_scoped_permission_on_a_model_without_a_company(self):
        models = {
            "planted.model": index.ModelInfo("planted.model", module="planted"),
        }
        row = self._row(model="planted.model", group="base.group_partner_manager")
        self.assertTrue(anchorless_findings([row], models))
        self.assertFalse(
            anchorless_findings([self._row(model="planted.model")], models),
            "a user type is never held in some companies only",
        )

    def test_a_model_without_a_permission(self):
        models = {"planted.model": index.ModelInfo("planted.model", module="planted")}
        self.assertTrue(coverage_findings([], models))
        self.assertFalse(coverage_findings([self._row(model="planted.model")], models))

    def test_a_cycle_through_the_operator(self):
        models = {
            "res.partner": index.ModelInfo("res.partner"),
            "res.users": index.ModelInfo("res.users"),
        }
        forth = self._row(
            model="res.users", domain="[('partner_id', 'access', 'read')]"
        )
        back = self._row(model="res.partner", domain="[('user_id', 'access', 'read')]")
        self.assertTrue(cycle_findings([forth, back], models))
        self.assertFalse(cycle_findings([forth], models))

    def test_a_module_shipping_the_retired_format(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "ir.model.access.csv").write_text("id,name\n")
        (root / "rules.xml").write_text('<odoo><record model="ir.rule"/></odoo>')
        (root / "views.xml").write_text('<odoo><record model="ir.ui.view"/></odoo>')
        self.assertEqual(
            len(old_format_findings(str(path) for path in root.iterdir())), 2
        )

    def test_an_override_deciding_access_in_code(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "m.py"
        path.write_text(
            "class M(models.Model):\n"
            "    def _check_access(self, operation):\n"
            "        return None\n"
            "    def _search(self, domain, *, bypass_access=False, **kw):\n"
            "        return super()._search(domain, bypass_access=bypass_access)\n"
            "    def _read(self):\n"
            "        return None\n"
        )
        self.assertEqual(len(override_findings([str(path)])), 2)
