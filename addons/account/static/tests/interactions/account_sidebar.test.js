import { describe, expect, test } from "@odoo/hoot";
import {
    setupInteractionWhiteList,
    startInteractions,
} from "@web/../tests/public/helpers";

setupInteractionWhiteList("account.account_sidebar");

describe.current.tags("interaction_dev");

/** @param {string} [inner] */
function portal(inner = "") {
    return `
        <div id="wrapwrap">
            <div class="row o_portal_invoice_sidebar">
                <div id="invoice_content">${inner}</div>
            </div>
        </div>`;
}

describe("AccountSidebar iframe sizing", () => {
    test("starts without the report iframe", async () => {
        const { core } = await startInteractions(portal());

        expect(core.interactions).toHaveLength(1);
    });

    test("survives an iframe whose document carries no #wrapwrap", async () => {
        const { core } = await startInteractions(
            portal(
                `<iframe id="invoice_html" srcdoc="&lt;p&gt;no wrapwrap&lt;/p&gt;"/>`,
            ),
        );

        expect(core.interactions).toHaveLength(1);
        const [interaction] = core.interactions;
        interaction.interaction.updateIframeSize();
        expect(".o_portal_invoice_sidebar").toHaveCount(1);
    });
});
