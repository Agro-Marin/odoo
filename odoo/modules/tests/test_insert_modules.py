"""`_insert_modules` batches what used to be one round trip per module.

`initialize` needed each module's id before it could build the `ir_model_data`
and dependency rows, and reached for it with a per-module
`INSERT ... RETURNING id` -- one round trip per module to collect their ids, on
every database creation, while the rows that consumed them were already
written with `copy_from`. Batched, `initialize` issues one round trip per chunk
instead and writes a byte-identical table (verified against md5 digests over
`ir_module_module`, `ir_model_data` and the dependency table).
"""

import unittest

from odoo.modules.db import _MODULE_COLUMNS, _MODULE_INSERT_CHUNK, _insert_modules

BaseCase = unittest.TestCase


class _Cursor:
    """Assigns ids in insertion order, like a serial column."""

    def __init__(self):
        self.statements = []
        self._returned = []
        self._next_id = 1

    def execute(self, query, params=None):
        self.statements.append((query, params))
        width = len(_MODULE_COLUMNS)
        assert len(params) % width == 0, "parameters do not divide into whole rows"
        names = [params[i * width + 2] for i in range(len(params) // width)]
        self._returned = []
        for name in names:
            self._returned.append((self._next_id, name))
            self._next_id += 1

    def fetchall(self):
        return self._returned


def _rows(names):
    # column 2 is `name`; the rest only has to be positionally present
    return [tuple(f"v{i}" if i != 2 else name for i in range(14)) for name in names]


class TestInsertModules(BaseCase):
    def test_every_module_gets_its_own_id(self):
        cr = _Cursor()
        ids = _insert_modules(cr, _rows(["base", "web", "mail"]))
        self.assertEqual(ids, {"base": 1, "web": 2, "mail": 3})

    def test_one_statement_for_a_normal_module_count(self):
        cr = _Cursor()
        _insert_modules(cr, _rows([f"m{i}" for i in range(500)]))
        self.assertEqual(len(cr.statements), 1)

    def test_the_row_count_is_chunked_below_the_parameter_ceiling(self):
        # The extended protocol caps a statement at 65535 parameters. Over 14
        # columns that is 4681 rows, and this workspace already carries 1554
        # modules.
        count = _MODULE_INSERT_CHUNK * 2 + 7
        cr = _Cursor()
        ids = _insert_modules(cr, _rows([f"m{i}" for i in range(count)]))
        self.assertEqual(len(ids), count)
        self.assertEqual(len(cr.statements), 3)
        for _query, params in cr.statements:
            self.assertLessEqual(len(params), 65535)

    def test_ids_are_correct_across_a_chunk_boundary(self):
        count = _MODULE_INSERT_CHUNK + 3
        cr = _Cursor()
        ids = _insert_modules(cr, _rows([f"m{i}" for i in range(count)]))
        self.assertEqual(ids[f"m{_MODULE_INSERT_CHUNK - 1}"], _MODULE_INSERT_CHUNK)
        self.assertEqual(ids[f"m{_MODULE_INSERT_CHUNK}"], _MODULE_INSERT_CHUNK + 1)
        self.assertEqual(len(set(ids.values())), count, "ids collide across chunks")

    def test_no_modules_issues_no_statement(self):
        cr = _Cursor()
        self.assertEqual(_insert_modules(cr, []), {})
        self.assertEqual(cr.statements, [])

    def test_the_statement_names_every_column_once(self):
        cr = _Cursor()
        _insert_modules(cr, _rows(["base"]))
        query, params = cr.statements[0]
        for column in _MODULE_COLUMNS:
            self.assertIn(column, query)
        self.assertEqual(len(params), len(_MODULE_COLUMNS))
        self.assertIn("RETURNING id, name", query)
