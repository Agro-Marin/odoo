// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    statistics = fields.Json();

    _records = [
        {
            id: 1,
            statistics: [
                { value: 12, label: "Meetings", iconClass: "fa fa-calendar" },
                {
                    value: 3,
                    label: "Opportunities",
                    iconClass: "fa fa-star",
                    tagClass: "o_tag_color_2",
                },
            ],
        },
        { id: 2, statistics: false },
    ];
}

defineModels([Partner]);

const ARCH = `<form><field name="statistics" widget="contact_statistics"/></form>`;

test("contact_statistics renders one badge per entry", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

    expect(".o_field_contact_statistics span.badge").toHaveCount(2);
    expect(queryAllTexts(".o_field_contact_statistics span.badge")).toEqual([
        "12",
        "3",
    ]);
});

test("contact_statistics labels each badge and renders its icon", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

    expect(".o_field_contact_statistics span.badge:eq(0)").toHaveAttribute(
        "title",
        "Meetings",
    );
    expect(".o_field_contact_statistics span.badge:eq(0)").toHaveAttribute(
        "aria-label",
        "Meetings",
    );
    expect(".o_field_contact_statistics span.badge:eq(0) i").toHaveClass([
        "fa",
        "fa-calendar",
    ]);
    expect(".o_field_contact_statistics span.badge:eq(1) i").toHaveClass("fa-star");
});

test("contact_statistics only tags the entries carrying a tagClass", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });

    expect(".o_field_contact_statistics span.badge:eq(0)").not.toHaveClass("o_tag");
    expect(".o_field_contact_statistics span.badge:eq(1)").toHaveClass([
        "o_tag",
        "o_tag_color_2",
    ]);
});

test("contact_statistics renders no badge for an empty value", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 2, arch: ARCH });

    expect(".o_field_contact_statistics").toHaveCount(1);
    expect(".o_field_contact_statistics span.badge").toHaveCount(0);
});
