from . import common


class TestResPartner(common.SlidesCase):
    def test_slide_channel_count_updates_within_transaction(self):
        partner = self.env["res.partner"].create({"name": "New Enrollee"})
        self.assertEqual(partner.slide_channel_count, 0)

        self.channel._action_add_members(partner)

        self.assertEqual(partner.slide_channel_count, 1)
        self.assertIn(self.channel, partner.slide_channel_ids)

    def test_search_slide_channel_ids_finds_members(self):
        partner = self.env["res.partner"].create({"name": "Searchable Enrollee"})
        self.channel._action_add_members(partner)

        found = self.env["res.partner"].search(
            [("slide_channel_ids", "in", self.channel.ids)]
        )
        self.assertIn(partner, found)

        not_member = self.env["res.partner"].create({"name": "Non Member"})
        not_found = self.env["res.partner"].search(
            [("slide_channel_ids", "in", self.channel.ids)]
        )
        self.assertNotIn(not_member, not_found)
