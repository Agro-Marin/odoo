"""A patch aimed at a re-export façade reaches the call site only by accident.

Several packages in core exist to be imported FROM rather than to hold code:
``odoo/api``, ``odoo/fields``, ``odoo/models`` (``coding_guidelines.rst`` §2.1
requires addons to go through them), and ``odoo/service/server``, which
re-exports the four server classes and the lifecycle verbs. Their ``__init__``
binds names defined elsewhere.

``patch("<façade>.<name>")`` rebinds the attribute ON THE FAÇADE. Whether the
code under test then sees the patch depends entirely on how IT reached the name:

* ``from odoo.api import Environment`` at module scope binds the object once, at
  import. Patching the façade afterwards changes nothing, and the test drives the
  real collaborator while reporting green.
* ``odoo.api.Environment(...)``, or a function-local ``from .server import
  ThreadedServer``, re-reads the attribute per call. Patching the façade is
  exactly right.

The difference is invisible at the patch site, and the failure mode is silent —
``tests/service/test_db_patch_targets`` exists because the same thing shipped in
``odoo.service.db``: seven tests began driving the real function against a real
cluster when that module became a package, and were only noticed because one of
them happened to need config the mock did not have. ADR-0014 records it.

So every façade-aimed patch has to be a recorded decision, with the mechanism
that justifies it. That is what ``FACADE_TARGETS_OK`` below is. A new one is not
forbidden — it just has to be looked at once and written down, and the entry is
what a later refactor breaks loudly instead of silently.
"""

import re

from .conftest import patch_target_sources

#: Packages whose ``__init__`` is a re-export surface rather than an implementation.
FACADES = (
    "odoo.service.db",
    "odoo.service.server",
    "odoo.api",
    "odoo.fields",
    "odoo.models",
)

_TARGET = re.compile(
    r"""patch\(\s*["'](?P<facade>"""
    + "|".join(re.escape(f) for f in FACADES)
    + r""")\.(?P<name>[A-Za-z_]\w*)["']"""
)

#: ``{façade: {name: why patching the façade really reaches the call site}}``.
#: Every entry below was checked against the consumer, not assumed.
FACADE_TARGETS_OK = {
    # `odoo.service.db` has its own, stricter gate (test_db_patch_targets), which
    # additionally requires a submodule-qualified target. These are the names it
    # lists as package-level-correct; repeating them here keeps this gate from
    # contradicting it.
    "odoo.service.db": {
        "check_super": "web/controllers/database.py does `db.check_super(...)`",
        "restore_db": "read off the package by the controller, per call",
        "list_dbs": "http/helpers.py does `odoo.service.db.list_dbs`",
        "dispatch": "read off the package by the RPC entry point",
        "dump_db": "read off the package by the controller, per call",
    },
    "odoo.service.server": {
        # lifecycle.start() imports INSIDE the function:
        #     from .server import EventServer, PreforkServer, ThreadedServer
        # so the attribute is re-read on every call. Hoisting that import to
        # module scope would silently disable the patch — and this entry.
        "ThreadedServer": "lifecycle.start() imports it at call time",
        # EventServer and PreforkServer come through the same call-time import
        # and would be equally correct — but nothing patches them today, and
        # test_the_recorded_reasons_are_not_stale rejects an entry with no
        # corresponding patch. Add one when a patch needs it, not before.
    },
    "odoo.api": {
        # service/common.py does `odoo.api.Environment(cr, None, {})` and
        # service/model.py does `api.Environment(...)`: an attribute read per
        # call, never a module-scope `from odoo.api import Environment`.
        "Environment": "service/common.py and service/model.py read it per call",
    },
    "odoo.fields": {},
    "odoo.models": {},
}


def _targets():
    for path, text in patch_target_sources():
        for m in _TARGET.finditer(text):
            line = text[: m.start()].count("\n") + 1
            yield path, line, m.group("facade"), m.group("name")


def test_every_facade_patch_is_a_recorded_decision():
    bad = []
    for path, line, facade, name in _targets():
        if name not in FACADE_TARGETS_OK[facade]:
            bad.append(f"{path}:{line} -> {facade}.{name}")
    assert not bad, (
        "patch target(s) aimed at a re-export façade with no recorded reason.\n"
        "  " + "\n  ".join(bad) + "\n\n"
        "The façade only re-exports the name, so whether the patch reaches the "
        "code under test depends on how that code imported it:\n"
        "  * bound at module scope (`from odoo.api import X`) -> the patch is a "
        "SILENT NO-OP and the test drives the real collaborator;\n"
        "  * read per call (`odoo.api.X(...)`, or a function-local import) -> "
        "the patch is correct.\n"
        "Check which, then either patch the module that DEFINES the name, or add "
        "it to FACADE_TARGETS_OK with the caller that justifies it."
    )


def test_the_recorded_reasons_are_not_stale():
    """An allowlist nobody prunes is a second place for dead knowledge to live.

    Every entry has to correspond to a patch that still exists, or it is a claim
    about code that has moved on.
    """
    live = {(facade, name) for _, _, facade, name in _targets()}
    stale = [
        f"{facade}.{name}"
        for facade, names in FACADE_TARGETS_OK.items()
        for name in names
        # `odoo.service.db`'s entries mirror test_db_patch_targets.PACKAGE_LEVEL_OK
        # and are kept in step with it, not with the current patch set.
        if facade != "odoo.service.db" and (facade, name) not in live
    ]
    assert not stale, (
        "FACADE_TARGETS_OK records a reason for a patch that no longer exists:\n"
        "  " + "\n  ".join(stale) + "\nDrop the entry."
    )


def test_the_two_gates_agree_about_the_db_package():
    """This gate must not quietly permit what the stricter one rejects."""
    from .test_db_patch_targets import PACKAGE_LEVEL_OK

    assert set(FACADE_TARGETS_OK["odoo.service.db"]) == set(PACKAGE_LEVEL_OK), (
        "the odoo.service.db entries here have drifted from "
        "test_db_patch_targets.PACKAGE_LEVEL_OK, which is the authority for that "
        "package"
    )


def test_the_gate_would_catch_a_regression():
    """Non-vacuity: the detector must fire on the form it exists to reject."""
    assert _TARGET.search('patch("odoo.api.SUPERUSER_ID")')
    assert _TARGET.search("patch('odoo.service.server.WorkerCron')")
    assert _TARGET.search('patch("odoo.fields.Many2one")')
    # ...and not on a target that names the defining module.
    assert not _TARGET.search('patch("odoo.orm.runtime.environment.Environment")')
    assert not _TARGET.search('patch("odoo.service._threaded.ThreadedServer")')


def test_the_scan_reaches_the_files_it_claims_to():
    """Guard the guard: an empty scan would make every assertion above vacuous."""
    assert len(patch_target_sources()) > 100
    assert list(_targets()), "no façade-aimed patch found anywhere; scan is broken"
