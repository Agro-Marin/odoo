from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'data_recycle')
class TestDataRecycleUi(HttpCase):

    def test_validate_a_grouped_selection(self):
        """The Validate button reaches `model.root`, which grouping replaces."""
        banks = self.env['res.bank'].create([{'name': 'Tour bank %s' % i} for i in range(3)])
        recycle_model = self.env['data_recycle.model'].create({
            'name': 'Tour banks',
            'res_model_id': self.env['ir.model']._get('res.bank').id,
            'recycle_action': 'archive',
            'domain': "[('name', 'like', 'Tour bank')]",
        })
        recycle_model._recycle_records()
        self.assertEqual(len(recycle_model.recycle_record_ids), 3)

        self.start_tour('/odoo/field-recycle', 'data_recycle_validate_grouped', login='admin')

        self.assertFalse(recycle_model.recycle_record_ids)
        self.assertFalse(any(bank.active for bank in banks))

    def test_the_unfiltered_warning_tracks_the_filter(self):
        """`invisible="time_field_id or (domain and domain != '[]')"` -- both branches."""
        bank_model = self.env['ir.model']._get('res.bank')
        unfiltered = self.env['data_recycle.model'].create({
            'name': 'No filter at all',
            'res_model_id': bank_model.id,
            'recycle_action': 'archive',
        })
        self.assertEqual(unfiltered.domain, '[]', "this is the value the alert compares against")
        filtered = self.env['data_recycle.model'].create({
            'name': 'With a filter',
            'res_model_id': bank_model.id,
            'recycle_action': 'archive',
            'domain': "[('name', 'like', 'x')]",
        })
        by_time = self.env['data_recycle.model'].create({
            'name': 'With a time field',
            'res_model_id': bank_model.id,
            'recycle_action': 'archive',
            'time_field_id': self.env['ir.model.fields'].search(
                [('name', '=', 'create_date'), ('model_id', '=', bank_model.id)], limit=1).id,
        })

        form = '/odoo/action-data_recycle.action_data_recycle_config/%s'
        self.start_tour(form % unfiltered.id, 'data_recycle_unfiltered_warning', login='admin')
        self.start_tour(form % filtered.id, 'data_recycle_filtered_no_warning', login='admin')
        self.start_tour(form % by_time.id, 'data_recycle_filtered_no_warning', login='admin')
