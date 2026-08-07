from odoo.tests.common import BaseCase, TransactionCase, tagged
from odoo.tests.tag_selector import TagsSelector


@tagged("nodatabase")
class TestSetTags(TransactionCase):
    def test_set_tags_empty(self):
        @tagged()
        class FakeClass(TransactionCase):
            pass

        fc = FakeClass()

        self.assertEqual(fc.test_tags, {"at_install", "standard"})
        self.assertEqual(fc.test_module, "base")

    def test_set_tags_not_decorated(self):

        class FakeClass(TransactionCase):
            pass

        fc = FakeClass()

        self.assertEqual(fc.test_tags, {"at_install", "standard"})
        self.assertEqual(fc.test_module, "base")

    def test_set_tags_single_tag(self):
        @tagged("slow")
        class FakeClass(TransactionCase):
            pass

        fc = FakeClass()

        self.assertEqual(fc.test_tags, {"at_install", "standard", "slow"})
        self.assertEqual(fc.test_module, "base")

    def test_set_tags_multiple_tags(self):
        @tagged("slow", "nightly")
        class FakeClass(TransactionCase):
            pass

        fc = FakeClass()

        self.assertEqual(fc.test_tags, {"at_install", "standard", "slow", "nightly"})
        self.assertEqual(fc.test_module, "base")

    def test_inheritance(self):

        @tagged("slow")
        class FakeClassA(TransactionCase):
            pass

        class FakeClassC(FakeClassA):
            pass

        fc = FakeClassC()
        self.assertEqual(fc.test_tags, {"at_install", "standard", "slow"})

        @tagged("-standard")
        class FakeClassD(FakeClassA):
            pass

        fc = FakeClassD()
        self.assertEqual(fc.test_tags, {"at_install", "slow"})

    def test_untagging(self):

        @tagged("-standard")
        class FakeClassA(TransactionCase):
            pass

        fc = FakeClassA()
        self.assertEqual(fc.test_tags, {"at_install"})
        self.assertEqual(fc.test_module, "base")

        @tagged("-standard", "-base", "-at_install", "post_install")
        class FakeClassB(TransactionCase):
            pass

        fc = FakeClassB()
        self.assertEqual(fc.test_tags, {"post_install"})

        @tagged("-standard", "-base", "fast")
        class FakeClassC(TransactionCase):
            pass

        fc = FakeClassC()
        self.assertEqual(fc.test_tags, {"fast", "at_install"})

    def test_parental_advisory(self):

        @tagged("flow")
        class FakeClassA(TransactionCase):
            pass

        class FakeClassB(FakeClassA):
            test_tags = {"foo", "bar"}

        self.assertEqual(FakeClassA().test_tags, {"standard", "at_install", "flow"})
        self.assertEqual(FakeClassB().test_tags, {"foo", "bar"})


@tagged("nodatabase")
class TestSelector(TransactionCase):
    def test_selector_file_path_typo_rejected(self):
        with self.assertLogs("odoo.tests.tag_selector", level="ERROR") as capture:
            tags = TagsSelector("standard/odoo/addons/base/tests/test_tests_tags?py")
        self.assertEqual(set(), tags.include)
        self.assertEqual(set(), tags.exclude)
        self.assertIn("Invalid tag", capture.output[0])

        tags = TagsSelector("standard/odoo/addons/base/tests/test_tests_tags.py")
        self.assertEqual(
            {
                (
                    "standard",
                    None,
                    None,
                    None,
                    "/odoo/addons/base/tests/test_tests_tags.py",
                )
            },
            tags.include,
        )

    def test_selector_negated_parameter_registers_not_excludes(self):
        tags = TagsSelector("-standard[foo]")
        self.assertEqual(set(), tags.exclude)
        self.assertEqual({("standard", None, None, None, None)}, tags.include)
        self.assertEqual(
            [(("standard", None, None, None, None), ("-", "foo"))],
            list(tags.parameters),
        )

    def test_selector_parser(self):

        tags = TagsSelector("+slow")
        self.assertEqual(
            {
                ("slow", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("+slow,nightly")
        self.assertEqual(
            {
                ("slow", None, None, None, None),
                ("nightly", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("+slow,-standard")
        self.assertEqual(
            {
                ("slow", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(
            {
                ("standard", None, None, None, None),
            },
            tags.exclude,
        )

        tags = TagsSelector("+slow, -standard")
        self.assertEqual(
            {
                ("slow", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(
            {
                ("standard", None, None, None, None),
            },
            tags.exclude,
        )

        tags = TagsSelector("+slow , -standard")
        self.assertEqual(
            {
                ("slow", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(
            {
                ("standard", None, None, None, None),
            },
            tags.exclude,
        )

        tags = TagsSelector("+slow ,-standard,+js")
        self.assertEqual(
            {("slow", None, None, None, None), ("js", None, None, None, None)},
            tags.include,
        )
        self.assertEqual(
            {
                ("standard", None, None, None, None),
            },
            tags.exclude,
        )

        tags = TagsSelector("slow, ")
        self.assertEqual(
            {
                ("slow", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("+slow,-standard, slow,-standard ")
        self.assertEqual(
            {
                ("slow", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(
            {
                ("standard", None, None, None, None),
            },
            tags.exclude,
        )

        tags = TagsSelector("")
        self.assertEqual(set(), tags.include)
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("/module")
        self.assertEqual(
            {
                ("standard", "module", None, None, None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("/module/tests/test_file.py")
        self.assertEqual(
            {
                ("standard", None, None, None, "/module/tests/test_file.py"),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("*/module")
        self.assertEqual(
            {
                (None, "module", None, None, None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector(":class")
        self.assertEqual(
            {
                ("standard", None, "class", None, None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector(".method")
        self.assertEqual(
            {
                ("standard", None, None, "method", None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector(":class.method")
        self.assertEqual(
            {
                ("standard", None, "class", "method", None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("/module:class.method")
        self.assertEqual(
            {
                ("standard", "module", "class", "method", None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("*/module:class.method")
        self.assertEqual(
            {
                (None, "module", "class", "method", None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("-/module:class.method")
        self.assertEqual(
            {
                ("standard", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(
            {
                (None, "module", "class", "method", None),
            },
            tags.exclude,
        )

        tags = TagsSelector("-*/module:class.method")
        self.assertEqual(
            {
                ("standard", None, None, None, None),
            },
            tags.include,
        )
        self.assertEqual(
            {
                (None, "module", "class", "method", None),
            },
            tags.exclude,
        )

        tags = TagsSelector("tag/module")
        self.assertEqual(
            {
                ("tag", "module", None, None, None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("tag.method")
        self.assertEqual(
            {
                ("tag", None, None, "method", None),
            },
            tags.include,
        )
        self.assertEqual(set(), tags.exclude)

        tags = TagsSelector("*/module,-standard")
        self.assertEqual(
            {
                (None, "module", None, None, None),
            },
            tags.include,
        )
        self.assertEqual(
            {
                ("standard", None, None, None, None),
            },
            tags.exclude,
        )

        tags = TagsSelector("*/some-paths/with-dash/addons/account/test/test_file.py")
        self.assertEqual(
            {
                (
                    None,
                    None,
                    None,
                    None,
                    "/some-paths/with-dash/addons/account/test/test_file.py",
                ),
            },
            tags.include,
        )
        tags = TagsSelector("/some/absolute/path/v.3/module.py")
        self.assertEqual(
            {
                (
                    "standard",
                    None,
                    None,
                    None,
                    "/some/absolute/path/v.3/module.py",
                ),
            },
            tags.include,
        )

        tags = TagsSelector("/some/absolute/path/v.3/module.py")
        self.assertEqual(
            {
                (
                    "standard",
                    None,
                    None,
                    None,
                    "/some/absolute/path/v.3/module.py",
                ),
            },
            tags.include,
        )

        tags = TagsSelector("/module.method")
        self.assertEqual(
            {
                ("standard", "module", None, "method", None),
            },
            tags.include,
        )


@tagged("nodatabase")
class TestSelectorSelection(TransactionCase):
    def test_selector_selection(self):

        class Test_A(TransactionCase):
            pass

        @tagged("stock")
        class Test_B(BaseCase):
            pass

        @tagged("stock", "slow")
        class Test_C(BaseCase):
            pass

        @tagged("standard", "slow")
        class Test_D(BaseCase):
            pass

        @tagged("-at_install", "post_install")
        class Test_E(TransactionCase):
            pass

        no_tags_obj = Test_A()
        stock_tag_obj = Test_B()
        multiple_tags_obj = Test_C()
        multiple_tags_standard_obj = Test_D()
        post_install_obj = Test_E()

        tags = TagsSelector("")
        self.assertFalse(tags.check(no_tags_obj))

        tags = TagsSelector("+slow")
        self.assertFalse(tags.check(no_tags_obj))

        tags = TagsSelector("+slow,fake")
        self.assertFalse(tags.check(no_tags_obj))

        tags = TagsSelector("slow,standard")
        self.assertTrue(no_tags_obj)

        tags = TagsSelector("slow,-standard")
        self.assertFalse(tags.check(no_tags_obj))

        tags = TagsSelector("-slow,-standard")
        self.assertFalse(tags.check(no_tags_obj))

        tags = TagsSelector("-slow,+standard")
        self.assertTrue(tags.check(no_tags_obj))

        tags = TagsSelector("")
        self.assertFalse(tags.check(stock_tag_obj))

        tags = TagsSelector("slow")
        self.assertFalse(tags.check(stock_tag_obj))

        tags = TagsSelector("standard")
        self.assertTrue(tags.check(stock_tag_obj))

        tags = TagsSelector("slow,standard")
        self.assertTrue(tags.check(stock_tag_obj))

        tags = TagsSelector("slow,-standard")
        self.assertFalse(tags.check(stock_tag_obj))

        tags = TagsSelector("+stock")
        self.assertTrue(tags.check(stock_tag_obj))

        tags = TagsSelector("stock,fake")
        self.assertTrue(tags.check(stock_tag_obj))

        tags = TagsSelector("stock,standard")
        self.assertTrue(tags.check(stock_tag_obj))

        tags = TagsSelector("-stock")
        self.assertFalse(tags.check(stock_tag_obj))

        tags = TagsSelector("")
        self.assertFalse(tags.check(multiple_tags_obj))

        tags = TagsSelector("-stock")
        self.assertFalse(tags.check(multiple_tags_obj))

        tags = TagsSelector("-slow")
        self.assertFalse(tags.check(multiple_tags_obj))

        tags = TagsSelector("slow")
        self.assertTrue(tags.check(multiple_tags_obj))

        tags = TagsSelector("slow,stock")
        self.assertTrue(tags.check(multiple_tags_obj))

        tags = TagsSelector("-slow,stock")
        self.assertFalse(tags.check(multiple_tags_obj))

        tags = TagsSelector("slow,stock,-slow")
        self.assertFalse(tags.check(multiple_tags_obj))

        tags = TagsSelector("")
        self.assertFalse(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("standard")
        self.assertTrue(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("slow")
        self.assertTrue(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("slow,fake")
        self.assertTrue(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("-slow")
        self.assertFalse(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("-standard")
        self.assertFalse(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("-slow,-standard")
        self.assertFalse(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("standard,-slow")
        self.assertFalse(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("slow,-standard")
        self.assertFalse(tags.check(multiple_tags_standard_obj))

        tags = TagsSelector("standard")
        position = TagsSelector("post_install")
        self.assertTrue(
            tags.check(post_install_obj) and position.check(post_install_obj)
        )

        tags = TagsSelector("/base")
        self.assertTrue(tags.check(no_tags_obj), "Test should match is module path")
        tags = TagsSelector("/base/tests/test_tests_tags.py")
        self.assertTrue(
            tags.check(no_tags_obj),
            "Test should match is module path with file",
        )

        tags = TagsSelector("/account/tests/test_tests_tags.py")
        self.assertFalse(
            tags.check(no_tags_obj),
            "Test should not match another module path with file",
        )

        tags = TagsSelector(__file__)
        self.assertTrue(
            tags.check(no_tags_obj), "Test should match its absolute file path"
        )
        tags = TagsSelector(__file__)
        self.assertTrue(tags.check(no_tags_obj), "Test should its absolute file path")

    def test_selector_parser_parameters(self):
        tags = "/base:FakeClassA[failfast=0,filter=-livechat],/other[notForThisClass],-/base:FakeClassA[arg1,arg2]"
        tags = TagsSelector(tags)

        class FakeClassA(TransactionCase):
            pass

        fc = FakeClassA()
        tags.check(fc)
        self.assertEqual(
            fc._test_params,
            [("+", "failfast=0,filter=-livechat"), ("-", "arg1,arg2")],
        )

    def test_negative_parameters_translate(self):
        tags = TagsSelector(".test_negative_parameters_translate")
        self.assertTrue(tags.check(self), "Sanity check")
        self.assertEqual(self._test_params, [])

        tags = TagsSelector(
            "/other_module,-.test_negative_parameters_translate[someparam]"
        )
        self.assertFalse(
            tags.check(self),
            "we don't expect a negative parameter to enable the test if not enabled in other tags",
        )
        self.assertEqual(self._test_params, [])

        tags = TagsSelector("/base,-.test_negative_parameters_translate[someparam]")
        self.assertTrue(
            tags.check(self),
            "A negative parametric tag should not disable the test",
        )
        self.assertEqual(self._test_params, [("-", "someparam")])

        tags = TagsSelector("-.test_negative_parameters_translate[someparam]")
        self.assertTrue(
            tags.check(self),
            "we don't expect a single negative parameter to disable the test that should run by edfault",
        )
        self.assertEqual(self._test_params, [("-", "someparam")])

        tags = TagsSelector("/base,-.test_negative_parameters_translate")
        self.assertFalse(
            tags.check(self),
            "Sanity check, a negative parametric tag without params still disable the test",
        )
        self.assertEqual(self._test_params, [])

        tags = TagsSelector(".test_negative_parameters_translate[-someparam]")
        self.assertTrue(tags.check(self), "A parametric tag should enable test")
        self.assertEqual(self._test_params, [("+", "-someparam")])


class TestTestClass(BaseCase):
    def test_canonical_tag(self):
        self.assertEqual(
            self.canonical_tag,
            "/base/tests/test_tests_tags.py:TestTestClass.test_canonical_tag",
        )

    def get_log_metadata(self):
        self.assertEqual(
            self.log_metadata["canonical_tag"],
            "/base/tests/test_tests_tags.py:TestTestClass.test_canonical_tag",
        )
