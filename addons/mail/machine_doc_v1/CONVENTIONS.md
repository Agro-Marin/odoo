# Mail Module — Conventions & Gotchas

## Context Flags

These `env.context` keys control mail.thread behavior. Set via `record.with_context(flag=value)`.

### Suppression Flags

| Flag | Default | Effect |
|------|---------|--------|
| `tracking_disable` | False | **Disables ALL** mail.thread features (tracking, subscribe, log) |
| `mail_notrack` | False | Skip field tracking only |
| `mail_create_nolog` | False | Skip creation log message |
| `mail_create_nosubscribe` | False | Skip auto-subscribe on create |
| `mail_auto_subscribe_no_notify` | False | Skip notifications on auto-subscribe |

### Send/Notification Flags

| Flag | Default | Effect |
|------|---------|--------|
| `mail_notify_force_send` | True | Force immediate email send (vs. queue) |
| `mail_notify_author` | False | Notify author of own messages |
| `mail_notify_author_mention` | False | Notify author if explicitly in partner_ids |
| `mail_post_autofollow` | False | Subscribe partner_ids after message_post |
| `mail_post_autofollow_author_skip` | False | Don't subscribe author when autofollowing |

### Internal Flags

| Flag | Purpose |
|------|---------|
| `mail_catchall_aliases` | Cached catchall emails (internal optimization) |
| `mail_catchall_write_any_to` | Check any To: vs. strict all To: |
| `default_message_type` | Override default message type in context |

## Security Rules Summary

### Access Control (ir.model.access.csv)

| Model | Public | Portal | User | System |
|-------|--------|--------|------|--------|
| mail.message | R | RWCU | RWCU | RWCU |
| mail.mail | — | — | — | RWCU |
| mail.followers | — | — | R | RWCU |
| mail.notification | — | R | RWC | RWCU |
| discuss.channel | R | R | RWC | RWCU |
| discuss.channel.member | RWCU | RWCU | RWCU | RWCU |
| mail.alias | — | — | R | RWCU |
| mail.activity | — | — | RWCU | RWCU |
| mail.template | — | — | RWCU | RWCU |

### Record Rules (mail_security.xml)

| Pattern | Rule |
|---------|------|
| **Channel access** | User is member OR belongs to channel's `group_public_id` |
| **Channel member** | Own entries only + accessible channels |
| **Activity access** | Assigned to user (`user_id`) or created by user (`create_uid`) |
| **Template access** | Created by or assigned to user; editors get full access |
| **Canned responses** | Shared responses visible to all; personal only to owner |
| **Notifications** | Own notifications only (by `res_partner_id`) |
| **Compose wizard** | Only records created by current user |

### Access Groups

| XML ID | Description |
|--------|-------------|
| `mail.group_mail_notification_type_inbox` | Users with inbox notifications |
| `mail.group_mail_template_editor` | Can edit all email templates |

## Naming Conventions

### Model Naming

| Prefix | Use |
|--------|-----|
| `mail.` | Core messaging models (message, mail, followers, etc.) |
| `mail.activity.` | Activity system models |
| `mail.alias.` | Email alias models |
| `mail.thread.*` | MailThread sub-mixins |
| `discuss.channel.*` | Discuss/chat models |

### Method Naming

| Prefix | Visibility | Use |
|--------|-----------|-----|
| `message_*` | Public API | Message operations (post, subscribe, route) |
| `_message_*` | Internal | Internal message helpers |
| `_notify_*` | Internal | Notification dispatch |
| `_track_*` | Internal | Field tracking |
| `_routing_*` | Internal | Mail gateway routing |
| `_detect_*` | Internal | Bounce/loop detection |
| `activity_*` | Public API | Activity operations |
| `_web_push_*` | Internal | Web push helpers |

## Extension Points (Override These)

These methods are designed to be overridden by inheriting modules:

| Method | On | Purpose |
|--------|-----|---------|
| `_track_subtype(initial_values)` | mail.thread | Return subtype for tracked changes |
| `_track_template(changes)` | mail.thread | Define email templates for tracking |
| `_creation_subtype()` | mail.thread | Subtype for creation log message |
| `_creation_message()` | mail.thread | Body text for creation log |
| `_notify_get_recipients_groups(message, ...)` | mail.thread | Classify recipients into groups |
| `_message_auto_subscribe_followers(updated_values, def_ids)` | mail.thread | Custom auto-subscription logic |
| `_message_get_suggested_recipients()` | mail.thread | Suggested To/Cc recipients |
| `_mail_get_partner_fields()` | Base | Discover partner fields on model |
| `_mail_get_primary_email_field()` | mail.thread | Primary email field name |
| `_mail_get_companies(default)` | Base | Map records to companies |
| `_get_customer_information()` | mail.thread | Extract customer data |
| `message_new(msg_dict, custom_values)` | mail.thread | Create record from incoming email |
| `message_update(msg_dict, update_vals)` | mail.thread | Update record from incoming email |

## Tools Reference

| Module | Location | Purpose |
|--------|----------|---------|
| `Store` | `tools/discuss.py` | JSON serialization for web client (records → frontend store) |
| `mail_validate` | `tools/mail_validation.py` | Email validation (flanker fallback) |
| `parse_res_ids` | `tools/parser.py` | Parse string res_ids to integer list |
| `sign` / `generate_vapid_keys` | `tools/jwt.py` | JWT/VAPID signing for web push |
| `get_link_preview_from_url` | `tools/link_preview.py` | Open Graph metadata extraction (SSRF-protected) |
| `push_to_end_point` | `tools/web_push.py` | Web Push encryption (AES128GCM + VAPID) |
| `AliasError` | `tools/alias_error.py` | Structured error for email alias failures |

## Store Pattern (Frontend Data Bridge)

The `Store` class (`tools/discuss.py`) is the standard way to serialize ORM data for the frontend:

```python
store = Store()
store.add(records, fields=["name", "email"])       # Add specific fields
store.add(messages, as_thread=True)                 # Add as thread context
store.add_global_values(hasLinkPreviewFeature=True)  # Add global values
store.delete(records)                               # Mark records for deletion
result = store.get_result()                         # → dict for JSON response

# Bus integration
store = Store(bus_channel=channel_member)
store.add(message)
store.bus_send("mail.record/insert")               # Send via bus.bus
```

**Key classes:**
- `Store.Attr(value)` — static attribute per record
- `Store.One(relation)` — single related record
- `Store.Many(relation, mode=REPLACE|ADD|DELETE)` — collection of related records

## Critical Gotchas

### 1. Tracking uses precommit hooks, not onchange

Field tracking (`tracking=N`) is implemented via `_track_prepare()` → `_track_finalize()` using `env.cr.precommit` hooks. The tracking messages are created **after** the ORM write commits. This means:
- You cannot test tracking values without calling `flush_tracking()` in tests
- Tracking runs even in batch writes — initial values are captured before the write

### 2. `_mail_flat_thread` controls message hierarchy

When `True` (default), all reply messages are linked to the **first message** on the record, flattening the tree. When `False`, messages maintain parent-child hierarchy. This affects how `parent_id` is computed in `message_post()`.

### 3. message_post() is keyword-only

All parameters after `self` are keyword-only (`*`). Positional calls will fail:
```python
record.message_post(body="Hello")          # CORRECT
record.message_post("Hello")              # WRONG — TypeError
```

### 4. MailMail inherits via _inherits, not _inherit

`mail.mail` uses `_inherits = {'mail.message': 'mail_message_id'}` (delegation inheritance), meaning each `mail.mail` record has an associated `mail.message` record. They share fields but are separate tables.

### 5. Author computation resolves email ↔ partner

`_message_compute_author()` ensures coherence: if `author_id` is given, `email_from` is set from partner; if `email_from` is given, it tries to find a matching partner. Never set both independently.

### 6. Notification recipients depend on subtypes

Only followers subscribed to a message's `subtype_id` receive notifications. If you post with a subtype that nobody follows, no notifications are sent. Use `subtype_xmlid='mail.mt_comment'` for comment-type messages (followed by default).

### 7. Aliases require alias domain configuration

Email aliases only work if `mail.alias.domain` records exist. Without configured domains, `alias_full_name` is empty and incoming email routing via aliases fails silently.

### 8. Guest authentication is cookie-based

`mail.guest` users authenticate via a cookie set by `_set_auth_cookie()`. The `add_guest_to_context` decorator in controllers extracts the guest from the cookie. Guest access is limited to channels they belong to.

### 9. Bus notifications require membership

Discuss channel notifications are sent to `discuss.channel.member` bus channels. Users who are not members of a channel will not receive real-time updates, even if they have read access to the channel model.

### 10. Web push payload limit is 4KB

The `_notify_by_web_push_prepare_payload()` method must keep payloads under 4,096 bytes. `_web_push_truncate_payload()` handles truncation respecting Unicode boundaries.

### 11. Personal mail server rate limiting

Users with personal outgoing mail servers (`owner_user_id` set) are rate-limited via `owner_limit_count` / `owner_limit_time`. The limit is configurable via `_get_personal_mail_servers_limit()`.

### 12. Loop detection is multi-layered

The mail gateway detects loops via:
1. **Sender domain** — known auto-reply domains
2. **Headers** — `References` pointing to own messages
3. **Bounce detection** — DSN / mailer-daemon sender
4. **Catchall write** — emails sent only to catchall address

## What NOT to Do

- **Don't call `message_post` in `create()`** — use `_creation_message()` override or `mail_create_nolog` + explicit post
- **Don't bypass `_notify_thread`** — always let the notification pipeline handle dispatch
- **Don't modify `mail.message` records directly** — use `_message_update_content()` which handles access checks and bus notifications
- **Don't assume `message_ids` includes all messages** — the field excludes `user_notification` type messages
- **Don't use `sudo()` for message posting** — `message_post` checks `_mail_post_access` permission; sudo bypasses security
