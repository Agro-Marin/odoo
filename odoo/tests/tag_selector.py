import logging
import re
from typing import Any

from odoo.tools.misc import OrderedSet

from .utils import addon_relative_path

_logger = logging.getLogger(__name__)


class TagsSelector:
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
    )

    def __init__(self, spec: str) -> None:
        parts = re.split(r",(?![^\[]*\])", spec)
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
                tag = "standard"
            elif not tag or tag == "*":
                tag = None
            test_filter = (tag, module, klass, method, file_path)

            if parameters:
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
        if not getattr(test, "test_tags", None):
            _logger.debug("Skipping test '%s' because no test_tag found.", test)
            return False

        test_module = test.test_module
        test_class = test.__class__.__name__
        test_tags = test.test_tags | {test_module}
        test_method = test._testMethodName
        test_module_path = addon_relative_path(test.__module__)

        # Reset for every test we are asked about, selected or not: a test the
        # selector rejects must not keep the params of a previous selector.
        test._test_params = []

        def _is_matching(test_filter: tuple) -> bool:
            tag, module, klass, method, file_path = test_filter
            if tag and tag not in test_tags:
                return False
            if file_path and not file_path.endswith(test_module_path):
                return False
            # Checked on its own, not as the "else" of file_path: the grammar
            # lets one spec carry both segments ("/web/tests/test_x.py/base"
            # parses as file_path + module), and hanging this off the elif meant
            # the module constraint was silently dropped whenever a file path
            # was also given.
            if module and module != test_module:
                return False
            if klass and klass != test_class:
                return False
            if method and test_method and method != test_method:
                return False
            return True

        if any(_is_matching(test_filter) for test_filter in self.exclude):
            return False

        if not any(_is_matching(test_filter) for test_filter in self.include):
            return False

        test._test_params = [
            parameter
            for test_filter, parameter in self.parameters
            if _is_matching(test_filter)
        ]

        return True
