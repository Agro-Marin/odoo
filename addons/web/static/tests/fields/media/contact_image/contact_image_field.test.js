// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryFirst } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

const IMG =
    "iVBORw0KGgoAAAANSUhEUgAAAAUAAAAFCAYAAACNbyblAAAAHElEQVQI12P4//8/w38GIAXDIBKE0DHxgljNBAAO9TXL0Y4OHwAAAABJRU5ErkJggg==";

class Partner extends models.Model {
    name = fields.Char();
    avatar = fields.Binary();
    image_preview = fields.Binary();

    _records = [{ id: 1, name: "rec", avatar: false, image_preview: false }];
}

defineModels([Partner]);

const ARCH = `
    <form>
        <field name="image_preview" invisible="1"/>
        <field name="avatar" widget="contact_image" options="{'preview_image': 'image_preview'}"/>
    </form>`;

/**
 * @param {number} id
 * @param {any} [patch]
 */
async function mountContact(id, patch) {
    Partner._records[0] = {
        id: 1,
        name: "rec",
        avatar: false,
        image_preview: false,
        ...patch,
    };
    await mountView({ resModel: "partner", type: "form", arch: ARCH, resId: id });
    return queryFirst(".o_field_widget[name='avatar'] img");
}

test.tags("desktop");
test("contact_image: empty primary falls back to the base64 preview", async () => {
    const img = await mountContact(1, { avatar: false, image_preview: IMG });
    expect(img.getAttribute("data-src")).toBe(`data:image/png;base64,${IMG}`);
});

test.tags("desktop");
test("contact_image: empty primary AND empty preview shows the placeholder, never data:...false", async () => {
    const img = await mountContact(1, { avatar: false, image_preview: false });
    const src = img.getAttribute("data-src");
    expect(src).toBe("/web/static/img/placeholder.png");
    expect(src).not.toInclude("false");
});

test.tags("desktop");
test("contact_image: a present primary image is shown and counts as valid", async () => {
    const img = await mountContact(1, { avatar: IMG, image_preview: false });
    expect(img.getAttribute("data-src")).toBe(`data:image/png;base64,${IMG}`);
    expect(img.className).not.toInclude("opacity-25-hover");
});

test.tags("desktop");
test("contact_image: a missing image dims the img via the opacity classes", async () => {
    const img = await mountContact(1, { avatar: false, image_preview: false });
    expect(img.className).toInclude("opacity-100");
    expect(img.className).toInclude("opacity-25-hover");
});
