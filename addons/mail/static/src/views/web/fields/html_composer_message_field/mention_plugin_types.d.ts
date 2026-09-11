import type { EditorConfig } from "@html_editor/editor";
import "@mail/views/web/fields/html_composer_message_field/mention_plugin";
declare module "@mail/views/web/fields/html_composer_message_field/mention_plugin" {
    interface MentionPlugin {
        config: EditorConfig & { thread: import("models").Thread };
    }
}
