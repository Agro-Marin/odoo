import logging
import re
from typing import Any

from odoo.tools.misc import OrderedSet

_logger = logging.getLogger(__name__)


class TagsSelector:
    """Test selector based on tags.

    Spec grammar (comma-separated specs)::

        [-][tag][/file_path.py|/module][:Class][.method][[params]]

    Semantics worth spelling out:

    - an include with no tag implies ``standard``; ``*`` selects all tags;
    - exclusions beat inclusions; with only exclusions (or only parameter
      specs), ``standard`` is the implicit include base;
    - ``tag[params]`` / ``-tag[params]`` attach a (possibly negated)
      parameter to matching tests via ``test._test_params``.  A
      negated-parameter spec does **not** exclude the test itself — the
      ``-`` binds to the parameter, not to the tag.
    """

    filter_spec_re = re.compile(
        r"""
                                ^
                                ([+-]?)                     # operator_re
                                (\*|\w*)                    # tag_re
                                (\/[\w\/\.-]+\.py)?         # file_re
                                (?:\/(\w+))?                # module_re
                                (?::(\w*))?                 # test_class_re
                                (?:\.(\w*))?                # test_method_re
                                (?:\[(.*)\])?               # parameters
                                $""",
        re.VERBOSE,
    )  # [-][tag][/file_path.py|/module][:class][.method][[params]]

    def __init__(self, spec: str) -> None:
        """Parse the spec to determine tags to include and exclude."""
        parts = re.split(
            r",(?![^\[]*\])", spec
        )  # split on all comma not inside [] (not followed by ])
        filter_specs = [t.strip() for t in parts if t.strip()]
        self.exclude: set[tuple] = set()
        self.include: set[tuple] = set()
        self.parameters: OrderedSet = OrderedSet()

        for filter_spec in filter_specs:
            match = self.filter_spec_re.match(filter_spec)
            if not match:
                if filter_spec.endswith(".js"):
                    _logger.debug(
                        "Ignoring JavaScript file path as test tag: %s (only .py files are supported)",
                        filter_spec,
                    )
                else:
                    _logger.error("Invalid tag %s", filter_spec)
                continue

            sign, tag, file_path, module, klass, method, parameters = match.groups()
            is_include = sign != "-"
            is_exclude = not is_include

            if not tag and is_include:
                # including /module:class.method implicitly requires 'standard'
                tag = "standard"
            elif not tag or tag == "*":
                # '*' indicates all tests (instead of 'standard' tests only)
                tag = None
            test_filter = (tag, module, klass, method, file_path)

            if parameters:
                # we could check here that test supports negated parameters
                self.parameters.add(
                    (test_filter, ("-" if is_exclude else "+", parameters))
                )
                is_exclude = False

            if is_include:
                self.include.add(test_filter)
            if is_exclude:
                self.exclude.add(test_filter)

        if (self.exclude or self.parameters) and not self.include:
            self.include.add(("standard", None, None, None, None))

    def check(self, test: Any) -> bool:
        """Return whether ``test`` matches the specification.

        It must have at least one tag in ``self.include`` and none in
        ``self.exclude`` for each tag category.
        """
        if not hasattr(
            test, "test_tags"
        ):  # handle the case where the Test does not inherit from BaseCase and has no test_tags
            _logger.debug("Skipping test '%s' because no test_tag found.", test)
            return False

        test_module = test.test_module
        test_class = test.__class__.__name__
        test_tags = test.test_tags | {
            test_module
        }  # module as test_tags deprecated, keep for retrocompatibility,
        test_method = test._testMethodName
        test_module_path = test.__module__
        for prefix in ("odoo.addons", "odoo.upgrade"):
            test_module_path = test_module_path.removeprefix(prefix)
        test_module_path = test_module_path.replace(".", "/") + ".py"

        test._test_params = []

        def _is_matching(test_filter: tuple) -> bool:
            tag, module, klass, method, file_path = test_filter
            if tag and tag not in test_tags:
                return False
            if file_path:
                if not file_path.endswith(test_module_path):
                    return False
            elif module and module != test_module:
                return False
            if klass and klass != test_class:
                return False
            return not (method and test_method and method != test_method)

        if any(_is_matching(test_filter) for test_filter in self.exclude):
            return False

        if not any(_is_matching(test_filter) for test_filter in self.include):
            return False

        for test_filter, parameter in self.parameters:
            if _is_matching(test_filter):
                test._test_params.append(parameter)

        return True
