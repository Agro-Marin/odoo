import { setupHTMLBuilder } from "@html_builder/../tests/helpers";
import { setSelection } from "@html_editor/../tests/_helpers/selection";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, waitFor } from "@odoo/hoot-dom";
import { contains } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

// Our overlay buttons are a bare `.o_overlay_options`; the text toolbar is the
// only `.o-we-toolbar` on screen, so the two selectors do not overlap here.
test("the overlay buttons step aside while the text toolbar is open", async () => {
    const { getEditor } = await setupHTMLBuilder(
        `<section><div class="test-options-target">test here</div></section>`
    );
    await contains(":iframe .test-options-target").click();
    expect(".o_overlay_options:not(.d-none)").toHaveCount(1);

    const textEl = getEditor().editable.querySelector(".test-options-target");
    setSelection({
        anchorNode: textEl.childNodes[0],
        anchorOffset: 2,
        focusNode: textEl.childNodes[0],
        focusOffset: 5,
    });
    await animationFrame();
    await waitFor(".o-we-toolbar");

    await waitFor(".o_overlay_options.d-none", { timeout: 2000 });
    expect(".o_overlay_options.d-none").toHaveCount(1);
});
