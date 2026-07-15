/* eslint-disable -- generated file; the body must stay strict JSON (see below)
 * and prettier's trailing commas would break the python json.loads parse. */
/* Store serialization contract — DO NOT EDIT BY HAND.
 *
 * Field-name sets per (scenario, Store model), shared by:
 * - python: mail/tests/test_mock_server_contract.py (real controllers)
 * - js: mail/static/tests/mock_server/contract.test.js (hoot mock server)
 *
 * Regenerate (after an intentional Store protocol change) with:
 *   MAIL_STORE_CONTRACT_REGEN=1 odoo-bin -d <bare mail db> \
 *       --test-tags mail_store_contract --stop-after-init
 * (the db must have only mail's dependency closure installed), then re-run
 * both the python tag and the hoot suite `@mail/mock_server/contract`
 * before committing.
 *
 * The body between the braces must remain strict JSON (the python test
 * parses it with json.loads); only this comment may precede it.
 */
export default {
    "gated_models": [
        "DataResponse",
        "MessageReactions",
        "Store",
        "discuss.channel",
        "discuss.channel.member",
        "ir.attachment",
        "mail.followers",
        "mail.message",
        "mail.thread",
        "res.partner"
    ],
    "scenarios": {
        "channel_members": {
            "discuss.channel": [
                "id",
                "member_count"
            ],
            "discuss.channel.member": [
                "channel_id",
                "create_date",
                "fetched_message_id",
                "id",
                "last_seen_dt",
                "partner_id",
                "seen_message_id"
            ],
            "res.partner": [
                "active",
                "avatar_128_access_token",
                "email",
                "id",
                "im_status",
                "im_status_access_token",
                "is_company",
                "main_user_id",
                "mention_token",
                "name",
                "write_date"
            ]
        },
        "channel_messages": {
            "MessageReactions": [
                "content",
                "count",
                "guests",
                "message",
                "partners",
                "sequence"
            ],
            "ir.attachment": [
                "checksum",
                "create_date",
                "file_size",
                "has_thumbnail",
                "id",
                "mimetype",
                "name",
                "raw_access_token",
                "res_model",
                "res_name",
                "thread",
                "thumbnail_access_token",
                "type",
                "url",
                "voice_ids"
            ],
            "mail.message": [
                "attachment_ids",
                "author_guest_id",
                "author_id",
                "body",
                "create_date",
                "date",
                "default_subject",
                "email_from",
                "id",
                "incoming_email_cc",
                "incoming_email_to",
                "message_link_preview_ids",
                "message_type",
                "model",
                "needaction",
                "notification_ids",
                "parent_id",
                "partner_ids",
                "pinned_at",
                "reactions",
                "record_name",
                "res_id",
                "scheduledDatetime",
                "starred",
                "subject",
                "subtype_id",
                "thread",
                "trackingValues",
                "write_date"
            ],
            "mail.thread": [
                "display_name",
                "has_mail_thread",
                "id",
                "model",
                "module_icon"
            ],
            "res.partner": [
                "avatar_128_access_token",
                "id",
                "is_company",
                "main_user_id",
                "name",
                "write_date"
            ]
        },
        "channels_as_member": {
            "MessageReactions": [
                "content",
                "count",
                "guests",
                "message",
                "partners",
                "sequence"
            ],
            "discuss.channel": [
                "avatar_cache_key",
                "channel_type",
                "create_uid",
                "default_display_mode",
                "description",
                "fetchChannelInfoState",
                "from_message_id",
                "group_ids",
                "group_public_id",
                "id",
                "invited_member_ids",
                "is_editable",
                "last_interest_dt",
                "member_count",
                "message_needaction_counter",
                "message_needaction_counter_bus_id",
                "name",
                "parent_channel_id",
                "rtc_session_ids",
                "uuid"
            ],
            "discuss.channel.member": [
                "channel_id",
                "create_date",
                "custom_channel_name",
                "custom_notifications",
                "fetched_message_id",
                "id",
                "last_interest_dt",
                "last_seen_dt",
                "message_unread_counter",
                "message_unread_counter_bus_id",
                "mute_until_dt",
                "new_message_separator",
                "partner_id",
                "rtc_inviting_session_id",
                "seen_message_id",
                "unpin_dt"
            ],
            "mail.message": [
                "attachment_ids",
                "author_guest_id",
                "author_id",
                "body",
                "create_date",
                "date",
                "default_subject",
                "email_from",
                "id",
                "incoming_email_cc",
                "incoming_email_to",
                "message_link_preview_ids",
                "message_type",
                "model",
                "needaction",
                "notification_ids",
                "parent_id",
                "partner_ids",
                "pinned_at",
                "reactions",
                "record_name",
                "res_id",
                "scheduledDatetime",
                "starred",
                "subject",
                "subtype_id",
                "thread",
                "trackingValues",
                "write_date"
            ],
            "mail.thread": [
                "display_name",
                "has_mail_thread",
                "id",
                "model",
                "module_icon"
            ],
            "res.partner": [
                "active",
                "avatar_128_access_token",
                "email",
                "id",
                "im_status",
                "im_status_access_token",
                "is_company",
                "main_user_id",
                "mention_token",
                "name",
                "write_date"
            ]
        },
        "chatter_thread": {
            "ir.attachment": [
                "checksum",
                "create_date",
                "file_size",
                "has_thumbnail",
                "id",
                "mimetype",
                "name",
                "raw_access_token",
                "res_model",
                "res_name",
                "thread",
                "thumbnail_access_token",
                "type",
                "url",
                "voice_ids"
            ],
            "mail.followers": [
                "display_name",
                "email",
                "id",
                "is_active",
                "name",
                "partner_id",
                "thread"
            ],
            "mail.thread": [
                "areAttachmentsLoaded",
                "attachments",
                "canPostOnReadonly",
                "followers",
                "followersCount",
                "hasReadAccess",
                "hasWriteAccess",
                "id",
                "isLoadingAttachments",
                "model",
                "recipients",
                "recipientsCount",
                "selfFollower"
            ],
            "res.partner": [
                "active",
                "avatar_128_access_token",
                "email",
                "id",
                "im_status",
                "im_status_access_token",
                "is_company",
                "main_user_id",
                "name",
                "write_date"
            ]
        },
        "get_or_create_chat": {
            "DataResponse": [
                "_resolve",
                "channel",
                "id"
            ],
            "discuss.channel": [
                "channel_type",
                "create_uid",
                "default_display_mode",
                "fetchChannelInfoState",
                "id",
                "invited_member_ids",
                "is_editable",
                "last_interest_dt",
                "member_count",
                "message_needaction_counter",
                "message_needaction_counter_bus_id",
                "name",
                "rtc_session_ids",
                "uuid"
            ],
            "discuss.channel.member": [
                "channel_id",
                "create_date",
                "custom_channel_name",
                "custom_notifications",
                "fetched_message_id",
                "id",
                "last_interest_dt",
                "last_seen_dt",
                "message_unread_counter",
                "message_unread_counter_bus_id",
                "mute_until_dt",
                "new_message_separator",
                "partner_id",
                "rtc_inviting_session_id",
                "seen_message_id",
                "unpin_dt"
            ],
            "res.partner": [
                "active",
                "avatar_128_access_token",
                "email",
                "id",
                "im_status",
                "im_status_access_token",
                "is_company",
                "main_user_id",
                "mention_token",
                "name",
                "write_date"
            ]
        },
        "init_messaging": {
            "Store": [
                "inbox",
                "initChannelsUnreadCounter",
                "starred"
            ]
        },
        "message_post": {
            "mail.message": [
                "attachment_ids",
                "author_guest_id",
                "author_id",
                "body",
                "create_date",
                "date",
                "default_subject",
                "email_from",
                "id",
                "incoming_email_cc",
                "incoming_email_to",
                "message_link_preview_ids",
                "message_type",
                "model",
                "needaction",
                "notification_ids",
                "parent_id",
                "partner_ids",
                "pinned_at",
                "reactions",
                "record_name",
                "res_id",
                "scheduledDatetime",
                "starred",
                "subject",
                "subtype_id",
                "thread",
                "trackingValues",
                "write_date"
            ],
            "mail.thread": [
                "display_name",
                "has_mail_thread",
                "id",
                "model",
                "module_icon"
            ],
            "res.partner": [
                "avatar_128_access_token",
                "id",
                "is_company",
                "main_user_id",
                "name",
                "write_date"
            ]
        }
    }
};
