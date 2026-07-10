"""Tier-1 (database-free) unit tests for ``NameManager.get_missing_fields``.

The missing-fields set algebra runs against the real
:class:`odoo.libs.set_expression.SetDefinitions` with stub model/env objects:
no registry, no database (see ``conftest.py``). Group universe: ``user`` (plain
internal), ``system`` (⊆ ``manager``), ``manager``, ``portal`` (disjoint from
internal groups).
"""

from lxml import etree

from odoo.libs.set_expression import SetDefinitions

from odoo.addons.base.models.ir_ui_view_name_manager import NameManager

DEFS = SetDefinitions(
    {
        1: {"ref": "base.group_user"},
        2: {"ref": "base.group_system", "supersets": [3]},
        3: {"ref": "base.group_erp_manager"},
        4: {"ref": "base.group_portal", "disjoints": [1, 2, 3]},
    }
)

USER = DEFS.parse("base.group_user")
SYSTEM = DEFS.parse("base.group_system")
MANAGER = DEFS.parse("base.group_erp_manager")
PORTAL = DEFS.parse("base.group_portal")


class StubField:
    """Field stand-in: only ``groups`` is read by the set algebra."""

    def __init__(self, groups: str | None = None) -> None:
        self.groups = groups


class StubEnv(dict):
    """Environment stand-in; NameManager only stores it, so empty is enough."""


class StubModel:
    """Model stand-in: only ``_fields``, ``fields_get`` and ``has_access`` are
    touched by the missing-fields logic."""

    _name = "stub.model"

    def __init__(self, fields: dict[str, StubField] | None = None) -> None:
        self._fields = fields or {}
        self.env = StubEnv()

    def fields_get(self, attributes=None):
        return {name: {} for name in self._fields}

    def has_access(self, operation: str) -> bool:
        return True


def make_manager(fields: dict[str, StubField] | None = None) -> NameManager:
    return NameManager(StubModel(fields), group_definitions=DEFS)


def node_info(view_groups=DEFS.universe, model_groups=DEFS.universe) -> dict:
    return {"model_groups": model_groups, "view_groups": view_groups}


def field_node(name: str) -> etree._Element:
    return etree.Element("field", name=name)


def declare(
    manager: NameManager, name: str, groups=DEFS.universe, model_groups=DEFS.universe
) -> None:
    """Declare a ``<field>`` element for ``name`` shown to ``groups``.

    ``model_groups`` mirrors the ``has_field`` invariant: for a field with
    python ``groups``, the postprocessing ANDs them into
    ``node_info["model_groups"]`` before calling ``has_field``.
    """
    manager.has_field(
        field_node(name), name, node_info(view_groups=groups, model_groups=model_groups)
    )


def use(manager: NameManager, name: str, groups=DEFS.universe) -> etree._Element:
    """Reference ``name`` from a modifier on a node shown to ``groups``;
    return the referencing node."""
    node = field_node("other")
    manager.must_have_fields(
        node,
        {name},
        node_info(view_groups=groups),
        (
            "invisible",
            name,
        ),
    )
    return node


class TestGetMissingFields:
    def test_used_and_declared_for_everyone(self):
        manager = make_manager({"field_a": StubField()})
        declare(manager, "field_a")
        use(manager, "field_a")
        assert manager.get_missing_fields() == {}

    def test_used_but_never_declared(self):
        """A field referenced by an expression but absent from the view is
        missing for the whole group universe."""
        manager = make_manager({"field_a": StubField()})
        node = use(manager, "field_a")
        missing = manager.get_missing_fields()
        assert set(missing) == {"field_a"}
        missing_groups, reasons = missing["field_a"]
        assert missing_groups is not False
        assert missing_groups.is_universal()
        assert reasons == [(DEFS.universe, ("invisible", "field_a"), node)]

    def test_use_disjoint_from_field_groups_is_error(self):
        """Using a field whose python groups can never match the users seeing
        the referencing node yields the ``False`` (hard error) sentinel."""
        manager = make_manager({"field_a": StubField(groups="base.group_system")})
        declare(manager, "field_a", groups=SYSTEM, model_groups=SYSTEM)
        node = use(manager, "field_a", groups=PORTAL)
        missing = manager.get_missing_fields()
        missing_groups, reasons = missing["field_a"]
        assert missing_groups is False
        assert reasons == [(PORTAL, ("invisible", "field_a"), node)]

    def test_use_within_declared_groups(self):
        """system ⊆ system: the declared node covers every user of the
        referencing node, nothing is missing."""
        manager = make_manager({"field_a": StubField()})
        declare(manager, "field_a", groups=SYSTEM)
        use(manager, "field_a", groups=SYSTEM)
        assert manager.get_missing_fields() == {}

    def test_use_wider_than_declared_groups(self):
        """system ⊂ manager: managers without system see the referencing node
        but not the field — it is missing for the manager groups."""
        manager = make_manager({"field_a": StubField()})
        declare(manager, "field_a", groups=SYSTEM)
        use(manager, "field_a", groups=MANAGER)
        missing = manager.get_missing_fields()
        missing_groups, _reasons = missing["field_a"]
        assert missing_groups is not False
        # whole manager group reported; the "manager minus system" subtraction
        # happens later, in _add_missing_fields
        assert missing_groups == MANAGER
        assert not missing_groups.is_universal()

    def test_union_of_declarations_covers_use(self):
        """A field declared once per group covers a use shown to the union of
        those groups."""
        manager = make_manager({"field_a": StubField()})
        declare(manager, "field_a", groups=SYSTEM)
        declare(manager, "field_a", groups=PORTAL)
        use(manager, "field_a", groups=SYSTEM | PORTAL)
        assert manager.get_missing_fields() == {}

    def test_partial_declaration_union_still_missing(self):
        """Declaring for system and portal does not cover plain users."""
        manager = make_manager({"field_a": StubField()})
        declare(manager, "field_a", groups=SYSTEM)
        declare(manager, "field_a", groups=PORTAL)
        use(manager, "field_a", groups=USER)
        missing = manager.get_missing_fields()
        missing_groups, _reasons = missing["field_a"]
        assert missing_groups == USER

    def test_admin_only_use_with_declared_field_is_skipped(self):
        """A use restricted to the empty group (super user only) is ignored
        when the field is declared somewhere in the view."""
        manager = make_manager({"field_a": StubField()})
        declare(manager, "field_a", groups=SYSTEM)
        use(manager, "field_a", groups=DEFS.empty)
        assert manager.get_missing_fields() == {}

    def test_admin_only_use_without_declared_field(self):
        """A super-user-only use of an undeclared field is still recorded,
        with the empty set as missing groups."""
        manager = make_manager({"field_a": StubField()})
        use(manager, "field_a", groups=DEFS.empty)
        missing = manager.get_missing_fields()
        missing_groups, _reasons = missing["field_a"]
        assert missing_groups is not False
        assert missing_groups.is_empty()

    def test_unknown_field_gets_empty_access_groups(self):
        """A name that is neither a model field nor available in the view has
        empty access groups: any non-empty use is a hard error."""
        manager = make_manager({})
        node = use(manager, "no_such_field", groups=SYSTEM)
        missing = manager.get_missing_fields()
        missing_groups, reasons = missing["no_such_field"]
        assert missing_groups is False
        assert reasons == [(SYSTEM, ("invisible", "no_such_field"), node)]

    def test_multiple_uses_aggregate_missing_groups(self):
        """Missing groups accumulate (union) over distinct use groups."""
        manager = make_manager({"field_a": StubField()})
        use(manager, "field_a", groups=SYSTEM)
        use(manager, "field_a", groups=PORTAL)
        missing = manager.get_missing_fields()
        missing_groups, reasons = missing["field_a"]
        assert missing_groups == SYSTEM | PORTAL
        assert len(reasons) == 2


class TestParentRouting:
    def test_parent_prefixed_names_route_to_parent_manager(self):
        parent = make_manager({"field_p": StubField()})
        child = NameManager(
            StubModel({"field_c": StubField()}),
            parent=parent,
            group_definitions=DEFS,
        )
        child.must_have_fields(
            field_node("other"),
            {"parent.field_p", "field_c"},
            node_info(),
            ("invisible", "parent.field_p or field_c"),
        )
        assert "field_c" in child.used_fields
        assert "parent.field_p" not in child.used_fields
        assert "field_p" in parent.used_fields

    def test_parent_prefixed_name_in_root_view_is_tolerated(self):
        """A ``parent.`` reference with no parent manager is silently skipped
        (dual-use embedded forms)."""
        manager = make_manager({"field_a": StubField()})
        manager.must_have_fields(
            field_node("other"),
            {"parent.field_x"},
            node_info(),
            ("invisible", "parent.field_x"),
        )
        assert manager.used_fields == {}
        assert manager.get_missing_fields() == {}
