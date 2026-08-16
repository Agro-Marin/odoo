import { InputPlugin } from "@html_editor/core/input_plugin";
import { MentionPlugin } from "@mail/views/web/fields/html_composer_message_field/mention_plugin";
import { describe, expect, test } from "@odoo/hoot";

describe("Implicit plugin dependencies", () => {
    test("position as an implicit dependency", async () => {
        for (const P of [MentionPlugin]) {
            expect(P.dependencies).toInclude(InputPlugin.id);
        }
    });
});
