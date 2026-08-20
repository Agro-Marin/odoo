import ast
import logging
from pathlib import Path

from . import lint_case

_logger = logging.getLogger(__name__)

_MARKER_KEYS = frozenset({"is_follower", "ushare"})

_RECIPIENT_DATA_KEYS = frozenset(
    {
        "active",
        "email_normalized",
        "groups",
        "id",
        "is_follower",
        "lang",
        "name",
        "notif",
        "share",
        "type",
        "uid",
        "ushare",
    }
)


def _literal_string_keys(node: ast.Dict) -> frozenset[str] | None:
    keys = set()
    for key in node.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.add(key.value)
    return frozenset(keys)


class TestRecipientData(lint_case.LintCase):
    def test_recipient_data_shape(self):
        scanned, findings = 0, []
        for path in lint_case.iter_module_files("*.py"):
            if not lint_case.is_core_path(path):
                continue
            try:
                tree = ast.parse(Path(path).read_text(encoding="utf-8"))
            except SyntaxError, UnicodeDecodeError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                keys = _literal_string_keys(node)
                if keys is None or not keys >= _MARKER_KEYS:
                    continue
                scanned += 1
                if missing := _RECIPIENT_DATA_KEYS - keys:
                    findings.append(
                        f"{path}:{node.lineno}: recipients-data entry is missing "
                        f"{sorted(missing)}"
                    )

        _logger.info("%s recipients-data literal(s) checked", scanned)
        self.assertTrue(
            scanned,
            "the scan matched no recipients-data literal at all -- the marker "
            "keys have been renamed and this check is measuring nothing",
        )
        self.assert_ratchet(
            findings,
            0,
            "recipients-data literal(s) missing a key",
            "Fill every key of `mail.followers.RecipientData`. A consumer reads "
            "the whole payload off any entry in the list, so a missing key is a "
            "KeyError in whichever notification path reaches it first.",
        )
