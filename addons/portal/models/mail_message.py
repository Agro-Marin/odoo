from odoo import models
from odoo.http import request
from odoo.tools import format_datetime, groupby


class MailMessage(models.Model):
    """Portal-specific extensions to mail.message (visibility, avatar URLs, attachment tokens)."""

    _inherit = "mail.message"

    # Avatar resolution served to portal chatter clients. Kept low because the
    # rendered avatar is rendered at ~32px CSS; bumping this requires a matching
    # change in the chatter SCSS to actually display the higher resolution.
    _PORTAL_AVATAR_SIZE = "50x50"

    def _compute_is_current_user_or_guest_author(self):
        """Mark portal-authored messages as 'current user' when the request was
        validated via HMAC hash+pid or access token.

        The ``portal_data`` context key is set by portal controllers after
        :func:`portal.utils.get_portal_partner` has cryptographically validated
        the requester. The ``isinstance`` checks below are defense-in-depth.
        """
        super()._compute_is_current_user_or_guest_author()
        portal_data = self.env.context.get("portal_data", {})
        portal_partner = portal_data.get("portal_partner")
        portal_thread = portal_data.get("portal_thread")
        if (
            not portal_partner
            or not portal_thread
            or not isinstance(portal_partner, self.pool["res.partner"])
            or not isinstance(portal_thread, self.pool["mail.thread"])
        ):
            return
        for message in self:
            if (
                message.author_id == portal_partner
                and message.model == portal_thread._name
                and message.res_id == portal_thread.id
            ):
                message.is_current_user_or_guest_author = True

    def portal_message_format(self, options=None):
        """Simpler and portal-oriented version of 'message_format'. Purpose
        is to prepare, organize and format values required by frontend widget
        (frontend Chatter).

        This public API asks for read access on messages before doing the
        actual computation in the private implementation.

        :param dict options: options, used notably for inheritance and adding
          specific fields or properties to compute;

        :returns: list of dict, one per message in self. Each dict contains
          values for either fields, either properties derived from fields.
        :rtype: list[dict]
        """
        self.check_access("read")
        return self._portal_message_format(
            self._portal_get_default_format_properties_names(options=options),
            options=options,
        )

    def _portal_get_default_format_properties_names(self, options=None):
        """Fields and values to compute for portal format.

        :param dict options: options, used notably for inheritance and adding
          specific fields or properties to compute;

        :returns: fields or properties derived from fields
        :rtype: set
        """
        return {
            "attachment_ids",
            "author_avatar_url",
            "author_id",
            "author_guest_id",
            "body",
            "date",
            "id",
            "is_internal",
            "is_message_subtype_note",
            "message_type",
            "model",
            "published_date_str",
            "res_id",
            "starred",
            "subtype_id",
        }

    def _portal_format_avatar_url(self, message, options):
        """Build the avatar URL appropriate to the caller's auth method.

        :param message: single ``mail.message`` record
        :param dict options: caller-supplied options carrying ``token`` /
                             ``hash`` + ``pid`` when the request was authenticated
                             against a thread access token or HMAC pair
        :return: URL serving the author avatar at 50x50, with auth params
        :rtype: str
        """
        size = self._PORTAL_AVATAR_SIZE
        if options and options.get("token"):
            return f"/mail/avatar/mail.message/{message.id}/author_avatar/{size}?access_token={options['token']}"
        if options and options.get("hash") and options.get("pid"):
            return f"/mail/avatar/mail.message/{message.id}/author_avatar/{size}?_hash={options['hash']}&pid={options['pid']}"
        return f"/web/image/mail.message/{message.id}/author_avatar/{size}"

    def _portal_message_format(self, properties_names, options=None):
        """Format messages for the portal frontend; assumes read access checked upstream.

        :param set properties_names: fields or properties derived from fields
                                     for which we are going to compute values
        :param dict options: caller-supplied options (token, hash, pid, ...)
        :return: list of dict, one per message in ``self``
        :rtype: list[dict]
        """
        # When attachments are requested, fetch them via sudo: read access on
        # the parent message implies read access on its attachments, but
        # ir.attachment ACL would otherwise refuse the portal user.
        message_to_attachments = {}
        if "attachment_ids" in properties_names:
            properties_names.remove("attachment_ids")
            attachments_sudo = self.sudo().attachment_ids
            related_attachments = {
                att_read_values["id"]: att_read_values
                for att_read_values in attachments_sudo.read(
                    [
                        "checksum",
                        "has_thumbnail",
                        "id",
                        "mimetype",
                        "name",
                        "res_id",
                        "res_model",
                    ]
                )
            }
            message_to_attachments = {
                message.id: [
                    message._portal_message_format_attachments(
                        related_attachments[att_id]
                    )
                    for att_id in message.attachment_ids.ids
                ]
                for message in self.sudo()
            }

        fnames = {
            property_name
            for property_name in properties_names
            if property_name in self._fields
        }
        vals_list = self._read_format(fnames)

        note_id = self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_note")
        for message, values in zip(self, vals_list, strict=True):
            values["body"] = ["markup", values["body"]]
            if message_to_attachments:
                values["attachment_ids"] = message_to_attachments.get(message.id, {})
            if "author_avatar_url" in properties_names:
                values["author_avatar_url"] = self._portal_format_avatar_url(
                    message, options
                )
            if "is_message_subtype_note" in properties_names:
                # ``subtype_id`` is read in classic format: ``[id, name]`` or False.
                subtype = values.get("subtype_id")
                values["is_message_subtype_note"] = (
                    bool(subtype) and subtype[0] == note_id
                )
            if "published_date_str" in properties_names:
                values["published_date_str"] = (
                    format_datetime(self.env, values["date"])
                    if values.get("date")
                    else ""
                )
            reaction_groups = []
            for content, reactions_iter in groupby(
                message.sudo().reaction_ids, lambda r: r.content
            ):
                reaction_records = self.env["mail.message.reaction"].union(
                    *reactions_iter
                )
                reaction_groups.append(
                    {
                        "content": content,
                        "count": len(reaction_records),
                        # sudo: mail.guest - reading guest names of reactions on accessible message is allowed
                        "guests": [
                            {"id": guest.id, "name": guest.name}
                            for guest in reaction_records.guest_id
                        ],
                        "message": message.id,
                        # sudo: res.partner - reading partners of reactions on accessible message is allowed
                        "partners": [
                            {"id": partner.id, "name": partner.name}
                            for partner in reaction_records.partner_id.sudo()
                        ],
                    },
                )
            values.update(
                {
                    "reactions": reaction_groups,
                    "author_id": {
                        "id": message.author_id.id,
                        "name": message.author_id.name,
                    }
                    if message.author_id
                    else False,
                    "thread": {
                        # The "add reaction" button must be hidden on messages
                        # whose model does not inherit from mail.thread.
                        "has_mail_thread": isinstance(
                            self.env[values["model"]], self.pool["mail.thread"]
                        ),
                        "id": values["res_id"],
                        "model": values["model"],
                    },
                }
            )
        # Linked messages (e.g. a message link posted in the chatter) carry the
        # referenced thread's display_name so the frontend can rebuild the
        # prettified link after a refresh.
        linked_messages = self.linked_message_ids - self
        linked_messages_vals_list = linked_messages._read_format(
            {"id", "model", "res_id"}
        )
        record_by_linked_message = linked_messages._record_by_message()
        for message, values in zip(
            linked_messages, linked_messages_vals_list, strict=True
        ):
            record = record_by_linked_message.get(message)
            # sudo: mail.thread - reading display_name of accessed thread is acceptable
            values["thread"] = {
                "display_name": record.sudo().display_name if record else False
            }
        vals_list.extend(linked_messages_vals_list)
        return vals_list

    def _portal_message_format_attachments(self, attachment_values):
        """From ``attachment_values`` build the dict consumed by the frontend chatter.

        :param dict attachment_values: values read from ``ir.attachment``
        :return: same dict augmented with filename, possibly remapped mimetype,
                 and raw/ownership access tokens
        :rtype: dict
        """
        self.ensure_one()
        # Safari plays video MIME types inline ignoring Content-Disposition:
        # attachment, so serve them as octet-stream to force the browser
        # download dialog.
        safari = (
            request
            and request.httprequest.user_agent
            and request.httprequest.user_agent.browser == "safari"
        )
        attachment_values["filename"] = attachment_values["name"]
        attachment_values["mimetype"] = (
            "application/octet-stream"
            if safari and "video" in (attachment_values["mimetype"] or "")
            else attachment_values["mimetype"]
        )
        attachment = self.env["ir.attachment"].browse(attachment_values["id"])
        attachment_values["raw_access_token"] = attachment._get_raw_access_token()
        attachment_values["thumbnail_access_token"] = attachment._get_thumbnail_token()
        if self.is_current_user_or_guest_author:
            attachment_values["ownership_token"] = attachment._get_ownership_token()
        return attachment_values
