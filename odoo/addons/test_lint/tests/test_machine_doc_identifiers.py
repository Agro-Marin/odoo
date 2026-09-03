import re
from pathlib import Path

from odoo import tools
from odoo.libs.lint import scan_regex_patterns
from odoo.tests import tagged

from .lint_case import LintCase, _module_roots

PRIVATE_CALL = re.compile(r"`(_[a-z][a-z0-9_]*)\(\)`")

DEF_PATTERN = r"\bdef [A-Za-z_]\w*"

KNOWN_STALE = frozenset(
    {
        "_build_category_snapshot",
        "_get_approval_protected_fields",
        "_get_approval_required_fields",
        "_get_approver_sync_trigger_fields",
        "_get_group_by_fields",
        "_get_locked_fields",
        "_get_request_trigger_fields",
        "_get_select_fields",
        "_avatar_generate_svg",
        "_backend_for_key",
        "_filestore",
        "_notify_trigger_channel",
        "_notifydb",
        "_storage",
        "_storage_backend",
        "_compute_enrollment_count",
        "_compute_step_count",
        "_get_badge_user_stats",
        "_get_owners_info",
        "_get_user_badge_level",
        "_recompute_rank_bulk",
        "_validate_coordinate_fields_exist",
        "_validate_coordinate_mode",
        "_validate_info_box_template",
        "_validate_layer_configurations",
        "_validate_trail_configuration",
        "_validate_webgl_trail_configuration",
        "_validate_levels_sum",
        "_t",
    }
)


@tagged("post_install", "-at_install")
class MachineDocIdentifierLinter(LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.references = []
        roots = [Path(r) for r in _module_roots()]
        framework_root = Path(tools.config.root_path)
        hits = scan_regex_patterns(
            [str(framework_root)], [".py"], [DEF_PATTERN], ["addons", "__pycache__"]
        ) + scan_regex_patterns(
            [str(root) for root in roots], [".py"], [DEF_PATTERN], ["__pycache__"]
        )
        cls.defined = {matched.removeprefix("def ") for _, _, _, matched in hits}

        for root in roots:
            for doc_dir in root.glob("machine_doc_v*"):
                for path in doc_dir.rglob("*.md"):
                    try:
                        text = path.read_text(encoding="utf-8")
                    except OSError, UnicodeDecodeError:
                        continue
                    for number, line in enumerate(text.splitlines(), 1):
                        for match in PRIVATE_CALL.finditer(line):
                            cls.references.append((path, number, match.group(1)))

    def test_documented_methods_exist(self):
        self.assertTrue(
            self.references,
            "the scan found no backticked private calls in any machine_doc",
        )
        offenders = [
            f"{path}:{number} `{name}()`"
            for path, number, name in self.references
            if name not in self.defined and name not in KNOWN_STALE
        ]
        self.assert_ratchet(
            sorted(offenders),
            "lint_machine_doc_identifier",
            "machine_doc reference(s) to a method that no module defines",
            "Rename the prose with the method, or drop the claim. A reader is told "
            "to read these documents first, so a name resolving to nothing is a "
            "premise they cannot check.",
        )

    def test_known_stale_entries_are_still_stale(self):
        paid = sorted(KNOWN_STALE & self.defined)
        self.assertFalse(
            paid,
            f"{len(paid)} name(s) in KNOWN_STALE resolve again: "
            + ", ".join(paid)
            + ". Delete them from the set so the gate enforces them.",
        )
