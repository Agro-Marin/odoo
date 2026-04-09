# Mail Module — Route Map

## Legend

| Symbol | Meaning |
|--------|---------|
| **J** | JSON-RPC (`type="json"`) |
| **H** | HTTP (`type="http"`) |
| **U** | `auth="user"` |
| **P** | `auth="public"` |
| **N** | `auth="none"` |

## General Mail (`controllers/mail.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| GET | `/mail/view` | P | H | Redirect to record from notification email link |
| GET | `/mail/unfollow` | P | H | Unfollow document via email link |
| GET | `/mail/message/<int:message_id>` | P | H | Redirect to message's thread |
| GET | `/web_editor/font_to_img/<icon>` | N | H | Render font icon to PNG image |
| GET | `/mail/font_to_img/<icon>` | N | H | Render font icon to PNG (mail variant) |

## Thread & Messages (`controllers/thread.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/thread/messages` | U | J | Fetch messages for a thread (paginated) |
| POST | `/mail/thread/recipients` | U | J | Get suggested recipients for thread |
| POST | `/mail/thread/recipients/fields` | U | J | Get partner fields and primary email field |
| POST | `/mail/thread/recipients/get_suggested_recipients` | U | J | Get updated suggested recipients |
| POST | `/mail/partner/from_email` | U | J | Find or create partners from email addresses |
| POST | `/mail/read_subscription_data` | U | J | Get follower subscription and subtype data |
| POST | `/mail/message/post` | P | J | Post new message to thread |
| POST | `/mail/message/update_content` | P | J | Update existing message content |
| POST | `/mail/thread/subscribe` | U | J | Subscribe to thread |
| POST | `/mail/thread/unsubscribe` | U | J | Unsubscribe from thread |

## Mailbox (`controllers/mailbox.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/inbox/messages` | U | J | Fetch messages needing action (inbox) |
| POST | `/mail/history/messages` | U | J | Fetch processed messages (history) |
| POST | `/mail/starred/messages` | U | J | Fetch starred messages |

## Attachments (`controllers/attachment.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/attachment/upload` | P | H | Upload attachment to thread |
| POST | `/mail/attachment/delete` | P | J | Delete attachment with ownership check |
| POST | `/mail/attachment/zip` | P | H | Download multiple attachments as ZIP |
| GET | `/mail/attachment/pdf_first_page/<int:attachment_id>` | P | H | Get first page of PDF as image |
| POST | `/mail/attachment/update_thumbnail` | P | J | Update PDF thumbnail |

## Message Reactions (`controllers/message_reaction.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/message/reaction` | P | J | Add or remove emoji reaction |

## Link Preview (`controllers/link_preview.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/link_preview` | P | J | Generate link preview for URL |
| POST | `/mail/link_preview/hide` | P | J | Hide link preview |

## Guest (`controllers/guest.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/guest/update_name` | P | J | Update guest name in channel |

## IM Status (`controllers/im_status.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/set_manual_im_status` | U | J | Set manual IM status (online/away/busy/offline) |

## Translation (`controllers/google_translate.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/message/translate` | U | J | Translate message via Google Translate API |

## WebSocket (`controllers/websocket.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/websocket/update_bus_presence` | P | J | Manually update user presence |

## Webclient (`controllers/webclient.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/action` | P | J | Execute actions and return data (with side effects) |
| POST | `/mail/data` | P | J | Return data without side effects (read-only) |

## Web Manifest (`controllers/webmanifest.py`)

Patches the existing web manifest to add Discuss-specific PWA entries.

---

## Discuss Controllers (`controllers/discuss/`)

### Channels (`discuss/channel.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/discuss/channel/members` | P | J | Fetch channel members |
| POST | `/discuss/channel/update_avatar` | P | J | Update channel avatar |
| POST | `/discuss/channel/messages` | P | J | Fetch messages in channel |
| POST | `/discuss/channel/pinned_messages` | P | J | Fetch pinned messages |
| POST | `/discuss/channel/mark_as_read` | P | J | Mark channel as read up to message |
| POST | `/discuss/channel/set_new_message_separator` | P | J | Set new message separator position |
| POST | `/discuss/channel/notify_typing` | P | J | Notify typing indicator |
| POST | `/discuss/channel/attachments` | P | J | Load channel attachments (paginated) |
| POST | `/discuss/channel/join` | P | J | Join channel |
| POST | `/discuss/channel/sub_channel/create` | P | J | Create sub-thread |
| POST | `/discuss/channel/sub_channel/fetch` | P | J | Fetch sub-threads |
| POST | `/discuss/channel/sub_channel/delete` | U | J | Delete sub-thread |

### RTC / Voice & Video (`discuss/rtc.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/mail/rtc/session/notify_call_members` | P | J | Send P2P notifications between RTC sessions |
| POST | `/mail/rtc/session/update_and_broadcast` | P | J | Update RTC session and broadcast |
| POST | `/mail/rtc/channel/join_call` | P | J | Join voice/video call |
| POST | `/mail/rtc/channel/leave_call` | P | J | Leave voice/video call |
| POST | `/mail/rtc/channel/upgrade_connection` | U | J | Upgrade to SFU connection |
| POST | `/mail/rtc/channel/cancel_call_invitation` | P | J | Cancel RTC call invitation |
| GET | `/mail/rtc/audio_worklet_processor_v2` | P | H | Audio worklet processor JS file |
| POST | `/discuss/channel/ping` | P | J | Ping channel to sync RTC sessions |

### Public Pages (`discuss/public_page.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| GET | `/chat/<string:create_token>` | P | H | Access channel via token |
| GET | `/chat/<string:create_token>/<string:channel_name>` | P | H | Access named channel via token |
| GET | `/meet/<string:create_token>` | P | H | Join video meeting via token |
| GET | `/meet/<string:create_token>/<string:channel_name>` | P | H | Join named meeting via token |
| GET | `/chat/<int:channel_id>/<string:invitation_token>` | P | H | Accept channel invitation |
| GET | `/discuss/channel/<int:channel_id>` | P | H | Access public channel |

### GIF Picker (`discuss/gif.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/discuss/gif/search` | U | J | Search GIFs from Tenor API |
| POST | `/discuss/gif/categories` | U | J | Get GIF categories |
| POST | `/discuss/gif/add_favorite` | U | J | Add GIF to favorites |
| POST | `/discuss/gif/favorites` | U | J | Get user's favorite GIFs |
| POST | `/discuss/gif/remove_favorite` | U | J | Remove GIF from favorites |

### Settings (`discuss/settings.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/discuss/settings/mute` | U | J | Mute channel notifications |
| POST | `/discuss/settings/custom_notifications` | U | J | Set custom notification preferences |

### Search (`discuss/search.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| POST | `/discuss/search` | P | J | Search channels by term |

### Voice (`discuss/voice.py`)

| Method | Route | Auth | Type | Description |
|--------|-------|------|------|-------------|
| GET | `/discuss/voice/worklet_processor` | P | H | Audio processor worklet JS file |

---

## Route Summary

| Category | Routes | Auth Distribution |
|----------|--------|-------------------|
| General mail | 5 | 3P, 2N |
| Thread & messages | 10 | 6U, 4P |
| Mailbox | 3 | 3U |
| Attachments | 5 | 5P |
| Reactions | 1 | 1P |
| Link preview | 2 | 2P |
| Guest | 1 | 1P |
| IM status | 1 | 1U |
| Translation | 1 | 1U |
| WebSocket | 1 | 1P |
| Webclient | 2 | 2P |
| Discuss channels | 12 | 12P |
| Discuss RTC | 8 | 7P, 1U |
| Discuss public | 6 | 6P |
| Discuss GIF | 5 | 5U |
| Discuss settings | 2 | 2U |
| Discuss search | 1 | 1P |
| Discuss voice | 1 | 1P |
| **Total** | **67** | **23U, 42P, 2N** |
