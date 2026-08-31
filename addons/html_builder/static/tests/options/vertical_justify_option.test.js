import { addBuilderPlugin, setupHTMLBuilder } from "@html_builder/../tests/helpers";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { SNIPPET_SPECIFIC_NEXT } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { expect, test, describe } from "@odoo/hoot";
import { queryAllAttributes } from "@odoo/hoot-dom";
import { xml } from "@odoo/owl";
import { contains } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

test("the vertical alignment option sits with the layout options, not after everything", async () => {
    // Sequenced after VERTICAL_ALIGNMENT but before END, so the assertion tells
    // the two candidate positions apart.
    addBuilderPlugin(
        class extends Plugin {
            static id = "testLaterOption";
            resources = {
                builder_options: withSequence(
                    SNIPPET_SPECIFIC_NEXT,
                    class extends BaseOptionComponent {
                        static selector = ".s_masonry_block .o_grid_item";
                        static template = xml`<BuilderRow label="'Later'">Z</BuilderRow>`;
                    }
                ),
            };
        }
    );
    await setupHTMLBuilder(
        `<section class="s_masonry_block"><div class="o_grid_item">b</div></section>`
    );
    await contains(":iframe .o_grid_item").click();

    expect(queryAllAttributes(".options-container .hb-row", "data-label")).toEqual([
        "Vert. Alignment",
        "Later",
    ]);
});
