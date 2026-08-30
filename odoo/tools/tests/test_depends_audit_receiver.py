import unittest
from opcode import opmap

from odoo.tools import depends_audit
from odoo.tools.depends_audit import accessed_attribute_names


class TestForeignReadsAreNotOurs(unittest.TestCase):
    def test_a_chain_through_env_contributes_nothing(self):
        def compute(self):
            return self.env.user.name

        self.assertEqual(accessed_attribute_names(compute), set())

    def test_a_long_chain_through_env_contributes_nothing(self):
        def compute(self):
            return self.env.company.currency_id.symbol

        self.assertEqual(accessed_attribute_names(compute), set())

    def test_our_own_reads_survive_beside_a_foreign_one(self):
        def compute(self):
            return self.name + self.env.user.login

        self.assertEqual(accessed_attribute_names(compute), {"name"})

    def test_a_read_through_one_of_our_own_fields_is_still_reported(self):
        def compute(self):
            return self.partner_id.name

        self.assertEqual(accessed_attribute_names(compute), {"name", "partner_id"})

    def test_a_fused_local_load_does_not_blind_the_guard(self):
        def compute(self, other):
            first = self.env.user
            second = other.partner_id
            return first, second

        self.assertEqual(accessed_attribute_names(compute), {"partner_id"})

    def test_a_nested_function_is_walked_too(self):
        def compute(self):
            def inner():
                return self.env.user.name, self.name

            return inner()

        self.assertEqual(accessed_attribute_names(compute), {"name"})

    def test_a_non_function_yields_nothing(self):
        self.assertEqual(accessed_attribute_names(object()), set())  # type: ignore[arg-type]


class TestOpcodeSetsMatchThisInterpreter(unittest.TestCase):
    def test_every_named_opcode_exists(self):
        for name in depends_audit._ATTR_ACCESS | depends_audit._RECEIVER_LOAD:
            with self.subTest(opcode=name):
                self.assertIn(name, opmap)

    def test_naming_a_missing_opcode_is_refused_not_ignored(self):
        with self.assertRaises(RuntimeError) as caught:
            depends_audit._opnames("LOAD_ATTR", "LOAD_METHOD")
        self.assertIn("LOAD_METHOD", str(caught.exception))

    def test_the_fused_loads_this_interpreter_emits_are_covered(self):
        emitted = set()

        def sample(a, b):
            x = a
            y = b
            return x, y

        import dis

        for instruction in dis.get_instructions(sample):
            if instruction.opname.startswith("LOAD_FAST"):
                emitted.add(instruction.opname)
        self.assertTrue(emitted)
        self.assertLessEqual(
            emitted,
            depends_audit._RECEIVER_LOAD,
            "this interpreter emits a LOAD_FAST form the receiver guard cannot see",
        )


if __name__ == "__main__":
    unittest.main()
