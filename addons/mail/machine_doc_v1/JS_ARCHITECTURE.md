# Mail Module — Frontend Architecture

## Overview

The mail module's frontend is built on **OWL** (Odoo Web Library) using a **reactive proxy-based store** for state management. The architecture follows a layered loading strategy with environment-specific asset bundles.

## Directory Structure

```
static/src/
├── model/                 # Reactive store system (core state management)
│   ├── store.js          # Store class (extends Record) — 314 lines
│   ├── record.js         # Base Record class (reactive proxy) — 464 lines
│   ├── record_internal.js # Field getter/setter implementation — 277 lines
│   ├── store_internal.js # Store-specific internals
│   ├── make_store.js     # Factory for creating reactive stores — 227 lines
│   ├── misc.js           # Field definitions (fields.One, fields.Many, fields.Attr) — 222 lines
│   ├── record_list.js    # RecordList for Many() fields — 676 lines
│   └── export.js         # Public API
│
├── core/
│   ├── common/           # Shared components & services (~89 JS files)
│   │   ├── store_service.js      # Main mail.store service — 871 lines
│   │   ├── thread_model.js       # Thread domain model
│   │   ├── message_model.js      # Message domain model
│   │   ├── attachment_model.js   # Attachment domain model
│   │   ├── composer_model.js     # Composer domain model
│   │   ├── thread.js             # Thread OWL component
│   │   ├── message.js            # Message OWL component
│   │   ├── composer.js           # Composer OWL component
│   │   ├── chat_window.js        # Floating chat window
│   │   └── chat_hub.js           # Chat hub service
│   │
│   ├── public_web/       # Discuss app entry
│   │   ├── discuss.js              # Main Discuss component
│   │   ├── discuss_client_action.js # Client action wrapper
│   │   ├── discuss_content.js
│   │   ├── discuss_sidebar.js
│   │   └── messaging_menu.js       # Top-bar messaging menu
│   │
│   ├── web/              # Backend-specific patches
│   └── web_portal/       # Portal-specific patches
│
├── discuss/              # Discuss feature modules
│   ├── core/             # Core discuss features
│   ├── call/             # RTC voice/video
│   ├── message_pin/      # Message pinning
│   ├── voice_message/    # Voice recording
│   ├── typing/           # Typing indicators
│   ├── gif_picker/       # GIF search (Tenor)
│   └── web/avatar_card/  # Hover avatar card
│
├── chatter/              # Document chatter component
│   ├── web_portal/       # Core chatter component
│   └── web/              # Backend patches (activities, followers)
│
├── views/                # Field widgets & view patches
│   └── fields/           # 13+ custom field widgets
│
├── utils/                # Utility functions
├── js/                   # Legacy/special JS
├── scss/                 # Stylesheets (~132 files)
└── worklets/             # Web audio worklets
```

## State Management: Reactive Store

### Architecture

The mail module uses a **reactive proxy-based record system** inspired by Vue 3's reactivity model:

```
┌─────────────────────────────────────────────────┐
│                  Store (singleton)                │
│                                                   │
│  recordByLocalId: reactive Map<string, Record>   │
│                                                   │
│  ┌─────────┐ ┌─────────┐ ┌──────────────┐      │
│  │ Thread   │ │ Message │ │ Attachment   │ ...  │
│  │ records  │ │ records │ │ records      │      │
│  └─────────┘ └─────────┘ └──────────────┘      │
│                                                   │
│  MAKE_UPDATE(fn) — batched mutation system       │
│  Update queues: FC,FS,FA,FD,FU,RO,RD,RHD        │
└─────────────────────────────────────────────────┘
         │
         │  OWL reactive() auto-triggers re-render
         ▼
┌─────────────────────────────────────────────────┐
│              OWL Components                       │
│  Discuss, Thread, Message, Composer, Chatter     │
└─────────────────────────────────────────────────┘
```

### Field System (`model/misc.js`)

```javascript
// Relational fields with automatic bidirectional sync
fields.One("Thread", { inverse: "composer" })    // Single related record
fields.Many("Message", { inverse: "thread" })    // Collection of related records
fields.Attr(defaultValue, { onUpdate() {...} })  // Non-relational attribute

// Combinators
OR(fields.One("Thread"), false)  // Optional field with fallback
AND(condition, fields.One("X"))  // Conditional field
```

### Record Class (`model/record.js`)

```javascript
class Record {
    static _name;           // Model name (e.g., "Thread")
    static id;              // Primary key field
    static env;             // Environment reference
    static store;           // Store reference

    MAKE_UPDATE(fn);        // Batched field updates
    onChange(record, fields, callback);  // Field subscriptions
    delete();               // Remove from store
    in(collection);         // Check membership
    notIn(collection);      // Check non-membership
}
```

### Store Service (`core/common/store_service.js`)

The singleton `mail.store` service (873 lines) initializes and manages all mail models:

```javascript
// Service registration
registry.category("services").add("mail.store", {
    dependencies: ["bus_service", "ui", ...],
    start(env, deps) {
        return makeStore(env, deps);
    }
});

// Usage in components
setup() {
    this.store = useService("mail.store");
}
```

### Data Flow

```
Server → RPC response → store.insert(data) → reactive Map update → OWL re-render
                                                                         │
User action → Component event → store mutation → field setter → onUpdate callbacks
                                                                         │
                                                       RPC call → Server → response
```

## Key Domain Models (JS)

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `Thread` | Conversation thread | `id`, `model`, `name`, `messages`, `composer`, `attachments`, `followers` |
| `Message` | Single message | `id`, `body`, `author`, `thread`, `attachments`, `reactions` |
| `Attachment` | File attachment | `id`, `name`, `message`, `thread`, `extension`, `isPdf` |
| `Composer` | Message input | `thread`, `message_type`, `body`, `attachments`, `isFocused` |
| `Persona` | User/guest identity | `id`, `name`, `im_status`, `isInternalUser` |
| `ChannelMember` | Channel membership | `persona`, `channel`, `seen_message_id` |

## OWL Component Hierarchy

```
Discuss (top-level app)
├── DiscussSidebar
│   └── DiscussSidebarCategories
├── DiscussContent
│   ├── Thread (main conversation)
│   │   ├── Message (per message)
│   │   │   ├── MessageInReply
│   │   │   ├── MessageReactions
│   │   │   ├── AttachmentList
│   │   │   ├── MessageLinkPreviewList
│   │   │   └── ActionList (dropdown)
│   │   └── DateSection
│   └── Composer (input box)
│       ├── AttachmentUploader
│       └── MailAttachmentDropzone
└── MessagingMenu (navbar)

Chatter (on document forms)
├── Thread
├── Composer
├── Activity
├── FollowerList
└── AttachmentList
```

## Registered Services

| Service | File | Purpose |
|---------|------|---------|
| `mail.store` | `core/common/store_service.js` | Reactive store singleton |
| `mail.suggestion` | `core/common/suggestion_service.js` | @mention autocomplete |
| `im_status` | `core/common/im_status_service.js` | Online status tracking |
| `mail.sound_effects` | `core/common/sound_effects_service.js` | Notification sounds |
| `mail.popout` | `core/common/mail_popout_service.js` | Popout message windows |
| `mail.chat_hub` | `core/common/chat_hub.js` | Floating chat windows |
| `mail.out_of_focus` | `core/common/out_of_focus_service.js` | Browser focus tracking |
| `mail.attachment_upload` | `core/common/attachment_upload_service.js` | File upload handling |
| `mail.fullscreen` | `core/common/mail_fullscreen.js` | Fullscreen mode |
| `mail.composer` | `core/common/composer_service.js` | Composer state management |

## Field Widgets

Custom field widgets registered in the `fields` registry.

Note: Most widgets live under `views/web/fields/` (backend-only); a few are in `views/fields/` (shared).

| Widget ID | Purpose | Location |
|-----------|---------|----------|
| `html_mail` | HTML email composer | `views/web/fields/html_mail_field/` |
| `html_composer_message` | Message body editor | `views/web/fields/html_composer_message_field/` |
| `many2one_avatar_user` | User picker with avatar | `views/web/fields/many2one_avatar_user_field/` |
| `many2many_avatar_user` | Multiple users with avatars | `views/web/fields/many2many_avatar_user_field/` |
| `kanban_activity` | Activity widget (kanban) | `views/web/fields/kanban_activity/` |
| `list_activity` | Activity widget (list) | `views/web/fields/list_activity/` |
| `text_emojis` | Text field with emoji picker | `views/web/fields/emojis_text_field/` |
| `char_emojis` | Char field with emoji support | `views/web/fields/emojis_char_field/` |
| `statusbar_duration` | Status bar with duration | `views/fields/statusbar_duration/` |
| `activity_model_selector` | Activity type selector | `views/fields/activity_model_selector/` |
| `selection_badge_icons` | Selection with icon badges | `views/fields/badge_selection_icons/` |
| `mail_server_configurator_selection` | Email server config | `views/fields/mail_server_configurator_selection/` |
| `scheduled_date` | Scheduled date display | `views/fields/scheduled_date_field/` |
| `properties_field` | Properties field extension | `views/fields/properties_field/` |

## Registries

| Registry | Purpose |
|----------|---------|
| `mail.composer/actions` | Contextual composer actions (attach file, template, etc.) |
| `mail.discuss/sidebar_items` | Sidebar category definitions |
| `discuss.component` | Custom component rendering |

## Asset Bundle Loading Strategy

The `__manifest__.py` uses explicit ordering to handle dependencies:

1. **Variables** — SCSS variables loaded first
2. **Model layer** — `model/**/*` (Record, Store, fields)
3. **Core common** — `core/common/**/*` (shared services, components)
4. **Core web** — `core/web/**/*` (backend-specific patches)
5. **Feature modules** — Discuss, chatter, views (loaded last)

**Important:** Discuss assets are removed then re-added last — this is an intentional dependency ordering mechanism ensuring all base components are registered before discuss-specific patches are applied.

## Vendored Libraries

| Library | Path | Purpose |
|---------|------|---------|
| idb-keyval | `static/lib/idb-keyval/` | IndexedDB key-value store |
| lame.js | `static/lib/lame/` | MP3 encoding (voice messages) |
| odoo_sfu | `static/lib/odoo_sfu/` | Selective Forwarding Unit (video calls) |
| selfie_segmentation | `static/lib/selfie_segmentation/` | ML model for background blur |

## Key Patterns

### Component Service Injection

```javascript
setup() {
    this.store = useService("mail.store");
    this.soundEffects = useService("mail.sound_effects");
}
```

### Feature Extension via Patches

Features extend existing models without modifying core files:

```javascript
// In discuss/message_pin/message_model_patch.js
patch(Message.prototype, {
    get isPinned() { return Boolean(this.pinned_at); },
});
```

### Server Data Integration

```javascript
// RPC returns data in Store-compatible format
const data = await this.orm.call("discuss.channel", "channel_info", [channelId]);
this.store.insert(data);  // Merges into reactive store
```

### Python-to-JS Model Mapping

The `pyToJsModels` mapping connects server model names to JS record classes:
- `"discuss.channel"` → `"Thread"`
- `"mail.message"` → `"Message"`
- `"ir.attachment"` → `"Attachment"`
- `"res.partner"` / `"mail.guest"` → `"Persona"`
