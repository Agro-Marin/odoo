import { expect, getFixture, test } from "@odoo/hoot";
import { mockFetch } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { htmlToCanvas } from "@point_of_sale/app/services/render_service";
import { allowTranslations, mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";

definePosModels();
odoo.pos_session_id = 1;

test("test the render service", async () => {
    class ComponentToBeRendered extends Component {
        static props = ["name"];
        static template = xml`
            <div> It's me, <t t-esc="props.name" />! </div>
        `;
    }

    allowTranslations();
    const comp = await mountWithCleanup("none");
    const renderedComp = await comp.env.services.renderer.toHtml(
        ComponentToBeRendered,
        {
            name: "Mario",
        },
    );
    expect(renderedComp).toHaveOuterHTML("<div> It's me, Mario! </div>");
});

test("htmlToCanvas", async () => {
    mockFetch(() => "");
    const target = getFixture();
    const node = document.createElement("div");
    node.classList.add("render-container");
    target.appendChild(node);

    const asciiChars = Array.from({ length: 256 }, (_, i) =>
        String.fromCharCode(i),
    ).join("");
    node.textContent = asciiChars;

    let canvas = null;
    try {
        canvas = await htmlToCanvas(node, { addClass: "pos-receipt-print" });
    } catch (error) {
        if (error.constructor.name !== "Event") {
            throw error;
        }
    }
    expect(canvas).not.toBe(null, {
        message: "htmlToCanvas should work with all ascii characters",
    });
});
