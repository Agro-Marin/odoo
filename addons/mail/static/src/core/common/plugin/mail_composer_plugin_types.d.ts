import type { EditorConfig } from "@html_editor/editor";
import type { Composer } from "@mail/core/common/composer";
import "@mail/core/common/plugin/mail_composer_plugin";

declare module "@mail/core/common/plugin/mail_composer_plugin" {
    interface MailComposerPlugin {
        config: EditorConfig &
            Pick<
                Composer["wysiwygConfig"],
                "composerPluginDependencies" | "placeholder"
            >;
    }
}
