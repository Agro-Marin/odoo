import ast
import pathlib

import pytest

from odoo.orm.runtime.backend import InMemoryBackend

_ORM_DIR = pathlib.Path(__file__).resolve().parent.parent

# Every ``env.backend`` dispatch point in the ORM, pinned exact-mode.
#
# ADR-0011 introduced the persistence-backend port to replace nine inline
# ``transaction.storage`` sniffs across six CRUD mixins.  Nothing pinned the
# resulting surface, and it has since grown to fifteen sites across eight files
# -- including four in Layer 1, which ADR-0011 does not mention (it scopes the
# port to "the model mixins (create/write/read/search/unlink)").
#
# Each entry records whether the two branches are known to be BEHAVIOURALLY
# EQUIVALENT.  They are not a formality: where a branch is marked lossy, a
# DB-free test exercising that code path asserts against semantics the SQL path
# has and the in-memory path does not, so it cannot fail for the right reason.
#
# Adding a dispatch site is a real architectural decision (a second persistence
# implementation gains another divergence point).  This gate makes it a
# deliberate one.
DISPATCH_SITES: dict[tuple[str, str], str] = {
    # -- Layer 2: the model mixins.  This is ADR-0011's stated scope. ----------
    ("models/mixins/create.py", "_create"): (
        "in-memory path skips the COPY fast path (performance only)"
    ),
    ("models/mixins/create.py", "_parent_store_create"): (
        "guarded by backend.supports_parent_store"
    ),
    ("models/mixins/read.py", "_fetch_query"): (
        "LOSSY: the SQL branch applies bin_size / bin_size_<field> "
        "(pg_size_pretty) and to_flush bookkeeping; backend.fetch() does not"
    ),
    ("models/mixins/write.py", "_execute_update"): (
        "LOSSY: the SQL branch merges jsonb translations "
        "(COALESCE(...jsonb_build_object('en_US', ...)) || expr) and handles "
        "company_dependent columns; backend.update_rows() does neither"
    ),
    ("models/mixins/write.py", "_parent_store_update_prepare"): (
        "guarded by backend.supports_parent_store"
    ),
    ("models/mixins/unlink.py", "_unlink_process_batch"): (
        "LOSSY: the SQL branch collects ir.model.data + ir.attachment rows and "
        "runs the many2one_company_dependents ir.default cleanup. "
        "InMemoryBackend.delete() returns two EMPTY recordsets and is not even "
        "passed the Defaults recordset the cleanup needs -- see "
        "test_in_memory_delete_is_declared_lossy below"
    ),
    ("models/mixins/search.py", "lock_for_update"): "equivalent",
    ("models/mixins/search.py", "try_lock_for_update"): "equivalent",
    ("models/mixins/_query.py", "_search"): "equivalent",
    ("models/mixins/_query.py", "_as_query"): "equivalent",
    ("models/mixins/_query.py", "exists"): "equivalent",
    # -- Layer 1: NOT in ADR-0011's scope. ------------------------------------
    # Layer 1 reaching a Layer-3 object through env is invisible to
    # orm-layer1-below-models-and-runtime (no import is created).  Listed here
    # so the four are visible rather than merely tolerated.
    ("fields/reference.py", "_reference_exists"): (
        "BACKEND-SNIFF: `env.backend is None` gates a prefetch SELECT, i.e. it "
        "reads as 'am I on PostgreSQL?'.  This is the inline test-backend sniff "
        "ADR-0011 set out to remove, renamed from transaction.storage"
    ),
    ("fields/relational/many2many.py", "read"): "equivalent",
    ("fields/relational/many2many.py", "_apply_relation_delta"): "equivalent",
}

LAYER1_PREFIXES = ("fields/",)


def _dispatch_sites() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(_ORM_DIR.rglob("*.py")):
        rel = path.relative_to(_ORM_DIR).as_posix()
        if "tests/" in rel or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text())
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and node.attr == "backend"):
                continue
            owner = node.value
            is_env = (isinstance(owner, ast.Name) and owner.id == "env") or (
                isinstance(owner, ast.Attribute) and owner.attr == "env"
            )
            if not is_env:
                continue
            enclosing = node
            while enclosing in parents:
                enclosing = parents[enclosing]
                if isinstance(enclosing, ast.FunctionDef | ast.AsyncFunctionDef):
                    found.add((rel, enclosing.name))
                    break
    return found


def test_dispatch_surface_matches_the_pinned_inventory():
    found = _dispatch_sites()
    pinned = set(DISPATCH_SITES)
    added = sorted(found - pinned)
    removed = sorted(pinned - found)
    assert not added, (
        f"new env.backend dispatch site(s): {added}. Each one is a place the "
        f"in-memory and SQL persistence paths may diverge. Add it to "
        f"DISPATCH_SITES with a note stating whether the two branches are "
        f"behaviourally equivalent, and say so in ADR-0011."
    )
    assert not removed, (
        f"env.backend dispatch site(s) gone: {removed}. Good news, but pin it: "
        f"remove the entry from DISPATCH_SITES so the shrink cannot be undone "
        f"silently."
    )


def test_layer1_dispatch_stays_explicitly_enumerated():
    # ADR-0011 scopes the port to the model mixins.  Layer 1 (fields/, domain/)
    # reaching env.backend is a runtime Layer-1 -> Layer-3 dependency that
    # layer_check cannot see, because it travels through `env` and creates no
    # import.  Keep the exception list closed.
    layer1 = {
        site
        for site in _dispatch_sites()
        if site[0].startswith(LAYER1_PREFIXES)
    }
    pinned_layer1 = {
        site for site in DISPATCH_SITES if site[0].startswith(LAYER1_PREFIXES)
    }
    assert layer1 == pinned_layer1, (
        f"Layer-1 env.backend dispatch changed: {sorted(layer1 ^ pinned_layer1)}. "
        f"ADR-0011 scopes the persistence port to the model mixins; a new "
        f"Layer-1 dispatch widens the port's blast radius past its own ADR."
    )


def test_in_memory_delete_is_declared_lossy():
    # Pins the sharpest known divergence so a future fix is deliberate rather
    # than accidental, and so nobody writes a DB-free test that "proves" unlink
    # cascades work.
    import inspect

    source = inspect.getsource(InMemoryBackend.delete)
    assert "Data.browse(), Attachment.browse()" in source, (
        "InMemoryBackend.delete no longer returns two empty recordsets. If it "
        "now really collects ir.model.data / ir.attachment rows, drop this test "
        "and the LOSSY note on unlink in DISPATCH_SITES."
    )
    params = list(inspect.signature(InMemoryBackend.delete).parameters)
    assert "Defaults" not in params, (
        "InMemoryBackend.delete now receives Defaults; if it performs the "
        "many2one_company_dependents cleanup, update the unlink note."
    )


def test_lossy_sites_are_spelled_out():
    # A note is only useful if it says which side loses what.
    for site, note in DISPATCH_SITES.items():
        if note.startswith("LOSSY"):
            assert len(note) > 60, f"{site}: LOSSY note must say what is lost"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
