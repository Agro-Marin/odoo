from odoo.tests import TransactionCase


class TestCountField(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Container = cls.env["test_orm.count.container"]
        cls.Line = cls.env["test_orm.count.line"]
        cls.Tag = cls.env["test_orm.count.tag"]
        cls.tags = cls.Tag.create([{"name": f"t{i}"} for i in range(5)])
        cls.containers = cls.Container.create(
            [{"name": f"c{i}", "tag_ids": [(6, 0, cls.tags[:i].ids)]} for i in range(4)]
        )
        cls.Line.create(
            [
                {
                    "name": f"l{index}-{line}",
                    "container_id": container.id,
                    "important": line % 2 == 0,
                    "active": line != 1,
                }
                for index, container in enumerate(cls.containers)
                for line in range(index * 3)
            ]
        )

    def assert_matches_len(self, records=None):
        records = records if records is not None else self.containers
        pairs = [
            ("line_count", "len_line_count"),
            ("important_line_count", "len_important_line_count"),
            ("all_line_count", "len_all_line_count"),
            ("unstored_inverse_count", "len_unstored_inverse_count"),
            ("computed_inverse_count", "len_computed_inverse_count"),
            ("tag_count", "len_tag_count"),
        ]
        for count_name, len_name in pairs:
            self.env.invalidate_all()
            counted = [record[count_name] for record in records]
            self.env.invalidate_all()
            expected = [record[len_name] for record in records]
            self.assertEqual(counted, expected, f"{count_name} != {len_name}")

    def test_counts_match_len(self):
        self.assert_matches_len()
        self.env.invalidate_all()
        self.assertEqual([c.line_count for c in self.containers], [0, 2, 5, 8])
        self.assertEqual([c.all_line_count for c in self.containers], [0, 3, 6, 9])

    def test_domain_on_the_counted_field_is_applied(self):
        self.env.invalidate_all()
        self.assertEqual(
            [c.important_line_count for c in self.containers],
            [len(c.important_line_ids) for c in self.containers],
        )
        self.assertNotEqual(
            [c.important_line_count for c in self.containers],
            [c.line_count for c in self.containers],
        )

    def test_archived_lines_follow_the_counted_field(self):
        self.env.invalidate_all()
        container = self.containers[3]
        self.assertEqual(container.line_count, 8)
        self.assertEqual(container.all_line_count, 9)
        self.assert_matches_len()

    def test_active_test_in_context_is_not_cached_across_contexts(self):
        container = self.containers[3]
        self.env.invalidate_all()
        self.assertEqual(container.line_count, 8)
        self.assertEqual(container.with_context(active_test=False).line_count, 9)
        self.assertEqual(container.line_count, 8)

    def test_new_records_count_their_in_memory_lines(self):
        container = self.Container.new(
            {"name": "n", "line_ids": [(0, 0, {"name": "a"}), (0, 0, {"name": "b"})]}
        )
        self.assertEqual(container.line_count, 2)
        self.assertEqual(container.line_count, container.len_line_count)

    def test_onchange_style_edit_updates_the_count(self):
        container = self.Container.new({"name": "n"})
        self.assertEqual(container.line_count, 0)
        container.line_ids = [(0, 0, {"name": "a"})]
        self.assertEqual(container.line_count, 1)

    def test_unstored_inverse_degrades_to_len(self):
        field = self.Container._fields["unstored_inverse_count"]
        self.assertFalse(field.counts_in_database)
        self.assertTrue(self.Container._fields["line_count"].counts_in_database)
        self.assert_matches_len()

    def test_stored_count_is_maintained(self):
        container = self.containers[1]
        self.assertEqual(container.stored_line_count, 2)
        self.Line.create({"name": "extra", "container_id": container.id})
        self.assertEqual(container.stored_line_count, 3)
        container.line_ids[0].unlink()
        self.assertEqual(container.stored_line_count, 2)

    def test_one_query_for_the_whole_recordset(self):
        self.env.invalidate_all()
        with self.assertQueryCount(1):
            [container.line_count for container in self.containers]

    def test_warm_cache_costs_no_query(self):
        self.env.invalidate_all()
        self.containers.mapped("line_ids")
        with self.assertQueryCount(0):
            [container.line_count for container in self.containers]

    def test_partially_warm_cache_still_matches(self):
        self.env.invalidate_all()
        self.containers[0].line_ids
        self.assertEqual(
            [c.line_count for c in self.containers],
            [0, 2, 5, 8],
        )

    def test_computed_stored_inverse_is_recomputed_before_counting(self):
        field = self.Container._fields["computed_inverse_count"]
        self.assertTrue(field.counts_in_database)
        container = self.containers[1]
        self.env.invalidate_all()
        self.assertEqual(container.computed_inverse_count, 2)
        self.Line.create({"name": "pending", "container_id": container.id})
        self.assertEqual(container.computed_inverse_count, 3)
        self.assertEqual(
            container.computed_inverse_count, container.len_computed_inverse_count
        )

    def test_many2many_count(self):
        self.env.invalidate_all()
        self.assertEqual([c.tag_count for c in self.containers], [0, 1, 2, 3])
        self.assert_matches_len()

    def test_a_delegating_model_gets_the_count_as_a_related_field(self):
        delegate = self.env["test_orm.count.delegate"].create(
            {"container_id": self.containers[3].id}
        )
        field = delegate._fields["line_count"]
        self.assertTrue(field.inherited)
        self.assertEqual(field.related, "container_id.line_count")
        self.assertEqual(delegate.line_count, self.containers[3].line_count)

    def test_field_is_readonly_and_not_stored_by_default(self):
        field = self.Container._fields["line_count"]
        self.assertTrue(field.readonly)
        self.assertFalse(field.store)
        self.assertFalse(field.copy)
        self.assertEqual(field.type, "integer")
        self.assertEqual(
            self.env.registry.field_depends[field], ("line_ids", "line_ids.active")
        )

    def test_a_filtered_count_depends_on_the_fields_its_domain_names(self):
        field = self.Container._fields["important_line_count"]
        self.assertEqual(
            self.env.registry.field_depends[field],
            (
                "important_line_ids",
                "important_line_ids.important",
                "important_line_ids.active",
            ),
        )

    def test_a_count_that_ignores_active_does_not_depend_on_it(self):
        field = self.Container._fields["all_line_count"]
        self.assertEqual(self.env.registry.field_depends[field], ("all_line_ids",))

    def test_archiving_a_line_updates_a_stored_count(self):
        container = self.containers[3]
        self.env.flush_all()
        before = container.stored_line_count
        self.assertEqual(before, len(container.line_ids))

        container.line_ids[0].active = False
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT stored_line_count FROM test_orm_count_container WHERE id = %s",
            (container.id,),
        )
        stored = self.env.cr.fetchone()[0]
        self.env.invalidate_all()
        self.assertEqual(stored, before - 1)
        self.assertEqual(container.stored_line_count, len(container.line_ids))

    def test_a_stored_filtered_count_sees_the_write_that_moved_a_line(self):
        container = self.containers[3]
        self.env.flush_all()
        before = container.stored_important_line_count
        important = container.important_line_ids
        self.assertTrue(important, "the fixture must give this container one")

        important[0].important = False
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT stored_important_line_count FROM test_orm_count_container "
            "WHERE id = %s",
            (container.id,),
        )
        stored = self.env.cr.fetchone()[0]
        self.env.invalidate_all()
        self.assertEqual(stored, before - 1)
        self.assertEqual(
            container.stored_important_line_count, len(container.important_line_ids)
        )

    def test_a_stored_filtered_many2many_count_survives_both_hazards(self):
        container = self.containers[3]
        tags = self.Tag.create([{"name": f"p{i}"} for i in range(3)])
        container.published_tag_ids = [(6, 0, tags.ids)]
        self.env.flush_all()

        field = self.Container._fields["stored_published_tag_count"]
        self.assertEqual(
            self.env.registry.field_depends[field],
            (
                "published_tag_ids",
                "published_tag_ids.container_ids",
                "published_tag_ids.published",
            ),
        )

        def stored():
            self.env.cr.execute(
                "SELECT stored_published_tag_count FROM test_orm_count_container "
                "WHERE id = %s",
                (container.id,),
            )
            return self.env.cr.fetchone()[0]

        self.env.invalidate_all()
        self.assertEqual(stored(), 3)
        self.assertEqual(container.stored_published_tag_count, 3)

        tags[0].published = False
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(stored(), 2)
        self.assertEqual(
            container.stored_published_tag_count, len(container.published_tag_ids)
        )

        tags[1].container_ids = [(3, container.id)]
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(stored(), 1)
        self.assertEqual(
            container.stored_published_tag_count, len(container.published_tag_ids)
        )

    def test_a_computed_collection_is_never_counted_by_query(self):
        field = self.Container._fields["computed_subset_line_count"]
        self.assertFalse(field.counts_in_database)
        self.assertEqual(
            self.env.registry.field_depends[field], ("computed_subset_line_ids",)
        )

        container = self.containers[3]
        expected = len(container.computed_subset_line_ids)
        self.assertTrue(expected, "the fixture must give this container some")
        self.assertNotEqual(
            expected,
            len(container.line_ids),
            "the subset must differ from the whole, or this proves nothing",
        )
        self.env.invalidate_all()
        self.assertEqual(container.computed_subset_line_count, expected)

    def test_a_mixin_may_count_a_collection_it_does_not_declare(self):
        mixin = self.env["mixin.test_orm.count"]
        self.assertTrue(mixin._abstract)
        self.assertIn("mixin_line_count", mixin._fields)

        container = self.containers[3]
        self.assertEqual(container.mixin_line_count, len(container.line_ids))
        self.assertEqual(container.mixin_line_count, container.line_count)

    def test_leaving_the_domain_updates_a_filtered_count(self):
        container = self.containers[3]
        important = container.line_ids.filtered("important")
        self.assertTrue(important, "the fixture must give this container one")
        before = container.important_line_count

        important[0].important = False
        self.env.flush_all()
        self.assertEqual(container.important_line_count, before - 1)
        self.assertEqual(
            container.important_line_count, len(container.important_line_ids)
        )
