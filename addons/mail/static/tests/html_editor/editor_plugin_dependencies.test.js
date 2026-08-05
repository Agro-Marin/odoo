import { InputPlugin } from "@html_editor/core/input_plugin";
import { MentionPlugin } from "@mail/views/web/fields/html_composer_message_field/mention_plugin";
import { describe, expect, test } from "@odoo/hoot";

describe("Implicit plugin dependencies", () => {
    test("position as an implicit dependency", async () => {
        for (const P of [MentionPlugin]) {
            // the plugin hooks the "beforeinput_handlers" resource, so
            // InputPlugin must stay in its declared dependencies
            expect(P.dependencies).toInclude(InputPlugin.id);
        }
    });
});
