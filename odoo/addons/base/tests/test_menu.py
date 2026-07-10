from unittest.mock import patch

from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.base.models.ir_ui_menu import IrUiMenu


class TestMenu(TransactionCase):
    def test_00_menu_deletion(self):
        """Deleting a menu with children promotes those children to top-level."""
        Menu = self.env["ir.ui.menu"]
        root = Menu.create({"name": "Test root"})
        child1 = Menu.create({"name": "Test child 1", "parent_id": root.id})
        child2 = Menu.create({"name": "Test child 2", "parent_id": root.id})
        child21 = Menu.create({"name": "Test child 2-1", "parent_id": child2.id})
        all_ids = [root.id, child1.id, child2.id, child21.id]

        # delete and check that direct children are promoted to top-level
        # cfr. explanation in menu.unlink()
        root.unlink()

        # search() over ir.ui.menu is unfiltered (no visibility filtering at the
        # ORM layer), so a plain search returns archived/hidden menus too.
        remaining = Menu.search([("id", "in", all_ids)], order="id")
        self.assertEqual([child1.id, child2.id, child21.id], remaining.ids)

        orphans = Menu.search(
            [("id", "in", all_ids), ("parent_id", "=", False)], order="id"
        )
        self.assertEqual([child1.id, child2.id], orphans.ids)

    def test_display_name_recomputed_on_ancestor_rename(self):
        """Renaming an ancestor recomputes display_name (which mirrors
        complete_name's recursive triggers) for all descendants (regression
        guard: depends("parent_id")-only triggers left it stale)."""
        Menu = self.env["ir.ui.menu"]
        root = Menu.create({"name": "Path root"})
        child = Menu.create({"name": "Child", "parent_id": root.id})
        grandchild = Menu.create({"name": "Leaf", "parent_id": child.id})
        self.assertEqual(grandchild.display_name, "Path root/Child/Leaf")

        root.name = "Renamed root"
        self.assertEqual(grandchild.display_name, "Renamed root/Child/Leaf")
        self.assertEqual(grandchild.complete_name, "Renamed root/Child/Leaf")


class TestMenuVisibility(TransactionCase):
    """Cover the visibility cache and its gates: group gating, the action-model
    read-ACL gate, dangling/deleted actions, and ancestor force-visibility.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Menu = cls.env["ir.ui.menu"]
        cls.Action = cls.env["ir.actions.act_window"]
        # Employee with only base.group_user: cannot read group_system models
        # such as ir.config_parameter.
        cls.employee = new_test_user(
            cls.env, login="menu_employee", groups="base.group_user"
        )

    def _act_window(self, res_model):
        """Create an act_window action targeting ``res_model``."""
        return self.Action.create(
            {
                "name": f"action {res_model}",
                "res_model": res_model,
                "view_ids": [Command.create({"view_mode": "form"})],
            }
        )

    def test_visible_menu_ids_action_acl_gate(self):
        """A menu whose action targets a model the user cannot read is hidden."""
        readable = self._act_window("res.partner")
        restricted = self._act_window("ir.config_parameter")
        root = self.Menu.create({"name": "ACL root"})
        menu_readable = self.Menu.create(
            {
                "name": "Readable",
                "parent_id": root.id,
                "action": f"{readable._name},{readable.id}",
            }
        )
        menu_restricted = self.Menu.create(
            {
                "name": "Restricted",
                "parent_id": root.id,
                "action": f"{restricted._name},{restricted.id}",
            }
        )

        # admin reads every model, so both action menus are visible
        admin_visible = self.Menu._visible_menu_ids()
        self.assertIn(menu_readable.id, admin_visible)
        self.assertIn(menu_restricted.id, admin_visible)
        # the root is force-shown as an ancestor of a visible action menu
        self.assertIn(root.id, admin_visible)

        # the employee can read res.partner but not ir.config_parameter, so only
        # the readable action menu (and its ancestor) passes the gate
        emp_visible = self.Menu.with_user(self.employee)._visible_menu_ids()
        self.assertIn(menu_readable.id, emp_visible)
        self.assertNotIn(menu_restricted.id, emp_visible)
        self.assertIn(root.id, emp_visible)

    def test_visible_menu_ids_deleted_action_hidden(self):
        """A menu pointing at a deleted action is hidden (no force-visibility)."""
        action = self._act_window("res.partner")
        root = self.Menu.create({"name": "Dangling root"})
        menu = self.Menu.create(
            {
                "name": "Dangling",
                "parent_id": root.id,
                "action": f"{action._name},{action.id}",
            }
        )
        self.assertIn(menu.id, self.Menu._visible_menu_ids())

        action.unlink()
        visible = self.Menu._visible_menu_ids()
        self.assertNotIn(menu.id, visible)
        # the lone child being gone, the empty folder is not force-shown either
        self.assertNotIn(root.id, visible)

    def test_visible_menu_ids_group_gate(self):
        """A group-restricted menu is hidden from users lacking the group, and
        a group-restricted ancestor is not force-shown to them."""
        group = self.env["res.groups"].create({"name": "Menu test group"})
        action = self._act_window("res.partner")
        # parent folder gated on the group; child action menu ungated
        parent = self.Menu.create(
            {"name": "Gated parent", "group_ids": [Command.set(group.ids)]}
        )
        child = self.Menu.create(
            {
                "name": "Child",
                "parent_id": parent.id,
                "action": f"{action._name},{action.id}",
            }
        )

        # employee lacks the group: the child action passes its own (empty)
        # gate, but the gated parent must NOT be force-shown as an ancestor
        emp_visible = self.Menu.with_user(self.employee)._visible_menu_ids()
        self.assertIn(child.id, emp_visible)
        self.assertNotIn(parent.id, emp_visible)

        # grant the group: the parent now passes the gate and is force-shown
        self.employee.write({"group_ids": [Command.link(group.id)]})
        emp_visible = self.Menu.with_user(self.employee)._visible_menu_ids()
        self.assertIn(child.id, emp_visible)
        self.assertIn(parent.id, emp_visible)

    def test_visible_menu_ids_cache_keyed_by_group_set(self):
        """The visibility set is recomputed (not stale) after a group change
        busts the cache, and identical group sets share an entry."""
        action = self._act_window("ir.config_parameter")
        root = self.Menu.create({"name": "Cache root"})
        menu = self.Menu.create(
            {
                "name": "Needs system",
                "parent_id": root.id,
                "action": f"{action._name},{action.id}",
            }
        )

        # warm the cache for the employee: cannot read ir.config_parameter
        self.assertNotIn(
            menu.id, self.Menu.with_user(self.employee)._visible_menu_ids()
        )

        # granting group_system changes the user's group set -> write() on the
        # user clears the cache -> the new set reflects the added access
        self.employee.write(
            {"group_ids": [Command.link(self.env.ref("base.group_system").id)]}
        )
        self.assertIn(menu.id, self.Menu.with_user(self.employee)._visible_menu_ids())

    def test_visible_menu_ids_keyed_on_debug(self):
        """The visibility set distinguishes debug from non-debug: a
        base.group_no_one-gated action menu is hidden unless debug is on."""
        action = self._act_window("res.partner")
        debug_root = self.Menu.create(
            {
                "name": "Debug only root",
                "group_ids": [Command.set(self.env.ref("base.group_no_one").ids)],
                "action": f"{action._name},{action.id}",
            }
        )

        # admin has group_no_one, but it is discarded when not in debug mode
        self.assertNotIn(debug_root.id, self.Menu._visible_menu_ids(False))
        # in debug mode group_no_one is kept, so the gated menu is visible
        self.assertIn(debug_root.id, self.Menu._visible_menu_ids(True))

    def test_load_menus_root_keyed_on_debug(self):
        """load_menus_root keys on the debug flag (regression guard for IUM-L3):
        the cached root set reflects request.session.debug, not the first call."""
        # ormcache key now includes the debug-resolving expression, so the
        # cached value cannot go stale across debug toggles
        self.assertIn(
            "self._get_session_debug()", IrUiMenu.load_menus_root.__cache__.args
        )

        action = self._act_window("res.partner")
        debug_root = self.Menu.create(
            {
                "name": "Debug only root",
                "group_ids": [Command.set(self.env.ref("base.group_no_one").ids)],
                "action": f"{action._name},{action.id}",
            }
        )
        # the new key element is _get_session_debug(): off-request it is False
        self.assertFalse(self.Menu._get_session_debug())

        # off-request (request is None) -> not debug -> group_no_one discarded
        roots_no_debug = self.Menu.load_menus_root()
        self.assertNotIn(debug_root.id, roots_no_debug["all_menu_ids"])

        # in debug mode a real request with session.debug="1" is on the stack,
        # so _get_session_debug() returns "1": before the fix the (uid, lang)
        # key returned the cached non-debug set; now the debug-keyed entry is a
        # cache miss and recomputes with the gated root visible
        with self.debug_mode():
            self.assertEqual(self.Menu._get_session_debug(), "1")
            roots_debug = self.Menu.load_menus_root()
            self.assertIn(debug_root.id, roots_debug["all_menu_ids"])

        # leaving debug mode restores the non-debug root set
        roots_again = self.Menu.load_menus_root()
        self.assertNotIn(debug_root.id, roots_again["all_menu_ids"])


class TestMenuMisc(TransactionCase):
    """Cover copy() name suffixing and web_icon_data computation."""

    def setUp(self):
        super().setUp()
        self.Menu = self.env["ir.ui.menu"]

    def test_copy_suffixes_name(self):
        """copy() appends ' (1)' to a fresh name and increments an existing one."""
        menu = self.Menu.create({"name": "Original"})
        copy1 = menu.copy()
        self.assertEqual(copy1.name, "Original (1)")

        copy2 = copy1.copy()
        self.assertEqual(copy2.name, "Original (2)")

    def test_copy_ignores_mid_name_number(self):
        """Only a trailing "(N)" is a copy counter: a parenthesized number in
        the middle of the name is left untouched (regression guard for the
        unanchored NUMBER_PARENS that turned "Budget (2025) Plan" into
        "Budget (2026) Plan")."""
        menu = self.Menu.create({"name": "Budget (2025) Plan"})
        copy1 = menu.copy()
        self.assertEqual(copy1.name, "Budget (2025) Plan (1)")

        # the trailing counter increments; the mid-name number still does not
        copy2 = copy1.copy()
        self.assertEqual(copy2.name, "Budget (2025) Plan (2)")

    def _count_cache_clears(self):
        """Return (patcher, calls) counting registry cache invalidations
        while the patcher is active."""
        registry_class = type(self.env.registry)
        calls = []
        original = registry_class.clear_cache

        def counting(reg, *cache_names):
            calls.append(cache_names)
            return original(reg, *cache_names)

        return patch.object(registry_class, "clear_cache", counting), calls

    def test_multi_copy_names_and_single_invalidation(self):
        """Copying menus suffixes each name at insert time: one batched create()
        invalidation, not a per-copy rename write that wipes the registry cache."""
        menus = self.Menu.create([{"name": f"Multi {i}"} for i in range(3)])
        patcher, calls = self._count_cache_clears()
        with patcher:
            copies = menus.copy()
        self.assertEqual(
            copies.mapped("name"), ["Multi 0 (1)", "Multi 1 (1)", "Multi 2 (1)"]
        )
        self.assertEqual(
            len(calls),
            1,
            "copying N menus must invalidate the cache once (the batched "
            "create), not once per copied menu",
        )

    def test_copy_suffixes_explicit_default_name(self):
        """An explicit default name is suffixed too (parity with the historical
        post-copy rename)."""
        menu = self.Menu.create({"name": "Original"})
        copy = menu.copy({"name": "Custom"})
        self.assertEqual(copy.name, "Custom (1)")

    def test_empty_operations_do_not_invalidate_cache(self):
        patcher, calls = self._count_cache_clears()
        with patcher:
            self.assertFalse(self.Menu.create([]))
            self.assertTrue(self.Menu.browse().write({"name": "x"}))
            self.assertTrue(self.Menu.browse().unlink())
        self.assertEqual(calls, [])

    def test_web_icon_data_built_icon(self):
        """A built icon (class,color[,bg]) yields no image data."""
        # 3-part built icon: not routed to _read_image at all
        menu3 = self.Menu.create(
            {"name": "Built 3", "web_icon": "fa fa-cog,#000000,#ffffff"}
        )
        self.assertFalse(menu3.web_icon_data)

        # 2-part built icon: routed to _read_image, which returns False for a
        # non-existent file path (harmless conflation, see _compute_web_icon_data)
        menu2 = self.Menu.create({"name": "Built 2", "web_icon": "fa fa-cog,#000000"})
        self.assertFalse(menu2.web_icon_data)

    def test_web_icon_data_image_icon(self):
        """An image icon (module,path) reads the file and yields base64 data."""
        menu = self.Menu.create(
            {"name": "Image icon", "web_icon": "base,static/img/main_partner-image.png"}
        )
        self.assertTrue(menu.web_icon_data)

    def test_read_image_malformed_path(self):
        """_read_image returns False for a value without exactly two parts."""
        self.assertFalse(self.Menu._read_image(""))
        self.assertFalse(self.Menu._read_image("only_one_part"))
        self.assertFalse(self.Menu._read_image("a,b,c"))
