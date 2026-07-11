// @ts-check

/**
 * @module tests/views/form/button_box
 *
 * Pins the ButtonBox per-breakpoint visible-button budget:
 * ``[0, 0, 4, 5, 7, 8]`` indexed by SIZES (XS SM MD LG XL XXL), monotonic so
 * growing the screen never hides stat buttons into the "More" dropdown.
 */

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import {
    defineModels,
    fields,
    mockService,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";
import { SIZES } from "@web/ui/block/ui_service";

class Partner extends models.Model {
    name = fields.Char();
    _records = [{ id: 1, name: "first" }];
}

const { ResCompany, ResPartner, ResUsers } = webModels;

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

const NB_BUTTONS = 9;

/**
 * @param {number} size
 */
function mockUiSize(size) {
    const bus = new EventBus();
    /** @type {any} */ (mockService)("ui", (env) => {
        Object.defineProperty(env, "isSmall", {
            value: size <= SIZES.SM,
        });
        return {
            bus,
            get size() {
                return size;
            },
            get isSmall() {
                return size <= SIZES.SM;
            },
        };
    });
}

async function mountFormWithStatButtons() {
    let buttons = "";
    for (let i = 0; i < NB_BUTTONS; i++) {
        buttons += `<button class="oe_stat_button" id="btn${i}">Button ${i}</button>`;
    }
    await mountView({
        resModel: "partner",
        type: "form",
        arch: `<form><sheet><div name="button_box">${buttons}</div></sheet></form>`,
        resId: 1,
    });
}

describe("visible-button budget per ui.size", () => {
    // With 9 visible stat buttons (always above every budget), the box shows
    // budget - 1 buttons plus the "More" dropdown.
    const EXPECTED = [
        ["XS", SIZES.XS, 0],
        ["SM", SIZES.SM, 0],
        ["MD", SIZES.MD, 3],
        ["LG", SIZES.LG, 4],
        ["XL", SIZES.XL, 6],
        ["XXL", SIZES.XXL, 7],
    ];
    for (const [label, size, expectedVisible] of EXPECTED) {
        test(`${label} shows ${expectedVisible} buttons plus More`, async () => {
            mockUiSize(/** @type {number} */ (size));
            await mountFormWithStatButtons();
            expect(`.o-form-buttonbox > button.oe_stat_button`).toHaveCount(
                /** @type {number} */ (expectedVisible),
            );
            expect(`.o-form-buttonbox .o_button_more`).toHaveCount(1);
        });
    }

    test("XXL shows all buttons without More when within budget", async () => {
        mockUiSize(SIZES.XXL);
        await mountView({
            resModel: "partner",
            type: "form",
            arch: `<form><sheet><div name="button_box">
                <button class="oe_stat_button" id="btn0">B0</button>
                <button class="oe_stat_button" id="btn1">B1</button>
                <button class="oe_stat_button" id="btn2">B2</button>
                <button class="oe_stat_button" id="btn3">B3</button>
                <button class="oe_stat_button" id="btn4">B4</button>
                <button class="oe_stat_button" id="btn5">B5</button>
                <button class="oe_stat_button" id="btn6">B6</button>
                <button class="oe_stat_button" id="btn7">B7</button>
            </div></sheet></form>`,
            resId: 1,
        });
        expect(`.o-form-buttonbox > button.oe_stat_button`).toHaveCount(8);
        expect(`.o-form-buttonbox .o_button_more`).toHaveCount(0);
    });
});
