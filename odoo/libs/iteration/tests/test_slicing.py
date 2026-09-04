import unittest
import warnings

from odoo.libs.iteration.slicing import split_every


class TestSplitEvery(unittest.TestCase):
    def test_splits_into_tuples_of_n(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = list(split_every(3, range(7)))
        self.assertEqual(result, [(0, 1, 2), (3, 4, 5), (6,)])

    def test_empty_iterable_yields_nothing(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = list(split_every(3, []))
        self.assertEqual(result, [])

    def test_custom_piece_maker(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = list(split_every(2, range(5), piece_maker=list))
        self.assertEqual(result, [[0, 1], [2, 3], [4]])

    def test_emits_deprecation_warning(self):
        with self.assertWarns(DeprecationWarning):
            list(split_every(2, range(3)))


if __name__ == "__main__":
    unittest.main()
