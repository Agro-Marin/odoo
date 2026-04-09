# Mail Module — Model Reference

## Quick Lookup Index

| Model | File | Type | Description |
|-------|------|------|-------------|
| `mail.thread` | `models/mail_thread.py` | Abstract | Core chatter mixin |
| `mail.activity.mixin` | `models/mail_activity_mixin.py` | Abstract | Activity support mixin |
| `mail.alias.mixin` | `models/mail_alias_mixin.py` | Abstract | Required email alias mixin |
| `mail.alias.mixin.optional` | `models/mail_alias_mixin_optional.py` | Abstract | Optional email alias mixin |
| `mail.render.mixin` | `models/mail_render_mixin.py` | Abstract | QWeb template rendering |
| `mail.composer.mixin` | `models/mail_composer_mixin.py` | Abstract | Composition functionality |
| `mail.thread.blacklist` | `models/mail_thread_blacklist.py` | Abstract | Blacklist support |
| `mail.thread.cc` | `models/mail_thread_cc.py` | Abstract | CC/BCC support |
| `mail.thread.main.attachment` | `models/mail_thread_main_attachment.py` | Abstract | Primary attachment |
| `mail.tracking.duration.mixin` | `models/mail_tracking_duration_mixin.py` | Abstract | Time-in-stage tracking |
| `template.reset.mixin` | `models/template_reset_mixin.py` | Abstract | Template reset utility |
| `bus.listener.mixin` | `models/discuss/bus_listener_mixin.py` | Abstract | Bus event listening |
| `mail.message` | `models/mail_message.py` | Model | Core message record |
| `mail.mail` | `models/mail_mail.py` | Model | Outgoing email queue |
| `mail.followers` | `models/mail_followers.py` | Model | Document subscriptions |
| `mail.notification` | `models/mail_notification.py` | Model | Per-recipient notifications |
| `mail.activity` | `models/mail_activity.py` | Model | Scheduled activity/task |
| `mail.activity.type` | `models/mail_activity_type.py` | Model | Activity type catalog |
| `mail.activity.plan` | `models/mail_activity_plan.py` | Model | Activity workflow |
| `mail.activity.plan.template` | `models/mail_activity_plan_template.py` | Model | Plan template line |
| `mail.template` | `models/mail_template.py` | Model | Email template |
| `mail.alias` | `models/mail_alias.py` | Model | Email alias |
| `mail.alias.domain` | `models/mail_alias_domain.py` | Model | Email domain config |
| `mail.message.subtype` | `models/mail_message_subtype.py` | Model | Message classification |
| `mail.message.reaction` | `models/mail_message_reaction.py` | Model | Emoji reactions |
| `mail.message.schedule` | `models/mail_message_schedule.py` | Model | Message scheduling |
| `mail.message.translation` | `models/mail_message_translation.py` | Model | Message translations |
| `message.mail.link.preview` | `models/mail_message_link_preview.py` | Model | Link preview relation |
| `mail.link.preview` | `models/mail_link_preview.py` | Model | Link preview cache |
| `mail.tracking.value` | `models/mail_tracking_value.py` | Model | Field change tracking |
| `mail.blacklist` | `models/mail_blacklist.py` | Model | Blocked email addresses |
| `mail.canned.response` | `models/mail_canned_response.py` | Model | Pre-written templates |
| `mail.gateway.allowed` | `models/mail_gateway_allowed.py` | Model | Allowed gateway addresses |
| `mail.scheduled.message` | `models/mail_scheduled_message.py` | Model | Scheduled outgoing message |
| `mail.presence` | `models/mail_presence.py` | Model | Online/away status |
| `mail.push` | `models/mail_push.py` | Model | Push notification queue |
| `mail.push.device` | `models/mail_push_device.py` | Model | Mobile device registration |
| `mail.ice.server` | `models/mail_ice_server.py` | Model | ICE server config (WebRTC) |
| `ir.mail_server` | `models/ir_mail_server.py` | Patch | SMTP server config |
| `fetchmail.server` | `models/fetchmail.py` | Model | POP/IMAP server config |
| `discuss.channel` | `models/discuss/discuss_channel.py` | Model | Chat channel |
| `discuss.channel.member` | `models/discuss/discuss_channel_member.py` | Model | Channel membership |
| `discuss.channel.rtc.session` | `models/discuss/discuss_channel_rtc_session.py` | Model | RTC session |
| `discuss.call.history` | `models/discuss/discuss_call_history.py` | Model | Call history |
| `discuss.gif.favorite` | `models/discuss/discuss_gif_favorite.py` | Model | Favorite GIFs |
| `discuss.voice.metadata` | `models/discuss/discuss_voice_metadata.py` | Model | Voice message metadata |
| `mail.guest` | `models/discuss/mail_guest.py` | Model | Anonymous guest user |
| `res.role` | `models/res_role.py` | Model | Role-based permissions |
| `res.users.settings` | `models/res_users_settings.py` | Patch | User discuss settings |
| `res.users.settings.volumes` | `models/res_users_settings_volumes.py` | Model | Volume controls |
| `mail.compose.message` | `wizard/mail_compose_message.py` | Transient | Email composition wizard |
| `mail.activity.schedule` | `wizard/mail_activity_schedule.py` | Transient | Activity scheduling wizard |
| `mail.followers.edit` | `wizard/mail_followers_edit.py` | Transient | Follower management wizard |

---

## Abstract Mixins

### mail.thread

**File:** `models/mail_thread.py` (~6,689 lines)
**Description:** Email Thread — the core mixin enabling document chatter

**Class Attributes:**

| Attribute | Default | Purpose |
|-----------|---------|---------|
| `_mail_flat_thread` | `True` | Links orphan messages to first message |
| `_mail_thread_customer` | `False` | Auto-subscribe customer in post recipients |
| `_mail_post_access` | `"write"` | Required access level to post |
| `_primary_email` | `"email"` | Field name for primary email |

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `message_is_follower` | Boolean (computed) | Current user follows this record |
| `message_follower_ids` | One2many → mail.followers | Document subscribers |
| `message_partner_ids` | Many2many → res.partner (computed) | Follower partners |
| `message_ids` | One2many → mail.message | Chatter messages (excludes user_notification) |
| `has_message` | Boolean (computed) | Record has any messages |
| `message_needaction` | Boolean (computed) | Has unread notifications |
| `message_needaction_counter` | Integer (computed) | Unread notification count |
| `message_has_error` | Boolean (computed) | Has failed notifications |
| `message_has_error_counter` | Integer (computed) | Failed notification count |
| `message_attachment_count` | Integer (computed) | Attachment count |

**Key Methods — Message Posting:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `message_post` | `(*, body, subject, message_type, email_from, author_id, parent_id, subtype_xmlid, subtype_id, partner_ids, attachments, attachment_ids, body_is_html, **kwargs)` | Post message on thread (main API) |
| `message_post_with_source` | `(source, /, *, body_is_html, subtype_xmlid, **kwargs)` | Post from mail.template or ir.ui.view |
| `_message_log` | `(*, body, author_id, tracking_value_ids)` | Log message without subtype (no notification) |
| `_message_log_batch` | `(bodies)` | Batch log messages |
| `_message_create` | `(values_list)` | Low-level mail.message creation |
| `_message_compute_author` | `(author_id=None, email_from=None) → (int, str)` | Resolve author/email coherence |

**Key Methods — Notification:**

| Method | Description |
|--------|-------------|
| `_notify_thread(message, msg_vals, **kwargs)` | Main dispatch: inbox + email + web_push + OOO |
| `_notify_thread_by_inbox(message, recipients_data, ...)` | Send inbox notifications via bus |
| `_notify_thread_by_email(message, recipients_data, ...)` | Send email via mail.mail queue |
| `_notify_thread_by_web_push(message, recipients_data, ...)` | Send web push notifications |
| `_notify_get_recipients(message, msg_vals, **kwargs)` | Compute all recipients from followers/subtypes |
| `_notify_get_recipients_groups(message, ...)` | Classify recipients into groups (user, portal, etc.) |

**Key Methods — Tracking:**

| Method | Description |
|--------|-------------|
| `_track_prepare(fields_iter)` | Prepare tracking for commit (precommit hook) |
| `_track_finalize()` | Generate tracking messages after commit |
| `_track_set_author(author)` | Override tracking message author |
| `_track_set_log_message(message)` | Add body to tracking message |
| `_message_track(fields_iter, initial_values_dict)` | Track field changes |
| `_track_template(changes)` | Define templates for tracking (override point) |
| `_track_subtype(initial_values)` | Return subtype for changes (override point) |

**Key Methods — Mail Gateway:**

| Method | Description |
|--------|-------------|
| `message_process(message, custom_values, save_original)` | Main gateway entry point (parse + route) |
| `message_route(message, message_dict, model, thread_id, custom_values)` | Route incoming email to model/thread |
| `message_parse(message, save_original)` | Parse RFC2822 email to message_dict |
| `message_new(msg_dict, custom_values)` | Create record from incoming email |
| `message_update(msg_dict, update_vals)` | Update record from incoming email |

**Key Methods — Followers:**

| Method | Description |
|--------|-------------|
| `message_subscribe(partner_ids, subtype_ids)` | Subscribe partners to record |
| `message_unsubscribe(partner_ids)` | Unsubscribe partners |
| `message_get_followers(after, limit, filter_recipients)` | Paginated follower list |
| `_message_auto_subscribe(updated_values, policy)` | Auto-subscribe on relational changes |

**Key Methods — Frontend Store:**

| Method | Description |
|--------|-------------|
| `_thread_to_store(store, fields, *, request_list)` | Serialize thread data for frontend |
| `_get_mail_thread_data_attachments()` | Get thread attachments |
| `_get_thread_with_access(thread_id, *, mode)` | Get thread with access check |

---

### mail.activity.mixin

**File:** `models/mail_activity_mixin.py`
**Description:** Adds activity/task support to any model

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `activity_ids` | One2many → mail.activity | Related activities |
| `activity_state` | Selection (computed) | overdue / today / planned |
| `activity_user_id` | Many2one → res.users (computed) | Responsible user |
| `activity_type_id` | Many2one → mail.activity.type (related) | Activity type |
| `activity_date_deadline` | Date (computed) | Next deadline |
| `my_activity_date_deadline` | Date (computed) | Current user's deadline |
| `activity_summary` | Char (related) | Activity summary |
| `activity_exception_decoration` | Selection (computed) | Exception display type |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `activity_schedule(act_type_xmlid, date_deadline, summary, note, **act_values)` | Create activity |
| `activity_reschedule(act_type_xmlids, user_id, date_deadline, new_user_id)` | Reschedule activities |
| `activity_feedback(act_type_xmlids, user_id, feedback, attachment_ids)` | Mark activities done |
| `activity_unlink(act_type_xmlids, user_id)` | Delete activities |
| `activity_search(act_type_xmlids, user_id, additional_domain)` | Search activities |

---

### mail.render.mixin

**File:** `models/mail_render_mixin.py`
**Description:** QWeb template rendering for email bodies

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `lang` | Char | Rendering language (ISO code) |
| `render_model` | Char (computed) | Target model for rendering |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `_render_field(field, res_ids, **kwargs)` | Render a field value with QWeb |
| `_render_lang(res_ids, engine)` | Get language for rendering |
| `_build_expression(field_name, sub_field_name, null_value)` | Build placeholder expression |

---

### mail.composer.mixin

**File:** `models/mail_composer_mixin.py`
**Inherits:** `mail.render.mixin`

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `subject` | Char (computed, stored) | Email subject |
| `body` | Html (computed, stored, qweb) | Email body |
| `body_has_template_value` | Boolean (computed) | Body unchanged from template |
| `template_id` | Many2one → mail.template | Selected template |
| `can_edit_body` | Boolean (computed) | User can edit body |

---

## Core Models

### mail.message

**File:** `models/mail_message.py`
**Inherits:** `bus.listener.mixin`

**Key Fields:**

| Field | Type | Key Attributes | Description |
|-------|------|----------------|-------------|
| `subject` | Char | | Message subject |
| `date` | Datetime | default: now | Message date |
| `body` | Html | default: "" | Rich-text body |
| `preview` | Char | computed | Text-only preview |
| `model` | Char | | Related document model |
| `res_id` | Many2oneReference | | Related document ID |
| `message_type` | Selection | | email, comment, email_outgoing, notification, auto_comment, out_of_office, user_notification |
| `subtype_id` | Many2one → mail.message.subtype | | Message subtype |
| `is_internal` | Boolean | | Hidden from portal |
| `email_from` | Char | | Sender email |
| `author_id` | Many2one → res.partner | | Message author |
| `author_guest_id` | Many2one → mail.guest | | Guest author |
| `partner_ids` | Many2many → res.partner | | Recipients |
| `notification_ids` | One2many → mail.notification | | Notifications |
| `starred_partner_ids` | Many2many → res.partner | | Starred by |
| `tracking_value_ids` | One2many → mail.tracking.value | | Field changes |
| `parent_id` | Many2one → mail.message | | Parent message |
| `child_ids` | One2many → mail.message | | Replies |
| `attachment_ids` | Many2many → ir.attachment | | Attachments |
| `reaction_ids` | One2many → mail.message.reaction | | Emoji reactions |
| `message_id` | Char | | RFC2822 Message-ID |
| `reply_to` | Char | | RFC2822 Reply-To |
| `mail_server_id` | Many2one → ir.mail_server | | Outgoing server |
| `pinned_at` | Datetime | | When pinned |
| `needaction` | Boolean | computed | Needs user action |
| `starred` | Boolean | computed | Current user starred |
| `has_error` | Boolean | computed | Has send errors |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `mark_all_as_read(domain)` | Mark messages as read |
| `set_message_done()` | Mark message as done |
| `toggle_message_starred()` | Toggle star status |

---

### mail.mail

**File:** `models/mail_mail.py`
**Inherits:** `mail.message` (via `_inherits`)

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `mail_message_id` | Many2one → mail.message | Related message (required) |
| `body_html` | Text | Rich-text email body |
| `email_to` | Text | Recipient emails (comma-separated) |
| `email_cc` | Char | CC recipients |
| `recipient_ids` | Many2many → res.partner | Partner recipients |
| `state` | Selection | outgoing, sent, received, exception, cancel |
| `failure_type` | Selection | unknown, mail_spam, mail_email_invalid, etc. |
| `failure_reason` | Text | Detailed failure reason |
| `auto_delete` | Boolean | Auto-delete after sending |
| `scheduled_date` | Datetime | Scheduled send time |
| `fetchmail_server_id` | Many2one → fetchmail.server | Inbound server |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `send(auto_commit, raise_exception, post_send_callback)` | Send emails via SMTP |
| `process_email_queue(email_ids, batch_size)` | Process outgoing queue (cron) |
| `action_retry()` | Retry failed sends |
| `cancel()` | Cancel outgoing mail |
| `_prepare_outgoing_list()` | Prepare recipient list |

---

### mail.followers

**File:** `models/mail_followers.py`
**_log_access:** False

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `res_model` | Char | Document model (required, indexed) |
| `res_id` | Many2oneReference | Document ID (indexed) |
| `partner_id` | Many2one → res.partner | Follower (required, indexed) |
| `subtype_ids` | Many2many → mail.message.subtype | Subscribed subtypes |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `_get_recipient_data(records, message_type, subtype_id, pids)` | Get recipient details for notification |
| `_insert_followers(res_model, res_ids, partner_ids, subtypes, ...)` | Bulk insert followers |

---

### mail.notification

**File:** `models/mail_notification.py`
**_log_access:** False

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `mail_message_id` | Many2one → mail.message | Related message (required) |
| `res_partner_id` | Many2one → res.partner | Recipient partner |
| `notification_type` | Selection | inbox, email |
| `notification_status` | Selection | ready, process, pending, sent, bounce, exception, canceled |
| `is_read` | Boolean | Whether read |
| `failure_type` | Selection | Error classification |

---

### mail.activity

**File:** `models/mail_activity.py`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `res_model_id` | Many2one → ir.model | Document model |
| `res_model` | Char | Model name (related, stored) |
| `res_id` | Many2oneReference | Document ID |
| `activity_type_id` | Many2one → mail.activity.type | Activity type |
| `summary` | Char | Activity summary |
| `note` | Html | Activity notes |
| `date_deadline` | Date | Due date (required) |
| `date_done` | Date | Completion date (computed, stored) |
| `feedback` | Text | Completion feedback |
| `user_id` | Many2one → res.users | Assigned user |
| `state` | Selection (computed) | overdue, today, planned, done |
| `automated` | Boolean | Is automated activity |
| `attachment_ids` | Many2many → ir.attachment | Attachments |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `action_done(feedback, attachment_ids)` | Mark activity complete |
| `action_feedback(feedback, attachment_ids)` | Add feedback and archive |
| `action_feedback_schedule_next(feedback, attachment_ids)` | Complete and schedule next |

---

### mail.template

**File:** `models/mail_template.py`
**Inherits:** `mail.render.mixin`, `template.reset.mixin`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | Char (translate) | Template name |
| `model_id` | Many2one → ir.model | Applies to model |
| `model` | Char (related, stored, indexed) | Model name |
| `subject` | Char (translate) | Email subject with placeholders |
| `email_from` | Char | Sender with placeholders |
| `body_html` | Html (qweb, translate) | Body with QWeb rendering |
| `attachment_ids` | Many2many → ir.attachment | Static attachments |
| `report_template_ids` | Many2many → ir.actions.report | Dynamic report attachments |
| `email_layout_xmlid` | Char | Email layout template |
| `auto_delete` | Boolean | Auto-delete after send (default: true) |
| `scheduled_date` | Char | Scheduled send expression |
| `template_category` | Selection (computed) | base_template, hidden_template, custom_template |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `send_mail(res_ids, force_send, raise_exception)` | Send templated emails |
| `_generate_template(res_ids, render_results)` | Full template rendering |
| `_generate_template_recipients(res_ids, render_results)` | Resolve recipients |
| `_generate_template_attachments(res_ids, render_results)` | Process attachments |

---

### mail.alias

**File:** `models/mail_alias.py`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `alias_name` | Char | Local-part (left of @) |
| `alias_full_name` | Char (computed, stored, indexed) | Full email address |
| `alias_domain_id` | Many2one → mail.alias.domain | Domain |
| `alias_model_id` | Many2one → ir.model | Target model (required) |
| `alias_defaults` | Text | Default field values (JSON, required) |
| `alias_force_thread_id` | Integer | Force all to one record |
| `alias_contact` | Selection | everyone, partners, followers |
| `alias_status` | Selection (computed, stored) | not_tested, valid, invalid |

---

### mail.tracking.value

**File:** `models/mail_tracking_value.py`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `field_id` | Many2one → ir.model.fields | Tracked field |
| `field_info` | Json | Removed field info |
| `old_value_*` | Integer/Float/Char/Text/Datetime | Old value (by type) |
| `new_value_*` | Integer/Float/Char/Text/Datetime | New value (by type) |
| `currency_id` | Many2one → res.currency | For monetary fields |
| `mail_message_id` | Many2one → mail.message | Related message (required) |

---

## Discuss Models

### discuss.channel

**File:** `models/discuss/discuss_channel.py`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | Char (required) | Channel name |
| `channel_type` | Selection | chat, channel, group |
| `description` | Text | Channel description |
| `channel_member_ids` | One2many → discuss.channel.member | Members |
| `channel_partner_ids` | Many2many (computed/inverse) | Member partners |
| `parent_channel_id` | Many2one → discuss.channel | Parent channel |
| `sub_channel_ids` | One2many → discuss.channel | Sub-channels (threads) |
| `from_message_id` | Many2one → mail.message | Origin message (for sub-channels) |
| `pinned_message_ids` | One2many → mail.message | Pinned messages |
| `rtc_session_ids` | One2many → discuss.channel.rtc.session | Active RTC sessions |
| `uuid` | Char (size=50) | Invitation token |
| `group_public_id` | Many2one → res.groups (computed, stored) | Access control group |
| `group_ids` | Many2many → res.groups | Auto-subscription groups |
| `sfu_channel_uuid` | Char | SFU channel ID |
| `sfu_server_url` | Char | SFU server URL |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `_get_or_create_chat(partners_to)` | Get/create direct message channel |
| `add_members(partner_ids, guest_ids, invite_to_rtc_call, post_joined_message)` | Add members |
| `_action_unfollow()` | Remove current user |
| `set_message_pin(message_id, pinned)` | Pin/unpin message |
| `channel_join()` | Current user joins |
| `channel_rename(name)` | Rename channel |
| `execute_command_help()` | /help command |
| `execute_command_leave()` | /leave command |
| `execute_command_who()` | /who command |
| `get_mention_suggestions(search, limit)` | @mention autocomplete |

---

### discuss.channel.member

**File:** `models/discuss/discuss_channel_member.py`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `partner_id` | Many2one → res.partner | Member partner |
| `guest_id` | Many2one → mail.guest | Member guest |
| `channel_id` | Many2one → discuss.channel | Channel (required) |
| `custom_channel_name` | Char | User-specific channel name |
| `fetched_message_id` | Many2one → mail.message | Last fetched |
| `seen_message_id` | Many2one → mail.message | Last seen |
| `new_message_separator` | Integer | Unread separator position |
| `message_unread_counter` | Integer (computed) | Unread count |
| `custom_notifications` | Selection | all, mentions, no_notif |
| `mute_until_dt` | Datetime | Mute until |
| `is_pinned` | Boolean (computed) | Pinned in sidebar |
| `rtc_inviting_session_id` | Many2one → discuss.channel.rtc.session | Incoming call |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `_rtc_join_call(check_rtc_session_ids)` | Join RTC call |
| `_rtc_leave_call()` | Leave RTC call |
| `_mark_as_read(last_message_id)` | Mark as read |
| `_notify_typing(is_typing)` | Broadcast typing status |

---

### discuss.channel.rtc.session

**File:** `models/discuss/discuss_channel_rtc_session.py`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `channel_member_id` | Many2one → discuss.channel.member | Session member (required) |
| `channel_id` | Many2one (related, stored) | Channel |
| `is_screen_sharing_on` | Boolean | Screen sharing active |
| `is_camera_on` | Boolean | Camera active |
| `is_muted` | Boolean | Microphone muted |
| `is_deaf` | Boolean | Audio disabled |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `_update_and_broadcast(values)` | Update session and broadcast to peers |
| `_notify_peers(notifications)` | Send P2P notifications |
| `_gc_inactive_sessions()` | Cleanup stale sessions (cron) |

---

### mail.guest

**File:** `models/discuss/mail_guest.py`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | Char (required) | Guest name |
| `access_token` | Char (readonly) | UUID access token |
| `country_id` | Many2one → res.country | Country |
| `lang` | Selection | Language preference |
| `timezone` | Selection | Timezone |
| `channel_ids` | Many2many → discuss.channel | Guest's channels |
| `im_status` | Char (computed) | Online status |

**Key Methods:**

| Method | Description |
|--------|-------------|
| `_get_guest_from_token(channel_id, token)` | Authenticate guest by token |
| `_get_guest_from_context()` | Get guest from request cookies |
| `_set_auth_cookie()` | Set authentication cookie |

---

## Infrastructure Models

### mail.presence

**File:** `models/mail_presence.py`

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | Many2one → res.users | User |
| `guest_id` | Many2one → mail.guest | Guest |
| `last_poll` | Datetime | Last poll time |
| `last_presence` | Datetime | Last activity |
| `status` | Selection | online, away, offline |

### ir.mail_server (patched)

**File:** `models/ir_mail_server.py`

Added fields: `owner_user_id` (personal server), `owner_limit_time`, `owner_limit_count` (rate limiting)

### fetchmail.server

**File:** `models/fetchmail.py`

| Field | Type | Description |
|-------|------|-------------|
| `server_type` | Selection | imap, pop, local |
| `server` | Char | Hostname/IP |
| `port` | Integer | Port |
| `is_ssl` | Boolean | Use SSL/TLS |
| `user` / `password` | Char | Credentials |
| `object_id` | Many2one → ir.model | Route emails to model |

### res.users.settings (patched)

**File:** `models/res_users_settings.py`

Added fields: `push_to_talk_key`, `use_push_to_talk`, `voice_active_duration`, `channel_notifications`, sidebar category toggles

---

## Patched Core Models

### Base (`models/models.py`)

| Addition | Description |
|----------|-------------|
| `_valid_field_parameter()` | Allows `tracking` attribute on fields |
| `with_user(user)` | Clears guest context |
| `unlink()` | Auto-deletes associated mail.activity |
| `_mail_get_companies()` | Map records to companies |
| `_mail_get_partner_fields()` | Discover partner field names |
| `_mail_get_primary_email()` | Extract primary email field |

### res.partner (`models/res_partner.py`)

**Inherits:** `mail.activity.mixin`, `mail.thread.blacklist`

Added fields: `im_status`, `offline_since` (computed from presence), tracked fields (`name`, `email`, `phone`, `parent_id`, `user_id`, `vat`)

Key methods: `_find_or_create_from_emails()`, `get_mention_suggestions()`

### res.users (`models/res_users.py`)

Added fields: `role_ids`, `notification_type` (email/inbox), `out_of_office_from/to/message`, `is_out_of_office`, `im_status`, `manual_im_status`, `outgoing_mail_server_id`

Key methods: `_init_store_data()`, `_init_messaging()`, `_get_activity_groups()`

---

## Wizard Models

### mail.compose.message

**File:** `wizard/mail_compose_message.py`
**Type:** TransientModel

| Field | Type | Description |
|-------|------|-------------|
| `composition_mode` | Selection | comment, mass_mail |
| `template_id` | Many2one → mail.template | Template selector |
| `attachment_ids` | Many2many → ir.attachment | Attachments |
| `email_from` | Char (computed) | Sender email |
| `author_id` | Many2one → res.partner (computed) | Author |

Batch size: 50 records for mass_mail mode.

### mail.activity.schedule

**File:** `wizard/mail_activity_schedule.py`
**Type:** TransientModel

Supports both plan-based (predefined templates) and custom activity creation. Batch size: 500 records.

### mail.followers.edit

**File:** `wizard/mail_followers_edit.py`
**Type:** TransientModel

Bulk add/remove followers with optional notification.
