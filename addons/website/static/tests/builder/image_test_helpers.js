import { before, globals } from "@odoo/hoot";
import { onRpc } from "@web/../tests/web_test_helpers";

/**
 * Serve a route from the real server instead of the mock one. ``route`` may be
 * a glob (``*``), in which case the *requested* URL is forwarded rather than
 * the pattern itself.
 */
function onRpcReal(route) {
    onRpc(route, (request) => {
        const url = new URL(request.url);
        return globals.fetch.call(window, url.pathname + url.search);
    });
}

export const testImgSrc = "/web/image/website.s_text_image_default_image";

export const testImg = `
    <img src='/web/image/website.s_text_image_default_image'
        data-attachment-id="1" data-original-id="1"
        data-original-src="/website/static/src/img/snippets_demo/s_text_image.webp"
        data-mimetype-before-conversion="image/webp"
        >
    `;

export const testGifImgSrc = "/web/image/456-test/test.gif";

export const testGifImg = `
    <img src='/web/image/456-test/test.gif'>
    `;

export function mockImageRequests() {
    before(() => {
        onRpc("/html_editor/get_image_info", async (data) => {
            const body = await data.body.getReader().read();
            const { src } = JSON.parse(new TextDecoder().decode(body.value)).params;
            if (src === testGifImgSrc) {
                return {
                    attachment: {
                        id: 456,
                    },
                    original: {
                        id: 456,
                        image_src:
                            "/website/static/src/img/snippets_options/header_effect_fade_out.gif",
                        mimetype: "image/gif",
                    },
                };
            }
            return {
                attachment: {
                    id: 1,
                },
                original: {
                    id: 1,
                    image_src:
                        "/website/static/src/img/snippets_demo/s_text_image.webp",
                    mimetype: "image/webp",
                },
            };
        });
        // The shape SVGs are ordinary static files: pass the whole directory
        // through instead of whitelisting them one by one. The enumeration this
        // replaces meant any test using a shape nobody had listed died on
        // "Unimplemented server route" (e.g. devices/iphone_front_portrait.svg).
        onRpcReal("/html_builder/static/image_shapes/*");
        onRpcReal("/web/image/website.s_text_image_default_image");
        onRpcReal("/website/static/src/img/snippets_demo/s_text_image.webp");
        onRpcReal(
            "/website/static/src/img/snippets_options/header_effect_fade_out.gif",
        );
        onRpcReal("/web/image/123/transparent.png");
        onRpcReal("/website/static/src/svg/hover_effects.svg");
        onRpcReal("/html_builder/static/image_shapes/geometric/geo_square.svg");
    });
}
