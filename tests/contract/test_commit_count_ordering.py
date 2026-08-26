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
        cr = self._cursor(scratch_db)
        try:
            before = cr.commit_count

            def boom():
                raise RuntimeError("post-commit hook blew up")

            cr.postcommit.add(boom)
            with pytest.raises(RuntimeError, match="blew up"):
                cr.commit()
            assert cr.commit_count > before
            assert cr.commit_count == before + 1
        finally:
            cr.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
