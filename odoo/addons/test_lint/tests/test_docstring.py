import contextlib
import inspect
import io
import logging

import docutils.core
import docutils.nodes  # noqa: F401  registers node classes with docutils
import docutils.parsers.rst.directives  # noqa: F401  registers rst directives
import docutils.parsers.rst.directives.admonitions  # noqa: F401  registers admonitions
import docutils.parsers.rst.roles  # noqa: F401  registers rst roles

from odoo.tests.common import tagged

from .lint_case import LintCase, iter_registry_methods

logger = logging.getLogger(__name__)

MODULES_TO_LINT = ("base",)
MODULES_TO_LINT_ONLY_PUBLIC_METHODS = ("helpdesk",)

POSITIONAL_ONLY = inspect.Parameter.POSITIONAL_ONLY
POSITIONAL_OR_KEYWORD = inspect.Parameter.POSITIONAL_OR_KEYWORD
VAR_POSITIONAL = inspect.Parameter.VAR_POSITIONAL
KEYWORD_ONLY = inspect.Parameter.KEYWORD_ONLY
VAR_KEYWORD = inspect.Parameter.VAR_KEYWORD

DOCUTILS_WARNING = 2
DOCUTILS_CRITICAL = 5

RST_INFO_FIELDS_DOC = (
    "https://www.sphinx-doc.org/en/master/usage/domains/python.html#info-field-lists"
)

RST_INFO_FIELDS = {
    "param": "param",
    "parameter": "param",
    "arg": "param",
    "argument": "param",
    "key": "param",
    "keyword": "param",
    "type": "type",
    "raises": "raises",
    "raise": "raises",
    "except": "raises",
    "exception": "raises",
    "var": "var",
    "ivar": "var",
    "cvar": "var",
    "vartype": "vartype",
    "returns": "returns",
    "return": "returns",
    "rtype": "rtype",
    "meta": "meta",
}


ABUSE_KWARGS = """\
{where}:
Function signature:
  {function}
Docstring:
  {docstring}
Absent from function: {func_missing}
Absent from docstring: {doc_missing}
"""

PARSE_ERROR = '''Unable to parse the docstring as reStructuredText.
"""
{doc}
"""
{error}
Learn rst:

* https://docutils.sourceforge.io/docs/user/rst/quickref.html
* https://www.sphinx-doc.org/en/master/usage/restructuredtext/index.html
* https://www.sphinx-doc.org/en/master/usage/domains/python.html

Online editor:

* https://rsted.info.ucl.ac.be/'''


def extract_docstring_params(doctree):
    params = {}
    types = {}
    rtype = inspect._empty

    field_lists = [
        node for node in doctree if node.tagname in ("docinfo", "field_list")
    ]
    for field_list in field_lists:
        for field in field_list:
            field_name, field_body = field.children
            kind, _, name = str(field_name[0]).partition(" ")
            if kind not in RST_INFO_FIELDS:
                e = f"unknown rst: {kind!r}\n{RST_INFO_FIELDS_DOC}"
                raise ValueError(e)
            kind = RST_INFO_FIELDS[kind]

            if kind == "param":
                if not name:
                    e = "empty :param:"
                    raise ValueError(e)
                type_param, _, name = name.rpartition(" ")
                params[name] = None
                if type_param:
                    type_type = types.setdefault(name, type_param)
                    if type_type != type_param:
                        e = f"conflicting type: {type_param} (:param:) vs {type_type} (:type:)"
                        raise ValueError(e)

            elif kind == "returns":
                if name:
                    e = f'invalid ":{kind} {name}:", did you mean ":rtype: {name}"?'
                    raise ValueError(e)

            elif kind == "type":
                if not name:
                    e = "empty :type:"
                    raise ValueError(e)
                params[name] = None
                try:
                    type_type = field_body.children[0].astext().strip()
                except IndexError as exc:
                    if name:
                        e = f'invalid ":{kind} {name}:", did you mean ":{kind}: {name}"?'
                        raise ValueError(e) from exc
                    raise
                type_param = types.setdefault(name, type_type)
                if type_param != type_type:
                    e = f"conflicting type: {type_param} (:param:) vs {type_type} (:type:)"
                    raise ValueError(e)

            elif kind == "rtype":
                try:
                    rtype = field_body.children[0].astext().strip()
                except IndexError as exc:
                    if name:
                        e = f'invalid ":{kind} {name}:", did you mean ":{kind}: {name}"?'
                        raise ValueError(e) from exc
                    raise

    return list(params), types, rtype


# This gate reads the *installed* registry, so its count is a function of the
# install and not of the tree: 1 on `base` + `test_lint` (the scope CI runs),
# 32 with the enterprise suite loaded. The floor is therefore the ceiling of
# the canonical scope and the ratchet is one-sided -- a bigger install
# reporting more is not a regression, and a smaller one reporting less is not
# a fix. Make it exact again the day this gate reads files instead.
DOCSTRING_FLOOR = 32


@tagged("-at_install", "post_install")
class TestDocstring(LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        doctree = docutils.core.publish_doctree(
            "",
            settings_overrides={
                "report_level": DOCUTILS_CRITICAL,
                "halt_level": DOCUTILS_CRITICAL,
            },
        )
        cls.doctree_settings_silent = doctree.settings

        doctree = docutils.core.publish_doctree(
            "",
            settings_overrides={
                "report_level": DOCUTILS_WARNING,
                "halt_level": DOCUTILS_CRITICAL,
            },
        )
        cls.doctree_settings_verbose = doctree.settings

    def test_docstring(self):
        offenders = []
        seen = set()
        checked = 0

        for entry in iter_registry_methods():
            model_name, model_cls, method_name, method, parent_class = entry
            key = (parent_class, method_name)
            if key in seen or not method.__doc__:
                continue
            seen.add(key)
            checked += 1

            if (getattr(parent_class, "_name", None) or "").startswith("mail."):
                settings = self.doctree_settings_silent
            elif (model_cls._original_module or model_name).startswith(
                MODULES_TO_LINT
            ) or (
                (model_cls._original_module or model_name).startswith(
                    MODULES_TO_LINT_ONLY_PUBLIC_METHODS
                )
                and not method_name.startswith("_")
            ):
                settings = self.doctree_settings_verbose
            else:
                settings = self.doctree_settings_silent

            where = (
                f"{getattr(parent_class, '_module', parent_class.__module__)}"
                f":{getattr(parent_class, '_name', None)}.{method_name}"
            )
            try:
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    doctree = docutils.core.publish_doctree(
                        inspect.cleandoc(method.__doc__),
                        settings=settings,
                    )
                    if stderr.tell():
                        raise AssertionError(
                            PARSE_ERROR.format(
                                doc=inspect.cleandoc(method.__doc__).strip(),
                                error=stderr.getvalue(),
                            )
                        )
                self._test_docstring_params(method, doctree, where)
            # A malformed docstring is the finding, not a crash. `extract_docstring_params`
            # raises ValueError for exactly the shapes this gate exists to report
            # -- `:returns set:` for `:rtype: set`, an empty `:param:`, an unknown
            # info-field -- and only AssertionError was caught, so one of them
            # ended the whole run with an error instead of contributing one
            # offender. Four methods in `account_reports` did precisely that, and
            # only once enough modules were installed for the registry to hold
            # them: the gate passed thinly and errored fat. IndexError joins it
            # for `sign_params[-1]` on a signature with no parameters.
            except (AssertionError, ValueError, IndexError) as exc:
                offenders.append(f"{where}: {str(exc).splitlines()[0][:160]}")

        logger.info("checked %s documented method definitions", checked)
        # Scales with the installed module set -- 151 on `base` + `test_lint`,
        # 3 347 with the enterprise suite installed. The anchor guards against a
        # registry that loaded nothing, so it has to hold at the *smallest*
        # scope this suite runs at, which is the one CI uses.
        self.assertGreater(checked, 100, "the scan reached almost no docstrings")
        self.assert_ratchet(
            offenders,
            DOCSTRING_FLOOR,
            "docstring(s) disagreeing with the signature they document",
            "Correct the docstring (or the annotation), then lower the floor.",
            exact=False,
        )

    def _test_docstring_params(self, method, doctree, where=""):
        doc_params, doc_types, doc_rtype = extract_docstring_params(doctree)

        signature = inspect.signature(
            method,
            annotation_format=inspect.Format.STRING,
        )
        sign_params = list(signature.parameters.values())
        sign_types = {param.name: param.annotation for param in sign_params}
        sign_rtype = signature.return_annotation

        if signature.empty not in (sign_rtype, doc_rtype):
            self.assertEqual(self._stringify_annotation(sign_rtype), doc_rtype)

        try:
            m = "the docstring is documenting non-existing parameters"
            self.assertGreaterEqual(set(sign_types), set(doc_params), m)
        except AssertionError:
            if sign_params[-1].kind != VAR_KEYWORD:
                raise
            logger.info(
                ABUSE_KWARGS.format(
                    where=where,
                    function=signature,
                    docstring=", ".join(tuple(doc_params)),
                    func_missing=set(doc_params) - set(sign_types),
                    doc_missing=(
                        set(sign_types)
                        - set(doc_params)
                        - {
                            sign_params[0].name,
                            sign_params[-1].name,
                        }
                    )
                    or {},
                )
            )

        for param, doc_type in doc_types.items():
            sign_type = sign_types.get(param, signature.empty)
            if sign_type != signature.empty:
                self.assertEqual(self._stringify_annotation(sign_type), doc_type)

    def _stringify_annotation(self, sign_type):
        if isinstance(sign_type, type):
            sign_type = sign_type.__name__
        return str(sign_type).removeprefix("typing.")

    def test_a_malformed_docstring_is_a_finding_not_a_crash(self):
        # `extract_docstring_params` raises ValueError for exactly the shapes
        # this gate reports. Four methods in `account_reports` write
        # `:returns set:` where they mean `:rtype: set`, and each one used to
        # end the whole run with an error -- so the gate scored zero offenders
        # on a thin install and did not run at all on a fat one.
        for docstring, expected in (
            (":returns set: the ids\n", 'invalid ":returns set:"'),
            (":param:\n", "empty :param:"),
            (":nosuchfield: x\n", "unknown rst"),
        ):
            with self.subTest(docstring=docstring):
                doctree = docutils.core.publish_doctree(
                    docstring, settings=self.doctree_settings_silent
                )
                with self.assertRaises(ValueError) as caught:
                    extract_docstring_params(doctree)
                self.assertIn(expected, str(caught.exception))

    def test_the_gate_records_such_a_docstring_as_one_offender(self):
        class _Fake:
            def method(self):
                """:returns set: the ids"""

        offenders = []
        try:
            doctree = docutils.core.publish_doctree(
                inspect.cleandoc(_Fake.method.__doc__),
                settings=self.doctree_settings_silent,
            )
            self._test_docstring_params(_Fake.method, doctree, "fake:method")
        except (AssertionError, ValueError, IndexError) as exc:
            offenders.append(f"fake:method: {str(exc).splitlines()[0][:160]}")
        self.assertEqual(len(offenders), 1, "it has to be counted, not raised")
