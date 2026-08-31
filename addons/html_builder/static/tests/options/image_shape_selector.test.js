import { dummyBase64Img, setupHTMLBuilder } from "@html_builder/../tests/helpers";
import { describe, expect, test } from "@odoo/hoot";
import { queryFirst } from "@odoo/hoot-dom";
import { contains, onRpc } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

// The Shape row is gated on `isShapeSupported`, which is `!!originalSrc`, and
// the image tool option asks the server about the image before it renders.
async function openShapeSelector() {
    onRpc("/html_editor/get_image_info", () => ({
        original: { id: 1, image_src: dummyBase64Img, mimetype: "image/png" },
    }));
    const { waitSidebarUpdated } = await setupHTMLBuilder(
        `<img src="${dummyBase64Img}" data-original-src="${dummyBase64Img}" data-mimetype="image/png"/>`
    );
    await contains(":iframe img").click();
    await waitSidebarUpdated();
    await contains("[data-label='Shape'] .dropdown").click();
}

test("the devices shape group offers the three half-device silhouettes", async () => {
    await openShapeSelector();
    expect("[data-action-value='html_builder/devices/iphone_front_portrait_half']").toHaveCount(1);
    expect("[data-action-value='html_builder/devices/galaxy_front_portrait_half']").toHaveCount(1);
    expect("[data-action-value='html_builder/devices/macbook_front_half']").toHaveCount(1);
});

test("the devices shape group is laid out in three columns", async () => {
    await openShapeSelector();
    // Each group renders one grid per subgroup, and `basic` has several.
    const devicesGridEl = queryFirst("[data-shape-group-id='devices'] .builder_select_page");
    const basicGridEl = queryFirst("[data-shape-group-id='basic'] .builder_select_page");
    expect(getComputedStyle(devicesGridEl).gridTemplateColumns.split(" ")).toHaveLength(3);
    // The other groups keep the four columns they had.
    expect(getComputedStyle(basicGridEl).gridTemplateColumns.split(" ")).toHaveLength(4);
});
