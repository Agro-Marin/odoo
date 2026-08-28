// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
    serverState,
} from "@web/../tests/web_test_helpers";

class Attachment extends models.Model {
    _name = "ir.attachment";
    name = fields.Char();
    _records = [{ id: 7, name: "cover.png" }];
}

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
    cover_id = fields.Many2one({ relation: "ir.attachment" });
    _records = [
        { id: 1, name: "with a cover", cover_id: 7 },
        { id: 2, name: "without one", cover_id: false },
    ];
}

defineModels([Attachment, Partner]);

const ARCH = `<form><field name="cover_id" widget="attachment_image"/></form>`;

test("renders the attachment through the image route at 300x300", async () => {
    await mountView({ type: "form", resModel: "res.partner", resId: 1, arch: ARCH });
    expect(".o_attachment_image").toHaveCount(1);
    expect(".o_attachment_image img").toHaveAttribute(
        "data-src",
        "/web/image/7/300x300?unique=1",
    );
});

test("renders the wrapper but no image when the field is empty", async () => {
    await mountView({ type: "form", resModel: "res.partner", resId: 2, arch: ARCH });
    expect(".o_attachment_image").toHaveCount(1);
    expect(".o_attachment_image img").toHaveCount(0);
});

test("no tooltip outside debug mode", async () => {
    await mountView({ type: "form", resModel: "res.partner", resId: 1, arch: ARCH });
    expect(queryOne(".o_attachment_image img").hasAttribute("title")).toBe(false);
});

test("the attachment name is a tooltip in debug mode", async () => {
    serverState.debug = "1";
    await mountView({ type: "form", resModel: "res.partner", resId: 1, arch: ARCH });
    expect(".o_attachment_image img").toHaveAttribute("title", "cover.png");
});
