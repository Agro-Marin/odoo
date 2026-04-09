# Mail Module — Architecture

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (OWL)                               │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ Discuss  │  │ Chatter  │  │ Messaging│  │  Field Widgets     │  │
│  │   App    │  │Component │  │  Menu    │  │  (activity, avatar)│  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬───────────┘  │
│       └──────────────┴─────────────┴─────────────────┘              │
│                          │                                          │
│              ┌───────────┴───────────┐                              │
│              │   Reactive Store      │  (model/, core/common/)      │
│              │   Record + Store      │                              │
│              └───────────┬───────────┘                              │
├──────────────────────────┼──────────────────────────────────────────┤
│                     JSON-RPC / HTTP                                 │
├──────────────────────────┼──────────────────────────────────────────┤
│                        Backend                                      │
│  ┌───────────────────────┴───────────────────────────────────────┐  │
│  │                    Controllers (21 files)                     │  │
│  │  mail.py  thread.py  mailbox.py  discuss/channel.py  rtc.py  │  │
│  └───────────────────────┬───────────────────────────────────────┘  │
│                          │                                          │
│  ┌───────────────────────┴───────────────────────────────────────┐  │
│  │                    ORM Models                                 │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │  Abstract Mixins (inherited by any model)               │  │  │
│  │  │  MailThread · MailActivityMixin · MailAliasMixin         │  │  │
│  │  │  MailRenderMixin · MailComposerMixin · MailBlacklist...  │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │  Concrete Models                                        │  │  │
│  │  │  mail.message · mail.mail · mail.followers              │  │  │
│  │  │  mail.notification · mail.activity · mail.template      │  │  │
│  │  │  discuss.channel · discuss.channel.member · mail.guest  │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │  Patched Core Models                                    │  │  │
│  │  │  Base · ResPartner · ResUsers · IrAttachment · IrHttp   │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                          │                                          │
│  ┌───────────────────────┴───────────────────────────────────────┐  │
│  │  Infrastructure                                               │  │
│  │  ir.mail_server (SMTP) · fetchmail.server (IMAP/POP)         │  │
│  │  bus.bus (real-time) · mail.presence (IM status)              │  │
│  │  Web Push (VAPID/AES128GCM) · WebRTC (ICE/SFU)              │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Mixin Hierarchy

The mail module provides abstract mixins that any Odoo model can inherit to gain communication features:

```
                    models.Base (patched)
                         │
              ┌──────────┴──────────┐
              │                     │
         mail.thread          mail.activity.mixin
              │                     │
    ┌─────────┼──────────┐          │
    │         │          │          │
  mail.     mail.      mail.       │
  thread.   thread.    thread.     │
  blacklist cc         main_       │
                       attachment  │
                                   │
                    mail.tracking.duration.mixin
```

**MailThread** (`mail.thread`) — The core mixin. Adds:
- `message_ids` — chatter messages
- `message_follower_ids` — document subscribers
- `message_post()` — post messages with notifications
- Field tracking via `tracking=N` attribute
- Auto-subscription on relational field changes
- Mail gateway integration (message_route, message_new, message_update)

**MailActivityMixin** (`mail.activity.mixin`) — Adds:
- `activity_ids` — scheduled activities/tasks
- `activity_state` — overdue/today/planned
- `activity_schedule()` / `activity_feedback()` — programmatic API

**MailAliasMixin** (`mail.alias.mixin`) — Adds:
- Email alias for automatic record creation from incoming emails
- Required variant (`mail.alias.mixin`) and optional variant (`mail.alias.mixin.optional`)

**MailRenderMixin** (`mail.render.mixin`) — Adds:
- QWeb template rendering for email bodies
- Dynamic placeholder resolution (e.g., `{{ object.name }}`)

## Message Lifecycle

```
                  ┌──────────────┐
                  │ message_post │ (or mail gateway)
                  └──────┬───────┘
                         │
              ┌──────────▼──────────┐
              │ _message_create()   │  Create mail.message
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │ _notify_thread()    │  Compute recipients
              └──────────┬──────────┘
                         │
           ┌─────────────┼─────────────────┐
           │             │                 │
    ┌──────▼──────┐ ┌────▼─────┐  ┌───────▼────────┐
    │  by_inbox   │ │ by_email │  │ by_web_push    │
    │ (bus notif) │ │(mail.mail│  │ (VAPID push)   │
    └─────────────┘ │  queue)  │  └────────────────┘
                    └────┬─────┘
Note: OOO auto-reply runs as a preprocessing step
before the three dispatch channels above.
                         │
              ┌──────────▼──────────┐
              │   mail.mail.send()  │  SMTP delivery
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │ _postprocess_sent   │  Update notification status
              └─────────────────────┘
```

### Notification Types

| Type | Mechanism | Trigger |
|------|-----------|---------|
| **inbox** | `bus.bus` record → longpoll/websocket | User's `notification_type = 'inbox'` |
| **email** | `mail.mail` → SMTP | User's `notification_type = 'email'` |
| **web_push** | VAPID/AES128GCM → browser push endpoint | Device registered in `mail.push.device` |
| **out_of_office** | Auto-reply message (preprocessing step, not a dispatch channel) | Recipient has OOO dates set |

## Mail Gateway Flow (Incoming Email)

```
  External Email
       │
       ▼
  fetchmail.server._fetch_mails()     ← Cron job
       │
       ▼
  MailThread.message_process()        ← Parse RFC2822
       │
       ▼
  MailThread.message_route()          ← Route to model/thread
       │
       ├── Check Message-ID → existing thread reply?
       ├── Check mail.alias → create new record?
       ├── Check model/thread_id → fallback route?
       └── Bounce detection / loop detection
       │
       ▼
  message_new() or message_update()   ← Create/update record
       │
       ▼
  message_post()                      ← Post on thread
```

### Routing Heuristics (Priority Order)

1. **Reply detection** — `In-Reply-To` / `References` headers match existing `mail.message.message_id`
2. **Alias matching** — Email `To:` matches a `mail.alias.alias_full_name`
3. **Fallback** — Use provided `model` + `thread_id` from fetchmail config
4. **Bounce** — Detect DSN / mailer-daemon and route to bounce handler
5. **Loop** — Detect auto-reply loops via headers and domain heuristics

## Follower & Subscription System

```
  Document (any MailThread model)
       │
       ├── message_follower_ids → mail.followers
       │       │
       │       ├── partner_id → res.partner (who)
       │       └── subtype_ids → mail.message.subtype (what)
       │
       ├── Auto-subscribe on:
       │       ├── Record creation (author)
       │       ├── Relational field write (e.g., user_id change)
       │       └── message_post with mail_post_autofollow=True
       │
       └── Notification filtering:
               └── Only notify followers subscribed to message's subtype
```

## Activity System

```
  mail.activity.type          mail.activity.plan
  (To Do, Call, Email...)     (predefined workflows)
       │                           │
       ▼                           ▼
  mail.activity               mail.activity.plan.template
  (assigned to user,          (templates within a plan)
   linked to document)
       │
       ├── action_done() → archive + post feedback message
       ├── action_feedback_schedule_next() → chain to next type
       └── Cron: overdue detection
```

## Discuss (Real-Time Chat)

```
  discuss.channel
       │
       ├── channel_type: 'chat' (1-to-1), 'group', 'channel' (public)
       │
       ├── channel_member_ids → discuss.channel.member
       │       ├── partner_id / guest_id (who)
       │       ├── seen_message_id (read receipts)
       │       ├── custom_notifications (per-channel prefs)
       │       └── rtc_session_ids → discuss.channel.rtc.session
       │
       ├── sub_channel_ids (thread-within-channel)
       │
       ├── rtc_session_ids (voice/video calls)
       │       ├── is_camera_on, is_muted, is_screen_sharing_on
       │       └── SFU integration (sfu_channel_uuid, sfu_server_url)
       │
       └── mail.guest (anonymous users in public channels)
               ├── access_token (UUID)
               └── Cookie-based auth (_set_auth_cookie)
```

## Email Infrastructure

```
  ir.mail_server (outgoing SMTP)
       ├── host, port, smtp_authentication
       ├── owner_user_id (personal server per user)
       └── Rate limiting (owner_limit_count, owner_limit_time)

  fetchmail.server (incoming IMAP/POP)
       ├── server_type: imap/pop/local
       ├── Cron-based fetching
       └── Routes to model via object_id

  mail.alias.domain
       ├── name (e.g., "example.com")
       ├── bounce_alias, catchall_alias, default_from
       └── company_ids (multi-company support)

  mail.alias
       ├── alias_name + alias_domain_id → alias_full_name
       ├── alias_model_id → target model for new records
       ├── alias_defaults → default field values (JSON)
       └── alias_contact → access policy (everyone/partners/followers)
```

## Key Integration Points

### How Other Modules Use Mail

```python
class SaleOrder(models.Model):
    _inherit = ['mail.thread', 'mail.activity.mixin']

    state = fields.Selection([...], tracking=1)  # Auto-track changes
    user_id = fields.Many2one('res.users', tracking=2)  # Track + auto-subscribe

    def action_confirm(self):
        self.message_post(body="Order confirmed")
        self.activity_feedback(['sale.mail_act_sale_upsell'])
```

### Store Pattern (Frontend Data Bridge)

The `Store` class (`tools/discuss.py`) serializes ORM records to JSON for the web client:

```python
store = Store()
store.add(channel, fields=["name", "channel_type"])
store.add(messages, as_thread=True)
result = store.get_result()  # → JSON dict for frontend
```

The frontend `store.insert(data)` method merges server data into the reactive record system.
