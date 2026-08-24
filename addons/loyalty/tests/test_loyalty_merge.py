# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLoyaltyNominative(TransactionCase):
    """"Nominative" as one statement, and the partner merge that reads it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.programs = cls.env['loyalty.program']
        selection = dict(cls.env['loyalty.program']._fields['program_type'].selection)
        for program_type in selection:
            for applies_on in ('current', 'future', 'both'):
                program = cls.env['loyalty.program'].create({
                    'name': f"{program_type}/{applies_on}", 'program_type': program_type,
                })
                program.applies_on = applies_on
                cls.programs |= program
        cls.env.flush_all()

    def test_reading_and_searching_is_nominative_agree(self):
        """The compute and the search are the same domain, over every combination."""
        searched = set(self.programs.filtered_domain([('is_nominative', '=', True)]).ids)
        computed = {program.id for program in self.programs if program.is_nominative}

        self.assertEqual(searched, computed)
        self.assertTrue(computed, "some combinations are nominative, or this proves nothing")

    def test_searching_for_the_negative_agrees_too(self):
        """`= False` and `!= True` both answer the complement."""
        nominative = {program.id for program in self.programs if program.is_nominative}
        rest = set(self.programs.ids) - nominative

        for domain in ([('is_nominative', '=', False)], [('is_nominative', '!=', True)]):
            with self.subTest(domain=domain):
                found = set(self.env['loyalty.program'].search(domain).ids) & set(self.programs.ids)
                self.assertEqual(found, rest)

    def test_an_unsupported_operator_is_handed_back(self):
        """The search method guesses at nothing it was not written for."""
        self.assertIs(
            self.env['loyalty.program']._search_is_nominative('like', 'x'), NotImplemented
        )


@tagged('post_install', '-at_install')
class TestLoyaltyMerge(TransactionCase):
    """Merging the nominative cards of partners that are merged together."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # `applies_on` is what makes a program nominative, and `create` does not
        # infer it from the type -- see `_with_program_type_values`.
        cls.program = cls.env['loyalty.program'].create({
            'name': "Merge program", 'program_type': 'loyalty', 'applies_on': 'both',
        })
        cls.env.flush_all()

    def test_the_fixture_program_is_nominative(self):
        """Everything below only means something if it is."""
        self.assertTrue(self.program.is_nominative)

    def _card(self, partner, points):
        return self.env['loyalty.card'].with_context(loyalty_no_mail=True).create(
            {'program_id': self.program.id, 'partner_id': partner.id, 'points': points}
        )

    def test_the_oldest_card_survives_when_the_destination_has_none(self):
        """`id:recordset` promises no order; the survivor must not be arbitrary."""
        first, second, destination = self.env['res.partner'].create([
            {'name': "Merge first"}, {'name': "Merge second"}, {'name': "Merge dest"},
        ])
        oldest = self._card(first, 10)
        self._card(second, 20)
        self.env.flush_all()

        self.env['base.partner.merge.automatic.wizard']._merge(
            [first.id, second.id, destination.id], destination
        )

        surviving = self.env['loyalty.card'].search([
            ('partner_id', '=', destination.id), ('program_id', '=', self.program.id),
        ])
        self.assertEqual(surviving, oldest)
        self.assertEqual(surviving.points, 30)

    def test_the_destination_card_survives_when_it_has_one(self):
        """An existing card of the destination keeps its identity and its history."""
        source, destination = self.env['res.partner'].create([
            {'name': "Merge src"}, {'name': "Merge dst"},
        ])
        self._card(source, 10)
        kept = self._card(destination, 5)
        self.env.flush_all()

        self.env['base.partner.merge.automatic.wizard']._merge(
            [source.id, destination.id], destination
        )

        self.assertEqual(kept.points, 15)
        self.assertTrue(kept.active)

    def test_the_move_is_written_to_the_history(self):
        """The surviving balance has to say where it came from."""
        source, destination = self.env['res.partner'].create([
            {'name': "Merge hist src"}, {'name': "Merge hist dst"},
        ])
        drained = self._card(source, 40)
        kept = self._card(destination, 2)
        self.env.flush_all()

        self.env['base.partner.merge.automatic.wizard']._merge(
            [source.id, destination.id], destination
        )

        moved_in = self.env['loyalty.history'].search([('card_id', '=', kept.id)])
        self.assertEqual(sum(moved_in.mapped('issued')), 40)
        moved_out = self.env['loyalty.history'].search([('card_id', '=', drained.id)])
        self.assertEqual(sum(moved_out.mapped('used')), 40)

    def test_a_non_nominative_program_is_left_alone(self):
        """Only cards whose points belong to a customer are merged."""
        anonymous = self.env['loyalty.program'].create({
            'name': "Merge coupons", 'program_type': 'coupons',
        })
        self.env.flush_all()
        self.assertFalse(anonymous.is_nominative)

        source, destination = self.env['res.partner'].create([
            {'name': "Merge anon src"}, {'name': "Merge anon dst"},
        ])
        card = self.env['loyalty.card'].with_context(loyalty_no_mail=True).create(
            {'program_id': anonymous.id, 'partner_id': source.id, 'points': 7}
        )
        self.env.flush_all()

        self.env['base.partner.merge.automatic.wizard']._merge(
            [source.id, destination.id], destination
        )

        self.assertEqual(card.points, 7, "its balance was not folded into another card")
        self.assertTrue(card.active)

    def test_merging_many_programs_does_not_search_per_program(self):
        """The destination's cards are found once, not once per program."""
        programs = self.env['loyalty.program'].create([
            {'name': f"Merge many {index}", 'program_type': 'loyalty', 'applies_on': 'both'}
            for index in range(8)
        ])
        source, destination = self.env['res.partner'].create([
            {'name': "Merge many src"}, {'name': "Merge many dst"},
        ])
        Card = self.env['loyalty.card'].with_context(loyalty_no_mail=True)
        Card.create([
            {'program_id': program.id, 'partner_id': source.id, 'points': 3}
            for program in programs
        ])
        self.env.flush_all()
        self.env.invalidate_all()

        before = self.env.cr.sql_log_count
        self.env['base.partner.merge.automatic.wizard']._merge_loyalty_cards(
            source, destination
        )
        self.env.flush_all()
        queries = self.env.cr.sql_log_count - before

        self.assertLess(
            queries, 8 * 3,
            f"{queries} queries to merge 8 programs -- the destination lookup is"
            f" supposed to happen once",
        )
        self.assertEqual(
            len(Card.search([('partner_id', '=', destination.id)])), 8
        )
