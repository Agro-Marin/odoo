import ast
from pathlib import Path
from textwrap import dedent

from odoo.modules import Manifest
from odoo.tests.common import BaseCase, no_retry

from . import (
    _checker_batch,
    _checker_gettext,
    _checker_noqa_rationale,
    _checker_onchange,
    _checker_orm_import,
    _checker_sql,
    _checker_unlink,
    _suppression,
    lint_case,
)


@no_retry
class TestSuppression(BaseCase):
    def test_bare_noqa_suppresses_everything(self):
        self.assertTrue(_suppression.is_suppressed("x  # noqa", 1, "sql-injection"))

    def test_rationale_does_not_cancel_the_suppression(self):
        for line in (
            "x  # noqa  because the column name is a legacy alias",
            "x  # noqa: E8501 -- table name comes from _table",
            "x  # noqa: E8501, F401  re-exported by __init__",
        ):
            with self.subTest(line=line):
                self.assertTrue(
                    _suppression.is_suppressed(line, 1, "sql-injection"),
                    "explaining a suppression must not undo it",
                )

    def test_codes_scope_the_suppression(self):
        self.assertFalse(
            _suppression.is_suppressed("x  # noqa: F401  unused", 1, "sql-injection"),
            "an unrelated code must not silence this rule",
        )

    def test_rule_name_and_numeric_alias_are_equivalent(self):
        for code in ("E8507", "e8507", "n-plus-one-query"):
            with self.subTest(code=code):
                self.assertTrue(
                    _suppression.is_suppressed(
                        f"x  # noqa: {code}  hoisting needs a schema change",
                        1,
                        "n-plus-one-query",
                    )
                )

    def test_a_rule_named_in_full_scopes_the_suppression_too(self):
        line = "x  # noqa: sql-injection  the table name comes from _table"
        self.assertTrue(_suppression.is_suppressed(line, 1, "sql-injection"))
        self.assertFalse(
            _suppression.is_suppressed(line, 1, "n-plus-one-query"),
            "naming one rule must not waive the others on the line",
        )

    def test_an_unparseable_code_list_silences_nothing(self):
        self.assertFalse(
            _suppression.is_suppressed("x  # noqa: !!!  see above", 1, "sql-injection")
        )

    def test_case_does_not_decide_whether_a_suppression_works(self):
        line = "x  # NOQA: E8501  the table name comes from _table"
        self.assertTrue(_suppression.is_suppressed(line, 1, "sql-injection"))
        self.assertFalse(list(_checker_noqa_rationale.find_violations(line)))
        self.assertTrue(
            _suppression.is_suppressed(
                "x  # PYLINT: disable=sql-injection", 1, "sql-injection"
            )
        )


@no_retry
class TestNoqaRationale(BaseCase):
    def _violations(self, line):
        return list(_checker_noqa_rationale.find_violations(line))

    def test_a_rule_name_is_not_its_own_rationale(self):
        self.assertTrue(self._violations("x  # noqa: E8501"))
        self.assertTrue(
            self._violations("x  # noqa: sql-injection"),
            "naming the rule is not a reason for waiving it",
        )
        self.assertTrue(self._violations("x  # noqa: sql-injection, E8507"))

    def test_a_real_rationale_still_passes(self):
        for line in (
            "x  # noqa: E8501  the table name comes from _table",
            "x  # noqa: sql-injection  the table name comes from _table",
            "x  # noqa  the column is a legacy alias",
        ):
            with self.subTest(line=line):
                self.assertFalse(self._violations(line))

    def test_both_spellings_agree_with_the_suppression_module(self):
        for line in ("x  # noqa: E8501", "x  # noqa: sql-injection", "x  # noqa"):
            with self.subTest(line=line):
                self.assertTrue(
                    _suppression.is_suppressed(line, 1, "sql-injection"),
                    "this line silences the rule",
                )
                self.assertTrue(
                    self._violations(line),
                    "so it has to be asked for a reason",
                )

    def test_pylint_disable_is_still_honoured(self):
        self.assertTrue(
            _suppression.is_suppressed(
                "x  # pylint: disable=sql-injection", 1, "sql-injection"
            )
        )

    def test_the_rationale_rule_cannot_silence_itself(self):
        self.assertFalse(
            _suppression.is_suppressed("x  # noqa", 1, _suppression.NOQA_RATIONALE_RULE)
        )


@no_retry
class TestCorePathScoping(BaseCase):
    # Every file-based gate in this module is scoped by `is_core_path`, so a
    # wrong answer here silently changes what all of them enforce.

    def test_a_sibling_checkout_is_not_core(self):
        # The bug: a bare string prefix. This workspace holds `odoo` and
        # `odoo-companion` side by side, and "<root>-companion".startswith(root)
        # is True -- so a sibling whose name merely begins with this one's
        # counted as core, and every rule here would have been enforced against
        # a separately-versioned checkout.
        root = lint_case.core_root()
        self.assertTrue(lint_case.is_core_path(root))
        self.assertTrue(lint_case.is_core_path(str(Path(root) / "addons" / "x.py")))
        for sibling in (f"{root}-companion", f"{root}_legacy", f"{root}2"):
            with self.subTest(sibling=sibling):
                self.assertFalse(
                    lint_case.is_core_path(str(Path(sibling) / "x.py")),
                    "a separately-versioned checkout is not this repository",
                )

    def test_the_real_siblings_on_this_addons_path_are_excluded(self):
        # The claim the scoping actually rests on, asserted against the live
        # addons_path rather than against invented paths.
        roots = [manifest.path for manifest in Manifest.all_addon_manifests()]
        self.assertTrue(roots, "no addon roots at all")
        core = [path for path in roots if lint_case.is_core_path(str(path))]
        self.assertTrue(core, "no core addon roots -- the scoping reached nothing")
        self.assertTrue(
            all(Path(lint_case.core_root()) in Path(path).parents for path in core),
            "is_core_path admitted a root outside this repository",
        )


@no_retry
class TestOrmImportLint(BaseCase):
    def _check(self, snippet, filepath="models/thing.py"):
        return list(_checker_orm_import.check(ast.parse(dedent(snippet).strip())))

    def test_direct_import_flagged(self):
        self.assertTrue(self._check("import odoo.orm.fields"))
        self.assertTrue(self._check("from odoo.orm import fields"))
        self.assertTrue(self._check("from odoo.orm.fields import Many2one"))

    def test_facade_import_allowed(self):
        self.assertFalse(self._check("from odoo import api, fields, models"))
        self.assertFalse(self._check("import odoo.ormsomething"))

    def test_string_mentioning_odoo_orm_is_not_an_import(self):
        self.assertFalse(self._check("DOC = 'see odoo.orm.fields for details'"))


@no_retry
class TestOnchangeLint(BaseCase):
    def _check(self, snippet):
        return list(_checker_onchange.check(ast.parse(dedent(snippet).strip())))

    def test_domain_in_onchange_flagged(self):
        self.assertTrue(
            self._check("""
        @api.onchange('partner_id')
        def _onchange_partner(self):
            return {'domain': {'x': []}}
        """)
        )

    def test_domain_outside_onchange_ignored(self):
        self.assertFalse(
            self._check("""
        def _compute_something(self):
            return {'domain': {'x': []}}
        """)
        )

    def test_one_report_per_method(self):
        self.assertEqual(
            len(
                self._check("""
            @api.onchange('a')
            def _onchange_a(self):
                x = {'domain': []}
                y = {'domain': []}
                return {'domain': []}
            """)
            ),
            1,
        )


@no_retry
class TestSqlLint(BaseCase):
    def _check(self, snippet, filepath="dummy.py", is_test=False):
        source = dedent(snippet).strip()
        tree = ast.parse(source)
        _checker_sql.annotate_parents(tree)
        checker = _checker_sql.SqlInjectionChecker(filepath, is_test=is_test)
        return list(checker.check(tree))

    def test_printf(self):
        violations = self._check("""
        def do_the_thing(cr, name):
            cr.execute('select %s from thing' % name)
        """)
        self.assertTrue(violations, "should have noticed the injection")
        self.assertEqual(violations[0].lineno, 2)

        violations = self._check("""
        def do_the_thing(self):
            self.env.cr.execute("select thing from %s" % self._table)
        """)
        self.assertFalse(violations, "underscore-attributes are allowed")

        violations = self._check("""
        def do_the_thing(self):
            query = "select thing from %s"
            self.env.cr.execute(query % self._table)
        """)
        self.assertFalse(violations, "underscore-attributes are allowed")

    def test_fstring(self):
        violations = self._check("""
        def do_the_thing(cr, name):
            cr.execute(f'select {name} from thing')
        """)
        self.assertTrue(violations, "should have noticed the injection")
        self.assertEqual(violations[0].lineno, 2)

        violations = self._check("""
        def do_the_thing(cr, name):
            cr.execute(f'select name from thing')
        """)
        self.assertFalse(violations, "unnecessary fstring should be innocuous")

        violations = self._check("""
        def do_the_thing(self):
            self.env.cr.execute(f'select name from {self._table}')
        """)
        self.assertFalse(violations, "underscore-attributes are allowable")

    def test_const_concat(self):
        violations = self._check("""
        def test():
            arg = "test"
            arg = arg + arg
            self.env.cr.execute(arg)
        """)
        self.assertFalse(violations)

    def test_percent_with_param(self):
        violations = self._check("""
        def test_function9(self, arg):
            my_injection_variable = "aaa" % arg
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertTrue(violations)

    def test_const_plus_const(self):
        violations = self._check("""
        def test_function10(self):
            my_injection_variable = "aaa" + "aaa"
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertFalse(violations)

    def test_const_plus_arg(self):
        violations = self._check("""
        def test_function11(self, arg):
            my_injection_variable = "aaaaaaaa" + arg
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertTrue(violations)

    def test_transitive_const_chain(self):
        violations = self._check("""
        def test_function12(self):
            arg1 = "a"
            arg2 = "b" + arg1
            arg3 = arg2 + arg1 + arg2
            arg4 = arg1 + "d"
            my_injection_variable = arg1 + arg2 + arg3 + arg4
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertFalse(violations)

    def test_fstring_with_param(self):
        violations = self._check("""
        def test_function1(self, arg):
            my_injection_variable = f"aaaaa{arg}aaa"
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertTrue(violations)

    def test_fstring_with_const_var(self):
        violations = self._check("""
        def test_function2(self):
            arg = 'bbb'
            my_injection_variable = f"aaaaa{arg}aaa"
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertFalse(violations)

    def test_format_no_args(self):
        violations = self._check("""
        def test_function3(self, arg):
            my_injection_variable = "aaaaaaaa".format()
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertFalse(violations)

    def test_format_keyword_const(self):
        violations = self._check("""
        def test_function4(self, arg):
            my_injection_variable = "aaaaaaaa {test}".format(test="aaa")
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertFalse(violations)

    def test_format_keyword_const_var(self):
        violations = self._check("""
        def test_function5(self):
            arg = 'aaa'
            my_injection_variable = "aaaaaaaa {test}".format(test=arg)
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertFalse(violations)

    def test_format_keyword_nonconst(self):
        violations = self._check("""
        def test_function6(self, arg):
            my_injection_variable = "aaaaaaaa {test}".format(test="aaa" + arg)
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertTrue(violations)

    def test_format_keyword_const_chain(self):
        violations = self._check("""
        def test_function7(self):
            arg = "aaa"
            my_injection_variable = "aaaaaaaa {test}".format(test="aaa" + arg)
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertFalse(violations)

    def test_format_global_var(self):
        violations = self._check("""
        def test_function8(self):
            global arg
            my_injection_variable = "aaaaaaaa {test}".format(test="aaa" + arg)
            self.env.cr.execute('select * from hello where id = %s' % my_injection_variable)
        """)
        self.assertTrue(violations)

    def test_ternary_const_branches(self):
        violations = self._check("""
        def test_function10(self, arg):
            if_else_variable = "aaa" if arg else "bbb"
            self.env.cr.execute('select * from hello where id = %s' % if_else_variable)
        """)
        self.assertFalse(violations)

    def test_a_private_method_is_not_a_licence(self):
        snippet = """
        def {name}(self, user_input):
            self.env.cr.execute("SELECT * FROM t WHERE x = '%s'" % user_input)
        """
        self.assertTrue(self._check(snippet.format(name="do_thing")))
        self.assertTrue(
            self._check(snippet.format(name="_do_thing")),
            "a leading underscore is a naming convention, not a safety proof",
        )

    def test_an_identifier_from_self_is_still_allowed(self):
        self.assertFalse(
            self._check("""
        def _init_column(self, value):
            query = f'UPDATE "{self._table}" SET "{self._rec_name}" = %s'
            self.env.cr.execute(query, (value,))
        """)
        )

    def test_real_false_positive_private_function(self):
        violations = self._check("""
        def _search_phone_mobile_search(self, operator, value):
            condition = 'IS NULL' if operator == '=' else 'IS NOT NULL'
            query = '''
                SELECT model.id
                FROM %s model
                WHERE model.phone %s
                AND model.mobile %s
            ''' % (self._table, condition, condition)
            self.env.cr.execute(query)
        """)
        self.assertFalse(violations)

    def test_tuple_assignment(self):
        violations = self._check("""
        def test1(self):
            operator = 'aaa'
            value = 'bbb'
            op1, val1 = (operator, value)
            self.env.cr.execute('query' + op1)
        """)
        self.assertFalse(violations)

    def test_augassign_const(self):
        violations = self._check("""
        def test2(self):
            operator = 'aaa'
            operator += 'bbb'
            self.env.cr.execute('query' + operator)
        """)
        self.assertFalse(violations)

    def test_fstring_self_table(self):
        violations = self._check("""
        def test3(self):
            self.env.cr.execute(f'{self._table}')
        """)
        self.assertFalse(violations)

    def test_private_function_fstring_with_param(self):
        violations = self._check("""
        def _init_column(self, column_name):
            query = f'UPDATE "{self._table}" SET "{column_name}" = %s WHERE "{column_name}" IS NULL'
            self.env.cr.execute(query, (value,))
        """)
        self.assertTrue(violations)

    def test_a_self_referential_accumulation_terminates(self):
        violations = self._check("""
        def _build(self, parts, pids):
            where_clause = " OR ".join(parts)
            if pids:
                where_clause = "(%s) AND (%s)" % (where_clause, "fol.partner_id = ANY(%s)")
            self.env.cr.execute("SELECT id FROM t WHERE " + where_clause)
        """)
        self.assertTrue(violations, "an accumulated value is not a constant")

    def test_dict_format_const(self):
        violations = self._check("""
        def _init_column1(self, column_name):
            query = 'SELECT %(var1)s FROM %(var2)s WHERE %(var3)s' % {'var1': 'field_name', 'var2': 'table_name', 'var3': 'where_clause'}
            self.env.cr.execute(query)
        """)
        self.assertFalse(violations)

    def test_complex_private_function(self):
        violations = self._check("""
        def _graph_data(self, start_date, end_date):
            query = '''SELECT %(x_query)s as x_value, %(y_query)s as y_value
                        FROM %(table)s
                        WHERE team_id = %(team_id)s
                        AND DATE(%(date_column)s) >= %(start_date)s
                        AND DATE(%(date_column)s) <= %(end_date)s
                        %(extra_conditions)s
                        GROUP BY x_value;'''
            dashboard_graph_model = self._graph_get_model()
            GraphModel = self.env[dashboard_graph_model]
            graph_table = self._graph_get_table(GraphModel)
            extra_conditions = self._extra_sql_conditions()
            where_query = GraphModel._search([])
            from_clause, where_clause, where_clause_params = where_query.get_sql()
            if where_clause:
                extra_conditions += " AND " + where_clause
            query = query % {
                'x_query': self._graph_x_query(),
                'y_query': self._graph_y_query(),
                'table': graph_table,
                'team_id': "%s",
                'date_column': self._graph_date_column(),
                'start_date': "%s",
                'end_date': "%s",
                'extra_conditions': extra_conditions,
            }
            self.env.cr.execute(query, [self.id, start_date, end_date] + where_clause_params)
            return self.env.cr.dictfetchall()
        """)
        self.assertFalse(violations)

    def test_cross_function_const_return(self):
        violations = self._check("""
        def first_fun():
            return 'a'

        def injectable():
            cr.execute(first_fun())
        """)
        self.assertFalse(violations)

    def test_cross_function_param_with_const_call(self):
        violations = self._check("""
        def second_fun(value):
            return value

        def injectable1():
            cr.execute(second_fun('aaaaa'))
        """)
        self.assertFalse(violations)

    def test_join_const_list(self):
        violations = self._check("""
        def injectable2(var):
            a = ['a', 'b']
            cr.execute('a'.join(a))
        """)
        self.assertFalse(violations)

    def test_cross_function_tuple_position(self):
        violations = self._check("""
        def return_tuple(var):
            return 'a', var

        def injectable4(var):
            a, _ = return_tuple(var)
            cr.execute(a)
        """)
        self.assertFalse(violations)

    def test_starred_const_tuple(self):
        violations = self._check("""
        def not_injectable5(var):
            star = ('defined', 'constant', 'string')
            cr.execute(*star)
        """)
        self.assertFalse(violations)

    def test_starred_nonconst_tuple(self):
        violations = self._check("""
        def injectable6(var):
            star = ('defined', 'variable', 'string', var)
            cr.execute(*star)
        """)
        self.assertTrue(violations)

    def test_percent_d_format(self):
        violations = self._check("""
        def formatNumber(var):
            cr.execute('LIMIT %d' % var)
        """)
        self.assertFalse(violations)

    def test_sql_call_with_variable(self):
        violations = self._check("""
        def wrapper1(var):
            query = SQL(var)
            return query
        """)
        self.assertTrue(violations)

    def test_tools_sql_call_with_variable(self):
        violations = self._check("""
        def wrapper2(var):
            query = tools.SQL(var)
            return query
        """)
        self.assertTrue(violations)

    def test_every_cursor_spelling_is_recognised(self):
        snippet = """
        def do_the_thing(self, env, cr, table):
            {cursor}.execute("SELECT * FROM " + table)
        """
        for cursor in ("self.env.cr", "self.cr", "self._cr", "cr", "env.cr"):
            with self.subTest(cursor=cursor):
                self.assertTrue(
                    self._check(snippet.format(cursor=cursor)),
                    f"{cursor} is a cursor; its query has to be checked",
                )

    def test_test_code_is_exempt(self):
        snippet = """
        def do_the_thing(cr, name):
            cr.execute('select %s from thing' % name)
        """
        self.assertTrue(self._check(snippet))
        self.assertFalse(self._check(snippet, is_test=True))


@no_retry
class TestGetTextLint(BaseCase):
    def _check(self, snippet, filepath="not_test.py"):
        source = dedent(snippet).strip()
        tree = ast.parse(source)
        return list(_checker_gettext.check(tree))

    def test_gettext_env(self):
        violations = self._check("""
        def method(self, vars):
            _("something %s %s", *vars)
        """)
        placeholders = [v for v in violations if v.rule == "gettext-placeholders"]
        self.assertTrue(placeholders, "_() should flag multiple placeholders")

        violations = self._check("""
        def method(self, vars):
            self.env._("something %s %s", *vars)
        """)
        placeholders = [v for v in violations if v.rule == "gettext-placeholders"]
        self.assertTrue(placeholders, "self.env._() should flag multiple placeholders")

    def test_gettext_variable(self):
        violations = self._check("""
        some_variable = "Roblox Mini Golf! [ACTUALLY FIXED]"
        _(some_variable)
        _lt(513)
        _lt("string but" + "not static")
        _(f"formatted string")
        """)
        variable_violations = [v for v in violations if v.rule == "gettext-variable"]
        self.assertEqual(len(variable_violations), 4)

    def test_placeholder_counting(self):
        def count(text):
            return len(_checker_gettext.PLACEHOLDER_REGEXP.findall(text))

        self.assertEqual(count("%s %s"), 2)
        self.assertEqual(count("Item%s and %s"), 2, "a placeholder may follow a word")
        self.assertEqual(count("%%s %%s"), 0, "escaped percents are not placeholders")
        self.assertEqual(count("%%%s"), 1, "an escaped percent then a real one")
        self.assertEqual(count("100%% of %s and %s"), 2)
        self.assertEqual(count("%(named)s %(other)s"), 0, "named ones are the fix")
        self.assertEqual(count("%i of %i"), 2, "%i is a Python conversion")
        self.assertEqual(count("%u and %u"), 2, "so is %u")
        self.assertEqual(count("%a and %a"), 2, "and %a")

    def test_the_conversion_types_are_the_ones_python_has(self):
        import re as _re

        types = _checker_gettext.PLACEHOLDER_REGEXP.pattern
        for char in "diouxXeEfFgGcrsa":
            with self.subTest(conversion=char):
                self.assertEqual(
                    len(
                        _checker_gettext.PLACEHOLDER_REGEXP.findall(f"%{char} %{char}")
                    ),
                    2,
                )
        for char in "bnwz":
            with self.subTest(conversion=char):
                self.assertFalse(
                    _checker_gettext.PLACEHOLDER_REGEXP.findall(f"%{char}"),
                    f"%{char} raises at runtime; it is not a placeholder",
                )
        self.assertNotIn("bcdeEfFgGnorsxX", _re.sub(r"\s|#.*", "", types))

    def test_gettext_placeholders(self):
        violations = self._check("""
        _("shouldn't match escaped %%s %%s")
        """)
        placeholders = [v for v in violations if v.rule == "gettext-placeholders"]
        self.assertFalse(placeholders)

        violations = self._check("""
        _("more than one unnamed placeholder: %s %s")
        _lt("with fancy placeholders: %03.14d %-xL")
        """)
        placeholders = [v for v in violations if v.rule == "gettext-placeholders"]
        self.assertEqual(len(placeholders), 2)

    def test_gettext_repr(self):
        violations = self._check("""
        _("%r shouldn't be part of translated strings")
        _lt("%(with_placeholders_in_between)r")
        """)
        repr_violations = [v for v in violations if v.rule == "gettext-repr"]
        self.assertEqual(len(repr_violations), 2)

    def test_missing_gettext_no_errors(self):
        violations = self._check("""
        raise UserError(_('This is translated'))
        some_var = 'This is not translated'
        raise UserError(some_var)
        raise UserError(some_var + _('This is translated'))
        raise UserError(_('This is translated') and some_var)
        raise UserError(_('This is translated') if true else some_var)
        def some_call():
            return _("nothing")
        some_arr = ["random_string", _("another_random_string")]
        raise UserError(some_arr[0])
        """)
        missing = [v for v in violations if v.rule == "missing-gettext"]
        self.assertEqual(len(missing), 0)

    def test_missing_gettext_catching_errors(self):
        violations = self._check("""
        UserError('This is not translated')
        exceptions.UserError('This is also not translated')
        UserError(f'This is an f-string')
        raise UserError('This is not translated' + 'This is also not translated')
        some_var = 'random_string'
        raise UserError('This is not translated' and some_var)
        raise UserError('This is not translated' if true else _('This is translated'))
        """)
        missing = [v for v in violations if v.rule == "missing-gettext"]
        self.assertEqual(len(missing), 6)

    def test_a_literal_concatenated_onto_a_translation_still_ships_untranslated(self):
        # `_is_whitelisted_argument` accepted a BinOp when EITHER half was
        # whitelisted, which is right for `_("%(a)s") % {...}` -- only the left
        # half is the message there -- and wrong for `+`, where both halves
        # are. `_("Error:") + "\n".join(errors)` is fine; the same line without
        # the `_()` shipped a user-facing sentence no translator ever sees, and
        # the rule said nothing because `"\n".join(...)` is a Call.
        for snippet, expected in (
            ("""raise UserError(_('Error') + "\\n".join(errors))""", 0),
            ("""raise UserError("Error:\\n" + "\\n".join(errors))""", 1),
            ("""raise UserError(_('Translated') + " and this is not")""", 1),
            ("""raise UserError(prefix + suffix)""", 0),
            ("""raise UserError(_('%(a)s and %(b)s') % {'a': x, 'b': y})""", 0),
        ):
            with self.subTest(snippet=snippet):
                missing = [
                    v for v in self._check(snippet) if v.rule == "missing-gettext"
                ]
                self.assertEqual(len(missing), expected, snippet)


@no_retry
class TestUnlinkLint(BaseCase):
    def _check(self, snippet):
        source = dedent(snippet).strip()
        tree = ast.parse(source)
        return list(_checker_unlink.check(tree))

    def test_raise_in_unlink(self):
        violations = self._check("""
        class MyModel(models.Model):
            def unlink(self):
                if self.state == 'posted':
                    raise UserError("Cannot delete posted record")
                return super().unlink()
        """)
        self.assertTrue(violations, "raise inside unlink should be flagged")

    def test_no_raise_in_unlink(self):
        violations = self._check("""
        class MyModel(models.Model):
            def unlink(self):
                self._check_delete()
                return super().unlink()
        """)
        self.assertFalse(violations, "no raise means no violation")

    def test_non_model_class(self):
        violations = self._check("""
        class NotAModel:
            def unlink(self):
                raise ValueError("this is fine")
        """)
        self.assertFalse(violations, "non-model classes should not be flagged")

    def test_model_variants(self):
        for base in (
            "models.Model",
            "models.TransientModel",
            "models.AbstractModel",
        ):
            with self.subTest(base=base):
                violations = self._check(f"""
                class MyModel({base}):
                    def unlink(self):
                        raise UserError("nope")
                        return super().unlink()
                """)
                self.assertTrue(violations, f"{base} should be detected as model class")


@no_retry
class TestBatchLint(BaseCase):
    def _check(self, snippet, filepath="not_test.py"):
        source = dedent(snippet).strip()
        tree = ast.parse(source)
        return list(_checker_batch.check(tree))

    def test_search_in_for_loop(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                partners = self.env['res.partner'].search([('id', '=', record.id)])
        """)
        self.assertTrue(violations, "search inside for loop should be flagged")
        self.assertIn("search()", violations[0].message)

    def test_search_count_in_for_loop(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                count = self.env['res.partner'].search_count([('id', '=', record.id)])
        """)
        self.assertTrue(violations, "search_count inside for loop should be flagged")
        self.assertIn("search_count()", violations[0].message)

    def test_search_fetch_in_for_loop(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                data = self.env['res.partner'].search_fetch([('id', '=', record.id)], ['name'])
        """)
        self.assertTrue(violations, "search_fetch inside for loop should be flagged")

    def test_read_group_in_for_loop(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                groups = self.env['sale.order']._read_group(
                    [('partner_id', '=', record.id)],
                    groupby=['state'],
                    aggregates=['amount_total:sum'],
                )
        """)
        self.assertTrue(violations, "_read_group inside for loop should be flagged")

    def test_search_outside_loop_ok(self):
        violations = self._check("""
        def process(self, records):
            partners = self.env['res.partner'].search([('active', '=', True)])
            for record in records:
                partner = partners.filtered(lambda p: p.id == record.id)
        """)
        self.assertFalse(violations, "search outside loop should not be flagged")

    def test_nested_for_loop(self):
        violations = self._check("""
        def process(self, orders):
            for order in orders:
                for line in order.order_line:
                    products = self.env['product.product'].search([('id', '=', line.product_id.id)])
        """)
        self.assertTrue(violations, "search in nested loop should be flagged")

    def test_nested_function_def_skipped(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                def helper():
                    return self.env['res.partner'].search([('active', '=', True)])
        """)
        self.assertFalse(
            violations, "search inside nested function should not be flagged"
        )

    def test_lambda_in_loop_not_flagged(self):
        violations = self._check("""
        def process(self, records):
            callbacks = []
            for record in records:
                callbacks.append(lambda: self.env['res.partner'].search([]))
        """)
        self.assertFalse(
            violations, "a lambda defers its body, like the nested def above"
        )

    def test_nested_loops_report_one_query_once(self):
        for depth in (1, 2, 3, 4):
            body = "self.env['res.partner'].search([])"
            for level in range(depth):
                body = f"for x{level} in a:\n    " + body.replace("\n", "\n    ")
            source = "def process(self, a):\n    " + body.replace("\n", "\n    ")
            with self.subTest(depth=depth):
                self.assertEqual(len(self._check(source)), 1)

    def test_async_for_is_a_loop_too(self):
        # `ast.AsyncFor` is a separate node type, so the entry-point scan
        # skipped it entirely: the same query, in a loop that runs its body
        # once per item exactly as `for` does, was not an N+1.
        self.assertTrue(
            self._check("""
        async def process(self, records):
            async for record in records:
                self.env['res.partner'].search([('id', '=', record.id)])
        """),
            "an async for iterates per item, like every other for",
        )

    def test_while_loop_not_flagged(self):
        violations = self._check("""
        def process(self):
            while True:
                results = self.env['res.partner'].search([], limit=100)
                if not results:
                    break
        """)
        self.assertFalse(violations, "while loops should not be flagged")

    def test_for_else_clause(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                pass
            else:
                self.env['res.partner'].search([])
        """)
        self.assertTrue(violations, "search in for/else should be flagged")

    def test_if_inside_loop(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                if record.active:
                    partners = self.env['res.partner'].search([('id', '=', record.id)])
        """)
        self.assertTrue(violations, "search inside if inside loop should be flagged")

    def test_non_query_method_ok(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                record.write({'active': True})
                record.unlink()
                name = record.name_get()
        """)
        self.assertFalse(violations, "non-query methods should not be flagged")

    def test_regex_search_not_flagged(self):
        violations = self._check("""
        import re
        PATTERN = re.compile(r'\\w+')
        def process(self, nodes):
            for node in nodes:
                if re.search(r'pattern', node.text):
                    pass
                if PATTERN.search(node.text):
                    pass
                if some_regex.search(node.text):
                    pass
        """)
        self.assertFalse(violations, "regex search should not be flagged")

    def test_a_compiled_regex_is_not_an_orm_query(self):
        self.assertFalse(
            self._check("""
        import re
        def process(self, nodes):
            for node in nodes:
                if re.compile(r'pattern').search(node.text):
                    pass
        """),
            "a compiled regex is not a recordset",
        )

    def test_a_recordset_returning_call_is_still_an_orm_receiver(self):
        for expression in (
            "IrAttachment.sudo().search([])",
            "request.env['sms.tracker'].sudo().search([])",
            "lead.with_context(active_test=False).search([])",
            "comodel.with_context(active_test=False).search([])",
            "model.sudo().search_count([])",
        ):
            with self.subTest(expression=expression):
                self.assertTrue(
                    self._check(
                        f"def process(self, records):\n"
                        f"    for record in records:\n"
                        f"        {expression}\n"
                    ),
                    "a recordset-returning method makes this an ORM query",
                )

    def test_orm_search_on_self_flagged(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                self.search([('id', '=', record.id)])
                self.env['res.partner'].search([('id', '=', record.id)])
                self.sudo().search([('id', '=', record.id)])
        """)
        self.assertEqual(
            len(violations), 3, "all three ORM search calls should be flagged"
        )

    def test_model_class_search_flagged(self):
        violations = self._check("""
        def process(self, records):
            for record in records:
                Partner.search([('id', '=', record.id)])
        """)
        self.assertTrue(violations, "CamelCase model search should be flagged")
