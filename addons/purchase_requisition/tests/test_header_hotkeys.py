from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestHeaderHotkeys(TransactionCase):
    """Every header button that drives a state change must be reachable by keyboard.

    The purchase order form gives nine of its buttons a `data-hotkey`; the
    purchase agreement form had none at all, and `action_acknowledge` was the
    one hole left in the purchase header.
    """

    def _header_buttons(self, xmlid, model):
        view = self.env.ref(xmlid)
        arch = etree.fromstring(self.env[model].get_view(view.id, "form")["arch"])
        return {
            node.get("name"): node for node in arch.xpath("//header//button[@name]")
        }

    def test_every_purchase_agreement_header_button_has_a_hotkey(self):
        buttons = self._header_buttons(
            "purchase_requisition.view_purchase_requisition_form",
            "purchase.requisition",
        )

        self.assertTrue(buttons, "fixture guard: the header must expose buttons")
        without = sorted(
            name for name, node in buttons.items() if not node.get("data-hotkey")
        )
        self.assertFalse(without, f"header buttons without a hotkey: {without}")

    def test_purchase_agreement_hotkeys_do_not_collide(self):
        buttons = self._header_buttons(
            "purchase_requisition.view_purchase_requisition_form",
            "purchase.requisition",
        )
        hotkeys = [node.get("data-hotkey") for node in buttons.values()]

        self.assertEqual(
            len(hotkeys),
            len(set(hotkeys)),
            "two header buttons of the same form cannot share a letter",
        )
        self.assertFalse(
            set(hotkeys) & {"c", "s", "j"},
            "c/s/j belong to the web form controller (New, Save, Discard)",
        )

    def test_acknowledge_has_a_hotkey_like_its_neighbours(self):
        buttons = self._header_buttons(
            "purchase.view_purchase_order_form",
            "purchase.order",
        )

        self.assertIn("action_acknowledge", buttons)
        hotkey = buttons["action_acknowledge"].get("data-hotkey")
        self.assertTrue(
            hotkey,
            "Acknowledge sits between Send PO (g) and Print (k) with no hotkey",
        )

        # `action_lock`/`action_unlock` and the two Print buttons deliberately
        # share a letter -- they are the same action in two states -- so the
        # check is that Acknowledge did not land on a letter already spoken for
        # by a *different* action.
        taken = {
            node.get("data-hotkey")
            for name, node in buttons.items()
            if name != "action_acknowledge"
        }
        self.assertNotIn(hotkey, taken)
