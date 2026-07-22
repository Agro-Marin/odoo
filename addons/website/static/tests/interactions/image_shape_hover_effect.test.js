import { describe, expect, test } from "@odoo/hoot";
import { hover, queryOne } from "@odoo/hoot-dom";
import { advanceTime } from "@odoo/hoot-mock";
import {
    setupInteractionWhiteList,
    startInteractions,
} from "@web/../tests/public/helpers";
import { onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { onceAllImagesLoaded } from "@website/utils/images";

setupInteractionWhiteList("website.image_shape_hover_effect");

describe.current.tags("interaction_dev");

test.tags("desktop");
test("image_shape_hover_effect changes image on enter & leave", async () => {
    patchWithCleanup(Image.prototype, {
        set onload(fn) {
            super.onload = fn;
            setTimeout(() => super.onload());
        },
    });
    // Registered before the markup is injected: the <img> below starts
    // fetching as soon as it lands in the fixture, so mocking the route
    // afterwards leaves that first request unmocked. It then fires an `error`
    // event that HOOT reports as an unverified error, which is why this test
    // failed inside a full run and passed on its own.
    onRpc(
        "/web/image/384-8a55a748/s_banner_3.svg",
        () =>
            `<svg viewBox="0 0 300 100" width="500px"><g id="hoverEffects"><animate values="a=1;b=2"><rect width="100%" fill="red" height="100%" /></animate></g></svg>`,
    );
    const { core } = await startInteractions(`
        <div id="wrapwrap">
            <img class="img img-fluid mx-auto o_we_image_cropped o_animate_on_hover rounded-circle rounded"
                src="/web/image/384-8a55a748/s_banner_3.svg" alt=""
                data-mimetype="image/svg+xml" data-attachment-id="276" data-original-id="276"
                data-original-src="/website/static/src/img/snippets_demo/s_banner_3.jpg"
                data-mimetype-before-conversion="image/jpeg"
                data-shape="html_builder/geometric/geo_door" data-file-name="s_banner_3.svg"
                data-shape-colors=";;;;" data-format-mimetype="image/jpeg"
                data-x="160" data-y="0"
                data-width="640" data-height="640"
                data-scale-x="1" data-scale-y="1"
                data-aspect-ratio="1/1"
                data-hover-effect="dolly_zoom"
                data-hover-effect-color="rgba(0, 0, 0, 0)"
                data-hover-effect-intensity="20"/>
            <div class="not_image">Not the image</div>
        </div>
    `);
    expect(core.interactions).toHaveLength(1);
    // Wait for the <img> to *settle*, not to succeed. Its `src` is a real
    // route on the test server, which answers 200 with a body Chrome cannot
    // decode, so the element always ends up in `error`. `onceAllImagesLoaded`
    // rejects with that event -- but only when it is called while the request
    // is still in flight; once the request has settled `imgEl.complete` is
    // true and it returns immediately. That timing is what decided whether
    // this test passed, hence green alone and red inside a full run. The
    // assertions below are about the hover swap, so either outcome is fine.
    await onceAllImagesLoaded(queryOne("#wrapwrap")).catch(() => {});
    const imgEl = queryOne("img");
    const baseSrc = imgEl.getAttribute("src");
    expect(imgEl).toHaveAttribute("src", "/web/image/384-8a55a748/s_banner_3.svg");
    await hover(imgEl);
    await advanceTime(1);
    const altSrc = imgEl.getAttribute("src");
    expect(imgEl).not.toHaveAttribute("src", baseSrc);
    await hover(".not_image");
    await advanceTime(1);
    expect(imgEl).not.toHaveAttribute("src", baseSrc);
    expect(imgEl).not.toHaveAttribute("src", altSrc);
});
