# Mail Module — Machine Documentation v1

## Purpose

The `mail` module (branded **Discuss**) is Odoo's communication platform. It provides:

- **MailThread mixin** — adds chatter (messages, followers, tracking) to any model
- **MailActivityMixin** — adds scheduled activities/tasks to any model
- **Discuss app** — real-time chat (1-to-1, group, channels) with voice/video calls
- **Mail gateway** — bidirectional email via SMTP/IMAP/POP3
- **Notification system** — inbox, email, and web push notifications
- **Email templates** — QWeb-rendered dynamic email templates

## Files at a Glance

| File | Purpose |
|------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layers, mixin hierarchy, notification pipeline, data flow |
| [MODELS.md](MODELS.md) | Complete ORM model reference (fields, methods, relationships) |
| [ROUTE_MAP.md](ROUTE_MAP.md) | HTTP endpoint catalog (67 routes across 21 controllers) |
| [CONVENTIONS.md](CONVENTIONS.md) | Context flags, security rules, patterns, gotchas |
| [JS_ARCHITECTURE.md](JS_ARCHITECTURE.md) | Frontend: reactive store, OWL components, services, widgets |
| [TEST_TAGS.md](TEST_TAGS.md) | Test infrastructure: base classes, fixtures, mocks, commands |

## Module Identity

| Attribute | Value |
|-----------|-------|
| Technical name | `mail` |
| Display name | Discuss |
| Category | Productivity/Discuss |
| Version | 1.19 |
| Dependencies | `web_tour`, `html_editor` |
| Post-init hook | `_mail_post_init` |

## Key Statistics

| Aspect | Count |
|--------|-------|
| Python model files | 78 (62 main + 16 discuss) |
| Abstract mixins | 12 (+ 7 patches on existing abstract models) |
| Controller files | 21 (13 main + 8 discuss) |
| Wizard files | 9 |
| Backend test files | 51 (27 main + 24 discuss) |
| Frontend test files | ~166 |
| JS/TS source files | ~397 |
| SCSS stylesheets | ~133 |
| HTTP routes | 67 |
| Security access rules | 69 |
| Translations | 67 languages |

## Directory Structure

```
mail/
├── controllers/              # HTTP endpoints (13 main + discuss/)
│   └── discuss/              # Discuss-specific endpoints (8 files)
├── data/                     # Default data (16 XML + 1 SQL)
├── demo/                     # Demo data (4 XML)
├── models/                   # ORM models (62 files)
│   └── discuss/              # Discuss models (16 files)
├── security/                 # ACL + record rules
├── static/
│   ├── lib/                  # Vendored JS libs (idb-keyval, lame, odoo_sfu, selfie_segmentation)
│   ├── src/                  # Frontend source (~854 files)
│   │   ├── model/            # Reactive store system
│   │   ├── core/             # Core components & services
│   │   ├── discuss/          # Discuss feature modules
│   │   ├── chatter/          # Chatter component
│   │   ├── views/            # Field widgets
│   │   └── scss/             # Stylesheets
│   └── tests/                # Frontend tests (~165 files)
├── tests/                    # Backend tests (27 files)
│   └── discuss/              # Discuss tests (24 files)
├── tools/                    # Utilities (8 files)
├── views/                    # UI views (41 XML)
├── wizard/                   # Transient models (9 files, 6 XML views)
└── i18n/                     # Translations (67 languages)
```

## Related Modules

| Module | Relationship |
|--------|-------------|
| `base` | Core models extended (res.partner, res.users, ir.attachment) |
| `bus` | Real-time notifications via longpolling/websocket |
| `web` | Frontend framework, OWL components, asset bundles |
| `html_editor` | Rich text editing in composer and templates |
| `web_tour` | Guided tours for Discuss |

## Read Next

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — understand the mixin hierarchy and notification pipeline first
2. **[MODELS.md](MODELS.md)** — detailed model reference for backend work
3. **[ROUTE_MAP.md](ROUTE_MAP.md)** — controller endpoints for API work
4. **[JS_ARCHITECTURE.md](JS_ARCHITECTURE.md)** — frontend reactive store and components
5. **[CONVENTIONS.md](CONVENTIONS.md)** — patterns and gotchas before making changes
6. **[TEST_TAGS.md](TEST_TAGS.md)** — how to run and write tests
