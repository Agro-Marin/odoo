from pathlib import Path

import odoo
from odoo.libs.lint import scan_regex_patterns
from odoo.modules import get_resource_from_path

from . import lint_case

# https://www.odoo.com/documentation/<version>/... -- the version segment is
# what this gate reads.
DOC_URL_PAT = r"odoo\.com/documentation/[A-Za-z0-9._-]+"

EXTENSIONS = [".py", ".js", ".xml", ".rst", ".csv"]

# `latest` redirects to the branch this fork is cut from, so it is the only
# segment that stays right when we move. A pinned one sends the reader to the
# documentation of a version other than the code they are running.
CORRECT_SEGMENT = "/latest"

# Test fixtures assert on a URL, they do not offer one to anybody.
IGNORED_PATH_FRAGMENTS = ("/static/tests/",)


def _scan_roots() -> list[str]:
    return sorted(
        {
            str(Path(p).resolve())
            for p in [*lint_case.core_module_roots(), *odoo.__path__]
            if lint_case.is_core_path(str(Path(p).resolve()))
        }
    )


class TestDocumentationUrls(lint_case.LintCase):
    def test_documentation_links_are_not_version_pinned(self):
        roots = _scan_roots()
        self.assertTrue(roots, "the scan reached no roots at all")

        results = scan_regex_patterns(
            roots,
            EXTENSIONS,
            [DOC_URL_PAT],
            ["node_modules", "__pycache__"],
        )
        self.assertTrue(results, "the scan found no documentation URL at all")

        offenders = []
        for path, line, _pattern_index, matched_text in results:
            if matched_text.endswith(CORRECT_SEGMENT):
                continue
            if any(fragment in path for fragment in IGNORED_PATH_FRAGMENTS):
                continue
            try:
                module, relative_path = get_resource_from_path(path)
                name = f"{module}/{relative_path}"
            except TypeError:
                # a framework file: not in a module, name it from the repo root
                name = str(Path(path).relative_to(lint_case.core_root()))
            offenders.append(f"{name}:{line}: {matched_text}")

        self.assert_ratchet(
            offenders,
            "lint_documentation_url_version",
            "version-pinned documentation link(s)",
            "Use https://www.odoo.com/documentation/latest/...",
        )
