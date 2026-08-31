import { expect, test, describe, globals } from "@odoo/hoot";
import { contains, dataURItoBlob, onRpc } from "@web/../tests/web_test_helpers";
import { dummyBase64Img, dummyCORSSrc, setupCORSProtectedImg, setupHTMLBuilder } from "@html_builder/../tests/helpers";

describe.current.tags("desktop");

test("Size should not be displayed on CORS protected images", async () => {
    setupCORSProtectedImg();
    // The next line is needed in order to correctly run the test without the
    // fix.
    onRpc("/web/image/__odoo__unknown__src__/", () => dataURItoBlob(dummyBase64Img));
    const { waitSidebarUpdated } = await setupHTMLBuilder(`<img src="${dummyCORSSrc}">`);
    await contains(":iframe img").click();
    await waitSidebarUpdated();
    expect(".o-hb-image-size-info").toHaveCount(0);
});

test("An image shape whose drawing animates offers its animation speed", async () => {
    // The shape SVG and the attachment lookup are ordinary server round trips;
    // serve the shape directory from the real server and answer the lookup with
    // the fixture's own image, so the option renders the way it does in
    // production.
    onRpc("/html_builder/static/image_shapes/*", (request) => {
        const url = new URL(request.url);
        return globals.fetch.call(window, url.pathname + url.search);
    });
    onRpc("/html_editor/get_image_info", () => ({
        attachment: { id: 1 },
        original: { id: 1, image_src: dummyBase64Img, mimetype: "image/png" },
    }));

    const { waitSidebarUpdated } = await setupHTMLBuilder(
        `<img src="${dummyBase64Img}"
              data-attachment-id="1" data-original-id="1"
              data-original-src="${dummyBase64Img}"
              data-mimetype-before-conversion="image/png"
              data-shape="html_builder/solid/solid_blob_5">`
    );
    await contains(":iframe img").click();
    await waitSidebarUpdated();
    expect("[data-action-id='setImageShapeSpeed']").toHaveCount(1);
});
