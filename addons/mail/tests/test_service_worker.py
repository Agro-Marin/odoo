import re
from collections import defaultdict

from odoo.tests import HttpCase, tagged
from odoo.tools import file_open

_STRIPPABLE_EXPORT = re.compile(
    r"^export\s+(?:async\s+)?(?:const|let|var|function|class)\s"
)

_TOP_LEVEL_BINDING = re.compile(
    r"^(?:(const|let|class)|(?:var|function))\s+([A-Za-z_$][\w$]*)", re.MULTILINE
)


@tagged("-at_install", "post_install")
class TestServiceWorkerComposition(HttpCase):
    def _fetch_worker(self):
        response = self.url_open("/web/service-worker.js")
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_the_mail_half_is_appended_for_an_internal_user(self):
        self.authenticate("admin", "admin")
        self.assertIn(
            "/mail/static/lib/idb-keyval/idb-keyval.js",
            self._fetch_worker(),
            "the internal-user worker must carry mail's half",
        )

    def test_the_appended_utils_only_export_declarations(self):
        source = file_open("mail/static/src/service_worker_utils.js").read()
        offenders = [
            line.strip()
            for line in source.splitlines()
            if line.startswith("export") and not _STRIPPABLE_EXPORT.match(line)
        ]
        self.assertFalse(
            offenders,
            f"{offenders} cannot be stripped into the service-worker scope. Bind the "
            f"value with `export const`/`function`/`class` and let the worker read it "
            f"as a global, the way the rest of this file is consumed.",
        )

    def test_the_composed_worker_declares_no_name_twice(self):
        self.authenticate("admin", "admin")
        kinds_by_name = defaultdict(list)
        for lexical_kind, name in _TOP_LEVEL_BINDING.findall(self._fetch_worker()):
            kinds_by_name[name].append(lexical_kind or "var/function")
        duplicated = {
            name: kinds for name, kinds in kinds_by_name.items() if len(kinds) > 1
        }
        fatal = sorted(
            name
            for name, kinds in duplicated.items()
            if any(kind != "var/function" for kind in kinds)
        )
        self.assertFalse(
            fatal,
            f"{fatal} are declared twice at the top level of the composed service "
            f"worker, at least once lexically — that is a SyntaxError, and it costs "
            f"the whole worker, not just the appended half. One script, one scope: "
            f"treat what web's half binds as a global (see the /* global */ line in "
            f"mail/static/src/service_worker.js) instead of rebinding it.",
        )
        self.assertFalse(
            sorted(set(duplicated) - set(fatal)),
            f"{sorted(set(duplicated) - set(fatal))} are declared twice at the top "
            f"level of the composed service worker. This one still parses — duplicate "
            f"`var`/`function` is legal — but one half silently overrides the other, "
            f"which is not something either file can see on its own.",
        )
