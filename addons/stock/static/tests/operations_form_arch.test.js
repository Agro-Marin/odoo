import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { FormCompiler } from "@web/views/form";

class ProbeWidget extends Component {
    static template = xml`<button class="probe-button">Probe</button>`;
    static props = ["*"];
}
registry.category("view_widgets").add("stock_probe_widget", { component: ProbeWidget });

class Move extends models.Model {
    _name = "move";

    name = fields.Char();
    picked = fields.Boolean();

    _records = [{ id: 1, name: "a move", picked: false }];
}
defineModels([Move]);
defineMailModels();

const POSITIONING_CLASSES = [
    "dropdown",
    "dropup",
    "dropend",
    "dropstart",
    "btn-group",
    "btn-group-vertical",
];

function compileArch(arch) {
    const doc = new DOMParser().parseFromString(arch, "text/xml");
    return new FormCompiler({ root: doc.documentElement }).compile("root", {})
        .outerHTML;
}

describe("compiler: a positioning class must not swallow an arch node", () => {
    for (const positioning of ["", ...POSITIONING_CLASSES]) {
        const label = positioning || "(no positioning class)";

        test(`widget survives "${label}"`, () => {
            const out = compileArch(
                `<form><div class="d-flex">` +
                    `<widget name="stock_probe_widget" class="btn btn-link ${positioning}" widget_id="w1"/>` +
                    `</div></form>`,
            );
            expect(out).toInclude("<Widget");
            expect(out).not.toInclude("<widget ");
        });

        test(`field survives "${label}"`, () => {
            const out = compileArch(
                `<form><field name="name" class="${positioning}"/></form>`,
            );
            expect(out).toInclude("<Field");
            expect(out).not.toInclude("<field ");
        });

        test(`action button survives "${label}"`, () => {
            const out = compileArch(
                `<form><button name="do_thing" type="object" string="Probe" ` +
                    `class="${positioning}"/></form>`,
            );
            expect(out).toInclude("<ViewButton");
            expect(out).not.toInclude("<button ");
        });
    }
});

describe("rendering: the same, end to end through mountView", () => {
    for (const positioning of ["", ...POSITIONING_CLASSES]) {
        const label = positioning || "(no positioning class)";

        test(`widget renders with "${label}"`, async () => {
            await mountView({
                type: "form",
                resModel: "move",
                resId: 1,
                arch:
                    `<form><div class="d-flex">` +
                    `<widget name="stock_probe_widget" class="btn btn-link ${positioning}"/>` +
                    `</div></form>`,
            });
            expect(".o_widget_stock_probe_widget button.probe-button").toHaveCount(1);
            expect("widget").toHaveCount(0);
        });

        test(`field renders with "${label}"`, async () => {
            await mountView({
                type: "form",
                resModel: "move",
                resId: 1,
                arch: `<form><field name="name" class="${positioning}"/></form>`,
            });
            expect(".o_field_widget[name=name]").toHaveCount(1);
            expect("field").toHaveCount(0);
        });
    }
});
