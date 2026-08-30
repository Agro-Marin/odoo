import unittest

from odoo.tools.cache import ormcache


class TestOrmcacheNeedsAReceiver(unittest.TestCase):
    def test_a_zero_argument_callable_is_refused_at_decoration(self):
        with self.assertRaises(ValueError) as caught:

            @ormcache()
            def takes_nothing():
                return 1

        message = str(caught.exception)
        self.assertIn("takes no arguments", message)
        self.assertIn("takes_nothing", message)

    def test_a_receiver_by_any_name_is_accepted(self):
        @ormcache()
        def named_records(records, extra):
            return extra

        self.assertTrue(hasattr(named_records, "__cache__"))


if __name__ == "__main__":
    unittest.main()
