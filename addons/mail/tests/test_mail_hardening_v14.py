"""Regression tests for the fourteenth mail hardening audit.

Each test pins a defect reproduced end to end before being fixed, so a refactor
cannot silently reintroduce it.
"""

from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.mail.tools.discuss import Store


@tagged("mail_store", "post_install", "-at_install")
class TestStoreRelationBatchingV14(MailCommon):
    """Serializing a batch must not cost one query per distinct related record.

    ``Store`` walks a relation one owner at a time: ``author_id`` of a message
    batch reaches ``Store.add()`` as a single-record partner set that still
    carries the wide many2one prefetch. ``_read_format`` used to resolve its
    cache miss through ``browse(id).with_prefetch(self._ids)``, narrowing that
    prefetch to the one record it held and turning the batch into one full-row
    read per distinct author -- invisible to every existing assertion, which
    pins one fixed N.

    These tests vary N instead: the payload is identical in shape, only the
    number of *distinct* related records changes, so any per-target query shows
    up as a difference between the two measurements.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # res.partner is a mail.thread, so mail can run this without test_mail.
        cls.document = cls.env["res.partner"].create({"name": "V14 Document"})
        cls.authors = cls.env["res.partner"].create(
            [
                {"name": f"V14 Author {idx}", "email": f"v14a{idx}@example.com"}
                for idx in range(20)
            ]
        )
        cls.comment_subtype_id = cls.env.ref("mail.mt_comment").id

    def _post_batch(self, distinct_authors, count=20):
        """Create ``count`` messages spread over ``distinct_authors`` authors."""
        return self.env["mail.message"].create(
            [
                {
                    "author_id": self.authors[idx % distinct_authors].id,
                    "body": f"<p>v14 {idx}</p>",
                    "message_type": "comment",
                    "model": self.document._name,
                    "res_id": self.document.id,
                    "subtype_id": self.comment_subtype_id,
                }
                for idx in range(count)
            ]
        )

    def _store_query_count(self, messages):
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        Store().add(messages).get_result()
        return self.env.cr.sql_log_count - before

    def test_store_query_count_is_flat_in_distinct_authors(self):
        """Same message count, 1 vs 20 authors: the query count must not move."""
        single_author = self._post_batch(1)
        many_authors = self._post_batch(20)
        # Warm up registry/ormcache work that is not per-author, so it cannot be
        # mistaken for the growth under test.
        self._store_query_count(single_author)
        self._store_query_count(many_authors)

        queries_one = self._store_query_count(single_author)
        queries_many = self._store_query_count(many_authors)

        self.assertEqual(
            queries_many,
            queries_one,
            "Store payload cost grew with the number of distinct authors: "
            f"{queries_one} queries for 1 author vs {queries_many} for 20. "
            "A relation target is being read one record at a time -- check that "
            "_read_format_miss_record still prefetches over _prefetch_ids.",
        )

    def test_store_query_count_is_flat_in_message_count(self):
        """The already-batched axis: more messages, same author, same cost."""
        small = self._post_batch(1, count=5)
        large = self._post_batch(1, count=60)
        self._store_query_count(small)
        self._store_query_count(large)

        self.assertEqual(
            self._store_query_count(large),
            self._store_query_count(small),
            "Store payload cost grew with the number of messages.",
        )

    def test_read_format_keeps_the_wider_prefetch(self):
        """The ORM contract the batching rests on, pinned directly.

        A single record carrying a wider prefetch must fetch that whole set on a
        cache miss, not just itself.
        """
        messages = self._post_batch(20)
        self.env.flush_all()
        self.env.invalidate_all()

        # Force the author_id column into cache so the many2one prefetch can
        # enumerate every author, then read one author through the Store path.
        messages.mapped("author_id")
        one_author = messages[0].author_id
        self.assertGreater(
            len(list(one_author._prefetch_ids)),
            1,
            "precondition: the relational value must carry a batch prefetch",
        )

        before = self.env.cr.sql_log_count
        one_author._read_format(["name"], load=False)
        self.assertEqual(
            self.env.cr.sql_log_count - before,
            1,
            "reading one author must cost a single query",
        )

        # That one query must have covered the whole prefetched batch: reading
        # the rest now costs nothing.
        before = self.env.cr.sql_log_count
        messages.author_id.mapped("name")
        self.assertEqual(
            self.env.cr.sql_log_count - before,
            0,
            "the batch read did not cover the other authors",
        )


@tagged("mail_store", "post_install", "-at_install")
class TestReactionBatchingV14(MailCommon):
    """Reactions must cost the same whatever the number of distinct reactors.

    ``mail.message.reaction._to_store`` groups by ``(message, content)`` and
    rebuilds each group with ``union()``, whose prefetch spans only that group.
    Serializing a message with N distinct reactions therefore read one reactor
    per group -- N round trips for what is a single set of partners.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document = cls.env["res.partner"].create({"name": "V14 Reactions"})
        cls.reactors = cls.env["res.partner"].create(
            [
                {"name": f"V14 Reactor {idx}", "email": f"v14r{idx}@example.com"}
                for idx in range(12)
            ]
        )
        cls.comment_subtype_id = cls.env.ref("mail.mt_comment").id

    def _message_with_reactions(self, count):
        """One message carrying ``count`` distinct emoji from distinct partners."""
        message = self.env["mail.message"].create(
            {
                "author_id": self.reactors[0].id,
                "body": "<p>react</p>",
                "message_type": "comment",
                "model": self.document._name,
                "res_id": self.document.id,
                "subtype_id": self.comment_subtype_id,
            }
        )
        self.env["mail.message.reaction"].create(
            [
                {
                    "content": chr(0x1F600 + idx),
                    "message_id": message.id,
                    "partner_id": self.reactors[idx].id,
                }
                for idx in range(count)
            ]
        )
        return message.id

    def _store_query_count(self, message_id):
        # Build the recordset AFTER invalidating: a recordset held across an
        # invalidation loses its prefetch and fakes a per-record read, which
        # would measure the harness rather than the code.
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        Store().add(self.env["mail.message"].browse(message_id)).get_result()
        return self.env.cr.sql_log_count - before

    def test_reaction_query_count_is_flat_in_distinct_reactors(self):
        few = self._message_with_reactions(2)
        many = self._message_with_reactions(12)
        self._store_query_count(few)
        self._store_query_count(many)

        queries_few = self._store_query_count(few)
        queries_many = self._store_query_count(many)

        self.assertEqual(
            queries_many,
            queries_few,
            "reaction payload cost grew with the number of distinct reactors: "
            f"{queries_few} queries for 2 vs {queries_many} for 12. Each grouped "
            "union() must still prefetch over every reactor in the batch.",
        )
