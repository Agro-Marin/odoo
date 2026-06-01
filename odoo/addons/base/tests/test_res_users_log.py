from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestResUsersLogGC(TransactionCase):
    """Coverage for the res.users.log autovacuum GC (audit RUL-T1).

    The GC keeps only the most recent log per user (create_date, then id as
    tie-break) and -- by the semantics of the correlated EXISTS -- never
    collects rows whose create_uid is NULL (documents RUL-L2).

    Setup/teardown use raw SQL because _gc_user_logs itself runs a raw DELETE
    and create_uid/create_date are auto-managed magic columns.
    """

    def test_gc_keeps_latest_per_user(self):
        user = new_test_user(self.env, login="rul_gc_user")
        cr = self.env.cr
        # Three logs, same user, same create_date -> the id tie-break decides.
        cr.execute(
            """
            INSERT INTO res_users_log (create_uid, create_date)
            VALUES (%s, '2020-01-01'), (%s, '2020-01-01'), (%s, '2020-01-01')
            RETURNING id
            """,
            (user.id, user.id, user.id),
        )
        ids = [row[0] for row in cr.fetchall()]

        self.env["res.users.log"]._gc_user_logs()

        cr.execute("SELECT id FROM res_users_log WHERE create_uid = %s", (user.id,))
        remaining = [row[0] for row in cr.fetchall()]
        self.assertEqual(remaining, [max(ids)], "GC must keep only the newest log")

    def test_gc_scopes_per_user(self):
        # RUL-T2: the GC keeps the latest log PER user. User A's newest row must
        # not be deleted just because user B has a (globally) newer row -- the
        # `log1.create_uid = log2.create_uid` correlation guarantees per-user
        # scoping. Pins it against an edit that drops the create_uid equality.
        user_a = new_test_user(self.env, login="rul_gc_a")
        user_b = new_test_user(self.env, login="rul_gc_b")
        cr = self.env.cr
        cr.execute(
            """
            INSERT INTO res_users_log (create_uid, create_date)
            VALUES (%s, '2020-01-01'), (%s, '2020-01-02'),
                   (%s, '2020-03-01'), (%s, '2020-03-02')
            RETURNING id, create_uid
            """,
            (user_a.id, user_a.id, user_b.id, user_b.id),
        )
        rows = cr.fetchall()
        a_ids = sorted(rid for rid, uid in rows if uid == user_a.id)
        b_ids = sorted(rid for rid, uid in rows if uid == user_b.id)

        self.env["res.users.log"]._gc_user_logs()

        cr.execute(
            "SELECT id FROM res_users_log WHERE create_uid = ANY(%s) ORDER BY id",
            ([user_a.id, user_b.id],),
        )
        remaining = [rid for (rid,) in cr.fetchall()]
        self.assertEqual(
            remaining,
            sorted([a_ids[-1], b_ids[-1]]),
            "GC must keep the latest log of EACH user (per-user scoping, RUL-T2)",
        )

    def test_gc_never_collects_null_create_uid(self):
        # RUL-L2: NULL create_uid rows are never matched by `log1.create_uid =
        # log2.create_uid` (NULL = NULL is never true), so they all survive.
        cr = self.env.cr
        cr.execute("SELECT count(*) FROM res_users_log WHERE create_uid IS NULL")
        before = cr.fetchone()[0]
        cr.execute(
            """
            INSERT INTO res_users_log (create_uid, create_date)
            VALUES (NULL, '2020-02-02'), (NULL, '2020-02-02')
            """
        )

        self.env["res.users.log"]._gc_user_logs()

        cr.execute("SELECT count(*) FROM res_users_log WHERE create_uid IS NULL")
        self.assertEqual(cr.fetchone()[0], before + 2)
