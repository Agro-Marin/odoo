import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

// The colour-combination preview is styled by CSS alone, so the contract is
// checked against a bare fixture rather than through a component: the previews
// that use it live in `website` (the Color Presets rows), and the one in this
// module only ever renders an `h1`.
class ColorCombinationPreview extends Component {
    static props = {};
    static template = xml`
        <div class="o_cc_preview_wrapper"
             style="--hb-cp-o-cc1-text: rgb(1, 2, 3); --hb-cp-o-cc1-headings: rgb(4, 5, 6);">
            <div class="o_cc1">
                <h1>Title</h1>
                <h3>Title</h3>
            </div>
        </div>`;
}

test("every heading level in a colour combination preview takes the headings colour", async () => {
    await mountWithCleanup(ColorCombinationPreview);
    expect("h1").toHaveStyle({ color: "rgb(4, 5, 6)" });
    expect("h3").toHaveStyle({ color: "rgb(4, 5, 6)" });
});
