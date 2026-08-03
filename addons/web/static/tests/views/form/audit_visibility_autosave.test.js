/**
 * The tab-switch auto-save must surface its own failure.
 *
 * requestSave({ errorMode: "silent" }) reports failure by RESOLVING to false,
 * so beforeVisibilityChange has to read the return value; a .catch() chained
 * onto it is unreachable and the failure would be completely silent.
 */

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    hideTab,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { patch } from "@web/core/utils/patch";

class Partner extends models.Model {
    _name = "partner";
    foo = fields.Char();
    _records = [{ id: 1, foo: "yop" }];
}

defineModels([Partner]);

const ARCH = `<form><field name="foo"/></form>`;

async function mountAndDirty() {
    await mountView({ type: "form", resModel: "partner", arch: ARCH, resId: 1 });
    await contains(".o_field_widget[name=foo] input").edit("changed", {
        confirm: false,
    });
    await animationFrame();
}

function captureConsoleWarn() {
    /** @type {string[]} */
    const warnings = [];
    const unpatch = patch(console, {
        warn(...args) {
            warnings.push(args.map(String).join(" "));
        },
    });
    return { warnings, unpatch };
}

/** Counts the save attempts so no assertion can pass by never running. */
function failEverySave() {
    const attempts = { count: 0 };
    onRpc("web_save", () => {
        attempts.count++;
        throw new Error("boom-from-server");
    });
    return attempts;
}

test("a failing tab-switch auto-save is reported", async () => {
    await mountAndDirty();
    const attempts = failEverySave();

    const { warnings, unpatch } = captureConsoleWarn();
    await hideTab();
    await animationFrame();
    unpatch();

    expect(attempts.count).toBe(1, {
        message: "control: the auto-save really was attempted and really failed",
    });
    expect(warnings.filter((w) => w.includes("Auto-save on tab switch"))).toHaveLength(
        1,
        { message: "the failure is reported exactly once" },
    );
});

test("a failing tab-switch auto-save leaves the record dirty and uninterrupted", async () => {
    await mountAndDirty();
    const attempts = failEverySave();

    await hideTab();
    await animationFrame();

    expect(attempts.count).toBe(1, {
        message: "control: the auto-save really was attempted and really failed",
    });
    // the tab is hidden: interrupting with a dialog/notification would be
    // pointless, but the record must stay dirty so the normal guards still fire
    expect(".o_notification").toHaveCount(0, {
        message: "no notification is raised",
    });
    expect(".modal").toHaveCount(0, { message: "no dialog is raised" });
    expect(".o_form_status_indicator_buttons").not.toHaveClass("invisible", {
        message: "record is still unsaved",
    });
});
