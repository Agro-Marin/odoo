/** @odoo-module native */
// Side-effect index: every Record subclass in ``core/common/`` so that
// ``modelRegistry`` is populated before ``makeStore()`` iterates over it.
//
// ``Store`` (``store_service.js``) declares fields whose ``targetModel``
// is a string identifier (``fields.One("res.partner")`` and similar).
// Those strings are invisible to esbuild, so without this index every
// satellite bundle that pulls ``store_service.js`` transitively (e.g.
// ``web.assets_tests`` via mail tours) registers the ``mail.store``
// service against an incomplete model registry, and service startup on
// the public frontend fails with ``Error: No target model X exists``.
//
// Keep this list aligned with ``mail/static/src/core/common/*_model.js``.
// A missing entry resurfaces as the same crash, pointing at the new
// model — no silent failure mode.
import "./activity_model.js";
import "./attachment_model.js";
import "./canned_response_model.js";
import "./chat_hub_model.js";
import "./chat_window_model.js";
import "./composer_model.js";
import "./country_model.js";
import "./data_response_model.js";
import "./discuss_call_history_model.js";
import "./failure_model.js";
import "./follower_model.js";
import "./link_preview_model.js";
import "./mail_activity_type_model.js";
import "./mail_guest_model.js";
import "./mail_message_subtype_model.js";
import "./mail_template_model.js";
import "./message_link_preview_model.js";
import "./message_model.js";
import "./message_reactions_model.js";
import "./notification_model.js";
import "./res_company_model.js";
import "./res_groups_model.js";
import "./res_groups_privilege_model.js";
import "./res_lang_model.js";
import "./res_partner_model.js";
import "./res_role_model.js";
import "./res_users_model.js";
import "./settings_model.js";
import "./thread_model.js";
import "./volume_model.js";
