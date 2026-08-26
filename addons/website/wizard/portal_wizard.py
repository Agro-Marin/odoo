from odoo import models


class PortalWizardUser(models.TransientModel):
    _inherit = "portal.wizard.user"

    def _get_similar_users_domain(self, portal_users_with_email):
        similar_user_domain = super()._get_similar_users_domain(portal_users_with_email)
        portal_user_website_ids = []
        for portal_user in portal_users_with_email:
            portal_user_website_id = portal_user.partner_id.website_id.id
            if (
                portal_user_website_id
                and portal_user_website_id not in portal_user_website_ids
            ):
                portal_user_website_ids.append(portal_user_website_id)
            elif not portal_user_website_id and False not in portal_user_website_ids:
                portal_user_website_ids.extend(
                    [False, self.env["website"].get_current_website().id]
                )
        similar_user_domain.append(("website_id", "in", portal_user_website_ids))
        return similar_user_domain

    def _get_fields_similar_users(self):
        similar_user_fields = super()._get_fields_similar_users()
        similar_user_fields.append("website_id")
        return similar_user_fields

    def _is_portal_similar_than_user(self, user, portal_user):
        if super()._is_portal_similar_than_user(user, portal_user):
            if portal_user.partner_id.website_id:
                return (
                    user["website_id"]
                    and user["website_id"][0] == portal_user.partner_id.website_id.id
                )
            return (
                not user["website_id"]
                or user["website_id"][0] == self.env["website"].get_current_website().id
            )
        return False
