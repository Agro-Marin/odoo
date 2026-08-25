import logging
import re

from odoo import tools

from . import lint_case

_logger = logging.getLogger(__name__)


class TestI18n(lint_case.LintCase):
    PROPS_RE = re.compile(
        r"""
        (
            <[A-Z]                          # Match the opening tag of a component node. We assume that tags starting with an uppercase letter refer to a component
                (
                    [^>]+                   # Match anything that is not a closing tag `>`. In other words, the rest of the component name and any prop that doesn't match the heuristics that follow
                )
        )
        \s
        (?!t-)                              # exclude directives (attributes starting with t-)
        (
            [a-zA-Z-]+                      # Match prop name
            =
            "'                              # Make sure that the value is a static string literal. Only static string literals are eligible for translation. We determine that the value is a string literal if the value begins and ends with a '
            [A-Z](\'|[^'"])*?                # Assumption: Text starting with an uppercase letter is probably supposed to be translated.
            [a-z]                           # Arbitrary constraint to avoid matching certain technical constants (e.g. ROW, COL)
            (\'|[^'"])*?                     # Match the content of the string
            '"                              # Value ends with the closing of a string literal
        )
        """,
        re.VERBOSE | re.DOTALL,
    )

    def test_directives_regex(self):
        test_cases = [
            (
                """
            <Component
                t-esc="some_variable"
                customProp="'Custom String'"
            />""",
                [
                    ("customProp=\"'Custom String'\""),
                ],
            ),
            (
                """
            <Component t-title="'Some String'" t-esc="some_variable"/>
            """,
                [],
            ),
            (
                """
            <Component title.translate="'Some String'" t-esc="some_variable"/>
            """,
                [],
            ),
            (
                """
            <Component title="'Another String'" t-esc="another_variable"/>
            <Component description="'Description here'" />
            <Component title="'String with an escaped single quote ' inside'"/>
            """,
                [
                    ("title=\"'Another String'\""),
                    ("description=\"'Description here'\""),
                    ("title=\"'String with an escaped single quote ' inside'\""),
                ],
            ),
            (
                """
            <Component title="'Valid Title'" t-esc="some_variable" t-title="'Should not be caught'" customProp="'Valid Prop'"/>
            """,
                [
                    ("customProp=\"'Valid Prop'\""),
                ],
            ),
            (
                """
            <Component name="'singleword'" title="'SingleWord'" prop="'another String'"/>
            """,
                [
                    ("title=\"'SingleWord'\""),
                ],
            ),
        ]

        for index, (file_content, expected_matches) in enumerate(test_cases, start=1):
            with self.subTest(case=index, source=file_content.strip()):
                matches = [m.group(3) for m in self.PROPS_RE.finditer(file_content)]
                self.assertEqual(matches, expected_matches)

    def test_user_content_as_prop_is_translatable(self):
        offenders = []
        checked = 0
        for file_path in self.iter_module_files("**/static/**/*.xml"):
            if not lint_case.is_core_path(file_path):
                continue
            checked += 1
            with tools.file_open(file_path, "r") as f:
                file_content = f.read()
            for m in self.PROPS_RE.finditer(file_content):
                lineno = file_content[: m.start()].count("\n") + 1
                offenders.append(f"{file_path}:{lineno}: {m.group(3)}")

        _logger.info("checked %s component template(s)", checked)
        self.assertTrue(checked, "the scan reached no component templates at all")
        self.assert_ratchet(
            offenders,
            "lint_untranslatable_prop",
            "component prop(s) carrying untranslatable human-readable text",
            "Add the `.translate` suffix. If this is a false positive, please "
            "contact the i18n team.",
        )
