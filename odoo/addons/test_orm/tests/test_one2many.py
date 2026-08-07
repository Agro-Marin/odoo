from odoo import Command
from odoo.exceptions import MissingError, UserError

from odoo.addons.base.tests.test_expression import TransactionExpressionCase


class One2manyCase(TransactionExpressionCase):
    def setUp(self):
        super().setUp()
        self.Line = self.env["test_orm.multi.line"]
        self.multi = self.env["test_orm.multi"].create(
            {
                "name": "What is up?",
            }
        )

        self.Edition = self.env["test_orm.creativework.edition"]
        self.Book = self.env["test_orm.creativework.book"]
        self.Movie = self.env["test_orm.creativework.movie"]

        book_model_id = (
            self.env["ir.model"].search([("model", "=", self.Book._name)]).id
        )
        movie_model_id = (
            self.env["ir.model"].search([("model", "=", self.Movie._name)]).id
        )

        books_data = (
            ("Imaginary book", ()),
            ("Another imaginary book", ()),
            ("Nineteen Eighty Four", ("First edition", "Fourth Edition")),
        )

        movies_data = (
            ("The Gold Rush", ("1925 (silent)", "1942")),
            ("Imaginary movie", ()),
            ("Another imaginary movie", ()),
        )

        for name, editions in books_data:
            book_id = self.Book.create({"name": name}).id
            for edition in editions:
                self.Edition.create(
                    {
                        "res_model_id": book_model_id,
                        "name": edition,
                        "res_id": book_id,
                    }
                )

        for name, editions in movies_data:
            movie_id = self.Movie.create({"name": name}).id
            for edition in editions:
                self.Edition.create(
                    {
                        "res_model_id": movie_model_id,
                        "name": edition,
                        "res_id": movie_id,
                    }
                )

    def operations(self):
        self.assertItemsEqual(
            self.multi.lines.mapped("name"), [str(i) for i in range(10)]
        )
        self.multi.lines[0].name = "hello"
        self.multi.lines = self.multi.lines[:-1]
        self.assertEqual(len(self.multi.lines), 9)
        self.assertIn("hello", self.multi.lines.mapped("name"))
        if not self.multi.id:
            return
        self.env.invalidate_all()
        self.assertEqual(len(self.multi.lines), 9)
        self.assertIn("hello", self.multi.lines.mapped("name"))

    def test_new_one_by_one(self):
        for name in range(10):
            self.multi.lines |= self.Line.new({"name": str(name)})
        self.operations()

    def test_new_single(self):
        self.multi.lines = self.Line.browse(
            [self.Line.new({"name": str(name)}).id for name in range(10)],
        )
        self.operations()

    def test_create_one_by_one(self):
        for name in range(10):
            self.multi.lines |= self.Line.create({"name": str(name)})
        self.operations()

    def test_create_single(self):
        self.multi.lines = self.Line.browse(
            [self.Line.create({"name": str(name)}).id for name in range(10)],
        )
        self.operations()

    def test_rpcstyle_one_by_one(self):
        for name in range(10):
            self.multi.lines = [Command.create({"name": str(name)})]
        self.operations()

    def test_rpcstyle_one_by_one_on_new(self):
        self.multi = self.env["test_orm.multi"].new(
            {
                "name": "What is up?",
            }
        )
        for name in range(10):
            self.multi.lines = [Command.create({"name": str(name)})]
        self.operations()

    def test_rpcstyle_single(self):
        self.multi.lines = [Command.create({"name": str(name)}) for name in range(10)]
        self.operations()

    def test_rpcstyle_single_on_new(self):
        self.multi = self.env["test_orm.multi"].new(
            {
                "name": "What is up?",
            }
        )
        self.multi.lines = [Command.create({"name": str(name)}) for name in range(10)]
        self.operations()

    def test_many2one_integer(self):

        def t(records):
            return records.mapped(lambda r: (r.id, r.name))

        books = self.Book.search([])
        movies = self.Movie.search([])
        movies_without_edition = movies.filtered(lambda r: not r.editions)
        movies_with_edition = movies.filtered(lambda r: r.editions)
        movie_editions = movies_with_edition.editions
        one_movie_edition = movie_editions[0]

        res_movies_without_edition = self._search(
            self.Movie, [("editions", "=", False)]
        )
        self.assertItemsEqual(t(res_movies_without_edition), t(movies_without_edition))

        res_movies_with_edition = self._search(self.Movie, [("editions", "!=", False)])
        self.assertItemsEqual(t(res_movies_with_edition), t(movies_with_edition))

        res_books_with_movie_edition = self._search(
            self.Book, [("editions", "in", movie_editions.ids)]
        )
        self.assertFalse(t(res_books_with_movie_edition))

        res_books_without_movie_edition = self._search(
            self.Book, [("editions", "not in", movie_editions.ids)]
        )
        self.assertItemsEqual(t(res_books_without_movie_edition), t(books))

        res_books_without_one_movie_edition = self._search(
            self.Book, [("editions", "not in", movie_editions[:1].ids)]
        )
        self.assertItemsEqual(t(res_books_without_one_movie_edition), t(books))

        res_books_with_one_movie_edition_name = self._search(
            self.Book, [("editions", "=", movie_editions[:1].name)]
        )
        self.assertFalse(t(res_books_with_one_movie_edition_name))

        res_books_without_one_movie_edition_name = self._search(
            self.Book, [("editions", "!=", movie_editions[:1].name)]
        )
        self.assertItemsEqual(t(res_books_without_one_movie_edition_name), t(books))

        res_movies_not_of_edition_name = self._search(
            self.Movie, [("editions", "!=", one_movie_edition.name)]
        )
        self.assertItemsEqual(
            t(res_movies_not_of_edition_name),
            t(movies.filtered(lambda r: one_movie_edition not in r.editions)),
        )

    def test_merge_partner(self):
        model = self.env["test_orm.field_with_caps"]
        partner = self.env["res.partner"]

        p1 = partner.create({"name": "test1"})
        p2 = partner.create({"name": "test2"})

        model1 = model.create({"pArTneR_321_id": p1.id})
        model2 = model.create({"pArTneR_321_id": p2.id})

        self.env["base.partner.merge.automatic.wizard"]._merge((p1 + p2).ids, p1)

        self.assertFalse(p2.exists())
        self.assertTrue(p1.exists())

        self.assertEqual(model1.pArTneR_321_id, p1)
        self.assertTrue(model2.exists())
        self.assertEqual(model2.pArTneR_321_id, p1)

    def test_merge_partner_archived(self):
        partner = self.env["res.partner"]

        p1 = partner.create({"name": "test1"})
        p2 = partner.create({"name": "test2"})
        p3 = partner.create({"name": "test3", "active": False})
        partners_ids = p1 + p2 + p3

        wizard = (
            self.env["base.partner.merge.automatic.wizard"]
            .with_context(active_ids=partners_ids.ids, active_model="res.partner")
            .create({})
        )

        self.assertEqual(wizard.partner_ids, partners_ids)
        self.assertEqual(wizard.dst_partner_id, p2)

        wizard.action_merge()

        self.assertFalse(p1.exists())
        self.assertTrue(p2.exists())
        self.assertFalse(p3.exists())

    def test_partner_merge_wizard_more_than_one_user_error(self):
        p1, p2, dst_partner = self.env["res.partner"].create(
            [{"name": f"test{idx + 1}"} for idx in range(3)]
        )
        u1, u2 = self.env["res.users"].create(
            [
                {"name": "test1", "login": "test1", "partner_id": p1.id},
                {"name": "test2", "login": "test2", "partner_id": p2.id},
            ]
        )
        MergeWizard_with_context = self.env[
            "base.partner.merge.automatic.wizard"
        ].with_context(
            active_ids=(u1.partner_id + u2.partner_id + dst_partner).ids,
            active_model="res.partner",
        )

        with self.assertRaises(UserError):
            MergeWizard_with_context.create({}).action_merge()

        u2.action_archive()
        with self.assertRaises(UserError):
            MergeWizard_with_context.create({}).action_merge()

        u2.unlink()
        MergeWizard_with_context.create({}).action_merge()
        self.assertTrue(dst_partner.exists())
        self.assertEqual(u1.partner_id.id, dst_partner.id)

    def test_cache_invalidation(self):
        record0 = self.env["test_orm.attachment.host"].create({})
        with self.assertQueryCount(0):
            self.assertFalse(record0.attachment_ids, "inconsistent cache")

        attachment = self.env["test_orm.attachment"].create(
            {
                "res_model": record0._name,
                "res_id": record0.id,
            }
        )
        self.env.flush_all()
        with self.assertQueryCount(0):
            self.assertEqual(
                attachment.name,
                record0.display_name,
                "field should be computed",
            )
        with self.assertQueryCount(1):
            self.assertEqual(record0.attachment_ids, attachment, "inconsistent cache")

        with self.assertQueryCount(1):
            record1 = self.env["test_orm.attachment.host"].create({})
        with self.assertQueryCount(0):
            attachment.res_id
        with self.assertQueryCount(0):
            self.assertFalse(record1.attachment_ids, "inconsistent cache")

        attachment.res_id = record1.id
        self.env.flush_all()
        with self.assertQueryCount(0):
            self.assertEqual(
                attachment.name,
                record1.display_name,
                "field should be recomputed",
            )
        with self.assertQueryCount(1):
            self.assertEqual(record1.attachment_ids, attachment, "inconsistent cache")
        with self.assertQueryCount(1):
            self.assertFalse(record0.attachment_ids, "inconsistent cache")

    def test_recompute(self):
        discussion = self.env.ref("test_orm.discussion_0")
        self.assertTrue(discussion.messages)

        message = discussion.messages[0]
        message.discussion = False

    def test_dont_write_the_existing_childs(self):
        parent = self.env["test_orm.model_parent_m2o"].create(
            {
                "name": "parent",
                "child_ids": [Command.create({"name": "A"})],
            }
        )
        a = parent.child_ids[0]
        parent.write({"child_ids": [Command.link(a.id), Command.create({"name": "B"})]})

    def test_create_with_commands(self):
        order = self.env["test_orm.order"].create(
            {
                "line_ids": [
                    Command.create({"product": name}) for name in ("set", "sept")
                ],
            }
        )
        line1, line2 = order.line_ids

        with self.assertQueryCount(2):
            self.env["test_orm.order"].create(
                {
                    "line_ids": [Command.set(line1.ids)],
                }
            )

        with self.assertQueryCount(3):
            order = self.env["test_orm.order"].create(
                {
                    "line_ids": [Command.set(line1.ids)],
                }
            )
            thief = self.env["test_orm.order"].create(
                {
                    "line_ids": [Command.set((line1 + line2).ids)],
                }
            )

        self.assertFalse(order.line_ids)
        self.assertEqual(thief.line_ids, line1 + line2)

    def test_recomputation_ends(self):
        parent = self.env["test_orm.model_parent_m2o"].create({"name": "parent"})
        child = self.env["test_orm.model_child_m2o"].create(
            {"name": "A", "parent_id": parent.id}
        )
        self.assertEqual(child.size1, 6)

        parent.unlink()
        self.env.flush_all()

    def test_compute_stored_many2one_one2many(self):
        container = self.env["test_orm.compute.container"].create({"name": "Foo"})
        self.assertFalse(container.member_ids)
        member = self.env["test_orm.compute.member"].create({"name": "Foo"})
        self.assertEqual(container.member_ids, member)
        self.assertEqual(container.member_count, 1)

        member.name = "Bar"
        self.assertEqual(container.member_count, 0)

        member.name = "Foo"
        self.assertEqual(container.member_count, 1)

    def test_reward_line_delete(self):
        order = self.env["test_orm.order"].create(
            {
                "line_ids": [
                    Command.create({"product": "a"}),
                    Command.create({"product": "b"}),
                    Command.create({"product": "b", "reward": True}),
                ],
            }
        )
        line0, line1, line2 = order.line_ids

        order.write(
            {
                "line_ids": [
                    Command.link(line0.id),
                    Command.delete(line1.id),
                    Command.link(line2.id),
                ],
            }
        )
        self.assertEqual(order.line_ids, line0)

        with self.assertRaises(MissingError):
            order.write(
                {
                    "line_ids": [
                        Command.link(line0.id),
                        Command.link(line1.id),
                    ],
                }
            )

    def test_new_real_interactions(self):
        parent = self.env["test_orm.model_parent_m2o"].create({"name": "parentB"})
        new_child = self.env["test_orm.model_child_m2o"].new(
            {"name": "B", "parent_id": parent.id}
        )

        self.assertFalse(parent.child_ids)
        self.assertEqual(new_child.parent_id, parent)

        parent.child_ids += new_child
        self.assertTrue(parent.child_ids)
        self.assertNotEqual(parent.child_ids, new_child)

        new_parent = self.env["test_orm.model_parent_m2o"].new(
            {
                "name": "parentC3PO",
                "child_ids": [(0, 0, {"name": "C3"})],
            }
        )
        self.assertEqual(new_parent, new_parent.child_ids.parent_id)
        self.assertFalse(new_parent.id)
        self.assertTrue(new_parent.child_ids)
        self.assertFalse(new_parent.child_ids.ids)

        new_child = self.env["test_orm.model_child_m2o"].new(
            {
                "name": "PO",
            }
        )
        new_parent.child_ids += new_child
        self.assertIn(new_child, new_parent.child_ids)
        self.assertEqual(len(new_parent.child_ids), 2)
        self.assertListEqual(new_parent.child_ids.mapped("name"), ["C3", "PO"])

        new_child2 = self.env["test_orm.model_child_m2o"].new(
            {
                "name": "R2D2",
                "parent_id": new_parent.id,
            }
        )
        self.assertIn(new_child2, new_parent.child_ids)
        self.assertEqual(len(new_parent.child_ids), 3)
        self.assertListEqual(new_parent.child_ids.mapped("name"), ["C3", "PO", "R2D2"])

        name = type(new_parent).name
        child_ids = type(new_parent).child_ids
        parent = self.env["test_orm.model_parent_m2o"].create(
            {
                "name": name.convert_to_write(new_parent.name, new_parent),
                "child_ids": child_ids.convert_to_write(
                    new_parent.child_ids, new_parent
                ),
            }
        )
        self.assertEqual(len(parent.child_ids), 3)
        self.assertEqual(parent, parent.child_ids.parent_id)
        self.assertEqual(parent.child_ids.mapped("name"), ["C3", "PO", "R2D2"])

    def test_parent_id(self):
        Team = self.env["test_orm.team"]
        Member = self.env["test_orm.team.member"]

        probe_team = Team.create({"name": "seq-probe"})
        probe_member = Member.create({"name": "seq-probe"})
        gap = probe_team.id - probe_member.id
        if gap > 0:
            Member.create([{"name": "seq-filler"} for _ in range(gap)])
        elif gap < 0:
            Team.create([{"name": "seq-filler"} for _ in range(-gap)])

        team1 = Team.create({"name": "ORM"})
        team2 = Team.create({"name": "Bugfix", "parent_id": team1.id})
        team3 = Team.create({"name": "Support", "parent_id": team2.id})

        member1 = Member.create({"name": "Raphael", "team_id": team1.id})
        member2 = Member.create({"name": "Noura", "team_id": team3.id})
        Member.create({"name": "Ivan", "team_id": team2.id})

        self.assertEqual(member1.id, team1.id)
        self.assertEqual(member2.id, member2.team_id.parent_id.id)

        Team.search([("member_ids", "child_of", member2.id)])

        team1.parent_id = team1.id
        self._search(Team, [("id", "parent_of", team1.id)])
        self._search(Team, [("id", "child_of", team1.id)])

    def test_create_one2many_with_unsearchable_field(self):
        unsearchableO2M = self.env["test_orm.unsearchable.o2m"]

        parent_record1 = unsearchableO2M.create(
            {
                "name": "Parent 1",
            }
        )

        parent_record2 = unsearchableO2M.create(
            {
                "name": "Parent 2",
            }
        )

        children = {parent_record1.id: [], parent_record2.id: []}
        for i in range(5):
            child = unsearchableO2M.create(
                {
                    "name": f"Child {i}",
                    "stored_parent_id": parent_record1.id,
                    "parent_id": parent_record1.id,
                }
            )
            self.assertEqual(child.parent_id, parent_record1)
            children[parent_record1.id].append(child.id)

        for i in range(5, 10):
            child = unsearchableO2M.create(
                {
                    "name": f"Child {i}",
                    "stored_parent_id": parent_record2.id,
                    "parent_id": parent_record2.id,
                }
            )
            self.assertEqual(child.parent_id, parent_record2)
            children[parent_record2.id].append(child.id)

        self.env.invalidate_all()
        with self.assertRaisesRegex(ValueError, r"it is not stored"):
            self.assertEqual(parent_record1.child_ids.ids, children[parent_record1.id])

    def test_computed_inverse_one2many(self):
        record = self.env["test_orm.computed_inverse_one2many"].create(
            {
                "name": "SuperRecord",
                "low_priority_line_ids": [
                    Command.create(
                        {
                            "name": "SuperChild 01",
                            "priority": 1,
                        }
                    )
                ],
            }
        )
        self.assertTrue(record.low_priority_line_ids.ids)

        record.low_priority_line_ids = [
            Command.create(
                {
                    "name": "SuperChild 02",
                    "priority": 2,
                }
            )
        ]
        self.assertEqual(len(record.low_priority_line_ids.ids), 2)

    def test_convert_to_write_partial_cache_origin(self):
        multi = self.env["test_orm.multi"].create(
            {"lines": [Command.create({"name": "L1"}), Command.create({"name": "L2"})]}
        )
        line_ids = multi.lines.ids
        field = multi._fields["lines"]

        self.env.invalidate_all()
        new_lines = self.env["test_orm.multi.line"].browse()
        for line in self.env["test_orm.multi.line"].browse(line_ids):
            new_lines |= self.env["test_orm.multi.line"].new(
                {"name": "CHANGED"}, origin=line
            )

        result = field.convert_to_write(new_lines, multi)
        self.assertEqual(result[0], Command.set(line_ids))
        updates = [cmd for cmd in result if cmd[0] == Command.UPDATE]
        self.assertEqual(len(updates), 2)
        self.assertTrue(all(cmd[2] == {"name": "CHANGED"} for cmd in updates))


class One2manyCommandOrderCase(TransactionExpressionCase):
    def setUp(self):
        super().setUp()
        self.Multi = self.env["test_orm.multi"]

    def _parent(self, *names):
        parent = self.Multi.create(
            {"lines": [Command.create({"name": name}) for name in names]}
        )
        self.env.flush_all()
        return parent

    def _names(self, parent):
        self.env.flush_all()
        self.env.invalidate_all()
        return sorted(parent.lines.mapped("name"))

    def test_clear_after_create_empties_the_relation(self):
        parent = self._parent("s0", "s1")
        parent.write({"lines": [Command.create({"name": "new"}), Command.clear()]})
        self.assertEqual(self._names(parent), [])

    def test_set_empty_after_create_empties_the_relation(self):
        parent = self._parent("s0", "s1")
        parent.write({"lines": [Command.create({"name": "new"}), Command.set([])]})
        self.assertEqual(self._names(parent), [])

    def test_set_after_create_keeps_only_the_set_lines(self):
        parent = self._parent("s0", "s1")
        keep = parent.lines.filtered(lambda line: line.name == "s0")
        parent.write(
            {"lines": [Command.create({"name": "new"}), Command.set(keep.ids)]}
        )
        self.assertEqual(self._names(parent), ["s0"])

    def test_clear_after_link_empties_the_relation(self):
        parent = self._parent("s0")
        orphan = self.env["test_orm.multi.line"].create({"name": "orphan"})
        self.env.flush_all()
        parent.write({"lines": [Command.link(orphan.id), Command.clear()]})
        self.assertEqual(self._names(parent), [])

    def test_one_write_agrees_with_split_writes(self):
        commands = [Command.create({"name": "new"}), Command.clear()]
        together = self._parent("s0", "s1")
        together.write({"lines": commands})

        split = self._parent("s0", "s1")
        for command in commands:
            split.write({"lines": [command]})

        self.assertEqual(self._names(together), self._names(split))

    def test_commands_before_the_clear_still_apply_in_order(self):
        parent = self._parent("s0")
        parent.write({"lines": [Command.clear(), Command.create({"name": "after"})]})
        self.assertEqual(self._names(parent), ["after"])

    def test_creation_mode_is_unchanged(self):
        orphan = self.env["test_orm.multi.line"].create({"name": "orphan"})
        self.env.flush_all()
        parent = self.Multi.create(
            {"lines": [Command.create({"name": "c1"}), Command.set([orphan.id])]}
        )
        self.assertEqual(self._names(parent), ["c1", "orphan"])
