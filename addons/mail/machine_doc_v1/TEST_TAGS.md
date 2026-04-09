# Mail Module — Test Reference

## Test Base Classes

### Hierarchy

```
common.BaseCase + MockSmtplibCase
        │
    MockEmail                    ← Email mocking (SMTP, build_email)
        │
    MailCase (+ BusCase)         ← Full mail + bus mocking
        │
    MailCommon                   ← Default test data + setup
        │
    ├── ActivityScheduleCase     ← Activity plan testing
    ├── MailTrackingDurationMixinCase ← Duration tracking testing
    └── MailControllerCommon     ← HTTP endpoint testing (HttpCase)
```

### MailCommon (`tests/common.py`)

The main base class for mail tests. Provides:

**Default Test Context** (`_test_context`):
- `mail_create_nolog=True` — no creation log messages
- `mail_create_nosubscribe=True` — no auto-subscriptions
- `mail_notrack=True` — no field tracking
- `no_reset_password=True` — no password reset emails

**Test Users & Partners:**

| Variable | Login | Name | Groups | Notification |
|----------|-------|------|--------|-------------|
| `user_admin` | admin | Mitchell Admin | admin | inbox |
| `user_employee` | employee | Ernest Employee | user, partner_manager | inbox |
| `user_employee_c2` | employee_c2 | Enguerrand Employee C2 | user, partner_manager | inbox |
| `user_employee_c3` | employee_c3 | Freudenbergerg Employee C3 | user, partner_manager | inbox |
| `user_public` | — | Public User | public | — |
| `user_root` | __system__ | Root | — | — |

**Test Companies:**

| Variable | Name | Country | Email |
|----------|------|---------|-------|
| `company_admin` | YourTestCompany | Belgium | your.company@example.com |
| `company_2` | Company 2 | Canada | company_2@test.example.com |
| `company_3` | Company 3 | Belgium | company_3@test.example.com |

**Mail Configuration:**
- `alias_domain`: test.mycompany.com
- `alias_catchall`: catchall.test
- `alias_bounce`: bounce.test
- `default_from`: notifications.test

**Test Data:**
- `guest` — `mail.guest` record named "Guest Mario"

---

## Mock Utilities

### mock_mail_gateway()

Context manager that mocks the entire email sending pipeline:

```python
with self.mock_mail_gateway():
    record.message_post(body="Test", partner_ids=partner.ids)

# Captured data:
self._mails          # Raw email dicts from _build_email
self._new_mails      # mail.mail records created
self._new_msgs       # mail.message records created
self._new_notifs     # mail.notification records created
```

### mock_mail_app()

Context manager for capturing mail.message and mail.notification creation:

```python
with self.mock_mail_app():
    record.message_post(body="Test")
    
self.assertEqual(len(self._new_msgs), 1)
```

### mock_bus()

Context manager for capturing bus.bus notifications:

```python
with self.mock_bus():
    record.message_post(body="Test")

self.assertBusNotifications(
    [(self.cr.dbname, 'res.partner', partner.id)],
    [{'type': 'mail.record/insert', ...}]
)
```

### flush_tracking()

Forces tracking value creation between test steps:

```python
record.write({'state': 'done'})
self.flush_tracking()  # Force tracking messages to be created
# Now assert on tracking values
```

### mock_datetime_and_now()

Combined freezegun + `env.cr.now()` patching:

```python
with self.mock_datetime_and_now('2025-01-15 10:00:00'):
    record.activity_schedule(date_deadline=date.today())
```

---

## Assertion Helpers

### Email Assertions

| Method | Description |
|--------|-------------|
| `assertSentEmail(email_from, email_to_list)` | Assert email was sent |
| `assertNotSentEmail(email_to_list)` | Assert no email sent to addresses |
| `assertNoMail(partners, mail_message, author)` | Assert no mail.mail created |
| `assertMailMail(partners, status, ...)` | Assert mail.mail record content |
| `assertMailMailWEmails(emails, status, ...)` | Assert by email address |

### Message Assertions

| Method | Description |
|--------|-------------|
| `assertMessageFields(message, fields_values)` | Assert mail.message field values |
| `assertTracking(message, tracking_list)` | Assert mail.tracking.value records |

### Bus Assertions

| Method | Description |
|--------|-------------|
| `assertBusNotifications(channels, messages)` | Assert bus.bus notifications |

### Activity Assertions (ActivityScheduleCase)

| Method | Description |
|--------|-------------|
| `assertActivityValues(record, expected)` | Validate activity field values |
| `assertActivityCreatedOnRecord(record, activity_type, user)` | Check activity creation |
| `assertActivityDoneOnRecord(record, activity_type)` | Check activity completion |
| `assertActivitiesFromPlan(record, plan, expected)` | Validate plan execution |

---

## Backend Test Files (51 files)

### Core Tests

| File | Test Class(es) | Focus |
|------|-----------------|-------|
| `test_mail_message.py` | TestMailMessage* | Message CRUD, access, threading |
| `test_mail_mail.py` | TestMailMail* | Outgoing email queue, sending |
| `test_mail_template.py` | TestMailTemplate* | Template rendering, sending |
| `test_mail_activity.py` | TestMailActivity* | Activity lifecycle |
| `test_mail_composer.py` | TestMailComposer* | Composition wizard |
| `test_mail_render.py` | TestMailRender* | QWeb template rendering |

### System Tests

| File | Focus |
|------|-------|
| `test_ir_mail_server.py` | SMTP server configuration |
| `test_ir_websocket.py` | WebSocket communication |
| `test_fetchmail.py` | POP/IMAP email fetching |
| `test_link_preview.py` | Link preview extraction |
| `test_mail_presence.py` | Online/away status |

### Feature Tests

| File | Focus |
|------|-------|
| `test_mail_message_translate.py` | Message translation |
| `test_res_partner.py` | Partner mail patches |
| `test_res_users.py` | User mail patches |
| `test_res_role.py` | Role-based access |
| `test_uninstall.py` | Clean uninstallation |

### Discuss Tests (24 files in `tests/discuss/`)

| File | Focus |
|------|-------|
| `test_discuss_channel.py` | Channel CRUD, types |
| `test_discuss_channel_member.py` | Membership management |
| `test_discuss_channel_access.py` | Access control rules |
| `test_discuss_channel_invite.py` | Channel invitations |
| `test_discuss_channel_as_guest.py` | Guest user scenarios |
| `test_discuss_sub_channels.py` | Sub-channel/thread features |
| `test_guest.py` | Guest model |
| `test_guest_feature.py` | Guest integration |
| `test_rtc.py` | Voice/video calls |
| `test_load_messages.py` | Message pagination |
| `test_discuss_mention_suggestions.py` | @mention autocomplete |
| `test_discuss_reaction_controller.py` | Emoji reactions |
| `test_discuss_message_update_controller.py` | Message editing |
| `test_discuss_thread_controller.py` | Thread controller |
| `test_message_controller.py` | Message controller |
| `test_ui.py` | Discuss UI tours |

---

## Running Tests

### Single module (all tests)

```bash
> ./odoo.log && ./addons/core/odoo-bin -c ./odoo.conf -d test_db \
    --test-tags '/mail' -u mail --stop-after-init --workers=0
```

### Specific test class

```bash
> ./odoo.log && ./addons/core/odoo-bin -c ./odoo.conf -d test_db \
    --test-tags '/mail:TestMailMessage' -u mail --stop-after-init --workers=0
```

### Specific test method

```bash
> ./odoo.log && ./addons/core/odoo-bin -c ./odoo.conf -d test_db \
    --test-tags '/mail:TestMailMessage.test_message_post' \
    -u mail --stop-after-init --workers=0
```

### Discuss tests only

```bash
> ./odoo.log && ./addons/core/odoo-bin -c ./odoo.conf -d test_db \
    --test-tags '/mail:TestDiscussChannel' -u mail --stop-after-init --workers=0
```

### Fresh test database

```bash
dropdb --if-exists test_db \
    && createdb test_db -O odoo --template=template0 --lc-collate=C --lc-ctype=C --encoding=UTF8 \
    && psql -d test_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent; ALTER FUNCTION unaccent(text) IMMUTABLE;" \
    && > ./odoo.log && ./addons/core/odoo-bin -c ./odoo.conf -d test_db \
    --test-tags '/mail' -i mail --stop-after-init --workers=0
```

### Check results

```bash
grep "tests when loading" ./odoo.log
grep -E "ERROR.*FAIL:" ./odoo.log | tail -20
```

---

## Controller Test Infrastructure

### MailControllerCommon (`tests/common_controllers.py`)

Combines `HttpCase` + `MailCommon` for endpoint testing.

**Subclasses:**

| Class | Purpose |
|-------|---------|
| `MailControllerAttachmentCommon` | Attachment upload/delete tests |
| `MailControllerBinaryCommon` | Avatar/binary serving tests |
| `MailControllerReactionCommon` | Message reaction tests |
| `MailControllerThreadCommon` | Message posting multi-user tests |
| `MailControllerUpdateCommon` | Message update tests |

Each provides `_execute_subtests_*()` methods that run parameterized tests across multiple users/guests with permission assertions.

---

## Frontend Tests (~165 files in `static/tests/`)

### Test Categories

| Directory | Focus |
|-----------|-------|
| `activity/` | Activity component tests |
| `chatter/` | Chatter component tests |
| `chat_window/` | Chat window tests |
| `composer/` | Message composer tests |
| `discuss/` | Discuss channel tests |
| `discuss_app/` | Discuss app-level tests |
| `message/` | Message component tests |
| `messaging_menu/` | Messaging menu tests |
| `thread/` | Thread component tests |
| `emoji/` | Emoji picker tests |
| `gif_picker/` | GIF search tests |
| `translation/` | Translation feature tests |
| `scheduled_message/` | Scheduled message tests |
| `tours/` | Guided tour tests |
| `mock_server/` | Mock server models for testing |

---

## Key Test Patterns

### 1. Context Suppression

```python
# Suppress mail features in non-mail tests
record = self.env['sale.order'].with_context(**self._test_context).create({...})
```

### 2. Flush Tracking Between Steps

```python
record.write({'stage_id': stage2.id})
self.flush_tracking()  # REQUIRED before asserting tracking values
self.assertTracking(record.message_ids[0], [('stage_id', 'many2one', stage1, stage2)])
```

### 3. Multi-Company Testing

```python
# Default setup provides 3 companies with dedicated employees
with self.with_user(self.user_employee_c2):
    record = self.env['model'].create({...})
    record.message_post(body="From company 2")
```

### 4. Portal User Testing

```python
portal_user = self._create_portal_user()
with self.with_user(portal_user):
    # Test portal-specific access
    ...
```
