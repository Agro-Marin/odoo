"""``Cursor.commit_count`` — the durability signal ``retrying()`` reads.

``odoo.service.transaction.retrying`` distinguishes "the COMMIT itself failed"
from "the COMMIT succeeded and a post-commit hook raised" by comparing
``commit_count`` before and after ``cr.commit()`` (transaction.py:230-241).
``Cursor.commit`` does both behind one call, so the *only* thing that tells them
apart is whether the counter moved.

That makes the increment's placement load-bearing. In ``Cursor.commit`` it sits
between ``self._cnx.commit()`` and ``self.postcommit.run()``: after the SQL
COMMIT, before the hooks. If it were bumped *after* the hooks, a raising hook
would make a durable commit look like a failed one — and the retry loop would
then reset the registry to a pre-change state the database has already accepted
and skip ``signal_changes()``, leaving every other worker on a stale registry
for a committed change.

These pin the ordering against a real cursor and a real COMMIT — the counter is
observable only once the SQL COMMIT has actually happened, so a mock could not
catch a regression that reordered it.
"""

import pytest

from .conftest import requires_pg


@requires_pg
class TestCommitCountOrdering:
    def _cursor(self, scratch_db):
        import odoo.db

        return odoo.db.db_connect(scratch_db).cursor()

    def test_starts_at_zero_and_counts_each_commit(self, scratch_db):
        cr = self._cursor(scratch_db)
        try:
            assert cr.commit_count == 0
            cr.commit()
            assert cr.commit_count == 1
            cr.commit()
            assert cr.commit_count == 2, "one increment per COMMIT, no skips"
        finally:
            cr.close()

    def test_postcommit_hook_sees_the_count_already_incremented(self, scratch_db):
        """The ordering guarantee: hooks run after the counter moves."""
        cr = self._cursor(scratch_db)
        try:
            before = cr.commit_count
            seen = {}

            def hook():
                seen["count"] = cr.commit_count

            cr.postcommit.add(hook)
            cr.commit()
            assert seen["count"] == before + 1, (
                "the post-commit hook must observe the bumped count, not the old one"
            )
        finally:
            cr.close()

    def test_a_raising_postcommit_hook_still_reads_as_durable(self, scratch_db):
        """The exact case retrying() guards: hook raises, commit is still durable."""
        cr = self._cursor(scratch_db)
        try:
            before = cr.commit_count

            def boom():
                raise RuntimeError("post-commit hook blew up")

            cr.postcommit.add(boom)
            with pytest.raises(RuntimeError, match="blew up"):
                cr.commit()
            # This is what retrying() checks to pick the durable branch: the
            # counter moved even though commit() propagated the hook's error.
            assert cr.commit_count > before
            assert cr.commit_count == before + 1
        finally:
            cr.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
