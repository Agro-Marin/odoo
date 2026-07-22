/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
// Import through the bare `@website/...` specifier, NOT a relative path. This
// module ships in the *test* bundles (`web.assets_tests`,
// `web.assets_unit_tests`) while its target lives in `web.assets_backend`. A
// relative specifier is resolved by the bundler within this bundle, so it
// produces a *second copy* of the class and the patch below lands on an object
// nobody runs: `testMode` stayed false, the `/website/iframefallback` iframe
// was rendered during tests, and every `queryOne("iframe")` in a HOOT builder
// test then matched two elements. The bare specifier goes through the import
// map instead, resolving to the single shared instance the webclient uses.
import { WebsiteBuilderClientAction } from "@website/client_actions/website_preview/website_builder_action";

patch(WebsiteBuilderClientAction.prototype, {
    /**
     * @override
     */
    get testMode() {
        return true;
    },
});
