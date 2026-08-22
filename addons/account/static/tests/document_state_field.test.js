import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Move extends models.Model {
    _name = "move";

    state = fields.Selection({
        selection: [
            ["draft", "Draft"],
            ["sent", "Sent"],
        ],
    });
    message = fields.Char();

    _records = [{ id: 1, state: "sent", message: "The document was rejected." }];
}

defineModels([Move]);

const ARCH = `
    <form>
        <field name="message" invisible="1"/>
        <field name="state" widget="account_document_state" readonly="1"/>
    </form>`;

async function mountState() {
    await mountView({ type: "form", resModel: "move", resId: 1, arch: ARCH });
}

describe("DocumentState message popover", () => {
    test("toggles on the info icon", async () => {
        await mountState();

        await contains(".fa-info-circle").click();
        expect(".account_document_state_popover").toHaveCount(1);

        await contains(".fa-info-circle").click();
        expect(".account_document_state_popover").toHaveCount(0);
    });

    test("reopens after being dismissed by a click away", async () => {
        await mountState();

        await contains(".fa-info-circle").click();
        expect(".account_document_state_popover").toHaveCount(1);

        await click(".o_form_view");
        await animationFrame();
        expect(".account_document_state_popover").toHaveCount(0);

        await contains(".fa-info-circle").click();
        expect(".account_document_state_popover").toHaveCount(1);
    });
});
