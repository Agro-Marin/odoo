/** @odoo-module native */
import { ChatBubblePreview } from "@mail/core/common/chat_bubble";
import { MessageSeenIndicator } from "@mail/discuss/core/common/message_seen_indicator";
ChatBubblePreview.components = { ...ChatBubblePreview.components, MessageSeenIndicator };
