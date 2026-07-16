import { setupEditor } from "@html_editor/../tests/_helpers/editor";
import { cleanLinkArtifacts } from "@html_editor/../tests/_helpers/format";
import { getContent } from "@html_editor/../tests/_helpers/selection";
import { pasteText } from "@html_editor/../tests/_helpers/user_actions";
import { Plugin } from "@html_editor/plugin";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { HeaderOptionPlugin } from "@website/builder/plugins/options/header/header_option_plugin";

defineMailModels();
class FakeCustomizeWebsitePlugin extends Plugin {
    static id = "customizeWebsite";
}

class FakeMenuDataPlugin extends Plugin {
    static id = "menuDataPlugin";
}

describe("Navbar Contact Us button", () => {
    test("should keep the unremovable Contact Us button on paste", async () => {
        const { el, editor } = await setupEditor(
            `<div id="o_main_nav">
                <div class="oe_structure oe_structure_solo o_editable">
                    <section class="oe_unremovable" contenteditable="false">
                        <div contenteditable="true">
                            a[a<a class="btn btn-primary oe_unremovable" href="/contactus">Contact Us</a>a]a
                        </div>
                    </section>
                </div>
            </div>`,
            {
                props: { iframe: true },
                config: {
                    Plugins: [
                        ...MAIN_PLUGINS,
                        FakeCustomizeWebsitePlugin,
                        FakeMenuDataPlugin,
                        HeaderOptionPlugin,
                    ],
                },
            },
        );
        pasteText(editor, "should keep unremovable");
        expect(cleanLinkArtifacts(getContent(el))).toBe(
            `<p data-selection-placeholder=""><br></p><div id="o_main_nav">
                <div class="oe_structure oe_structure_solo o_editable">
                    <section class="oe_unremovable" contenteditable="false">
                        <div contenteditable="true">
                            ashould keep unremovable<a class="btn btn-primary oe_unremovable" href="/contactus"></a>[]a
                        </div>
                    </section>
                </div>
            </div><p data-selection-placeholder=""><br></p>`,
        );
    });
});
