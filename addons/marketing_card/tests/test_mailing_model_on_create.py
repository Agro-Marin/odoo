from odoo.tests import TransactionCase


class TestMailingModelOnCreate(TransactionCase):
    def test_a_card_campaign_mailing_targets_the_campaign_model(self):
        campaign = self.env["card.campaign"].create(
            {
                "name": "Campaign",
                "preview_record_ref": f"res.partner,{self.env.user.partner_id.id}",
            }
        )

        mailing = self.env["mailing.mailing"].create(
            {"subject": "Cards", "card_campaign_id": campaign.id}
        )

        self.assertEqual(mailing.mailing_model_id.model, "res.partner")

    def test_a_plain_mailing_targets_mailing_lists(self):
        mailing = self.env["mailing.mailing"].create({"subject": "News"})

        self.assertEqual(
            mailing.mailing_model_id, self.env.ref("mass_mailing.model_mailing_list")
        )
