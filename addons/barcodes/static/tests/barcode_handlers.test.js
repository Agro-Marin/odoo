/** @odoo-module native */
/**
 * Regression tests for what a scan is allowed to do to the page.
 *
 * A barcode is untrusted input: it comes off a label somebody else printed.
 */

import { BarcodeHandlerField } from "@barcodes/barcode_handler_field";
import { barcodeService } from "@barcodes/barcode_service";
import { beforeEach, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    mockService,
    models,
    mountView,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

class Product extends models.Model {
    name = fields.Char({ string: "Product name" });
    handler = fields.Char({ string: "Handler" });
    _records = [{ id: 1, name: "Large Cabinet" }];
}
defineModels([Product]);

beforeEach(() => {
    patchWithCleanup(barcodeService, { maxTimeBetweenKeysInMs: 0 });
});

test.tags("desktop");
test("a barcode cannot inject a selector and click unrelated buttons", async () => {
    mockService("action", {
        doActionButton: (data) => expect.step(data.name),
    });
    const view = await mountView({
        type: "form",
        resModel: "product",
        resId: 1,
        arch: `<form>
                <header>
                    <button name="intended" string="Intended" type="object" barcode_trigger="DOIT"/>
                    <button name="unrelated" string="Unrelated" type="object" class="o_danger"/>
                </header>
            </form>`,
    });

    // `[barcode_trigger=DOIT], [class]` is a *valid* selector, so a try/catch
    // around querySelectorAll would not have stopped it: it simply matches
    // more than the trigger it names.
    view.env.services.barcode.scan("OBTDOIT], [class");
    await animationFrame();
    expect.verifySteps([]);

    // ...and the honest trigger still works.
    view.env.services.barcode.scan("OBTDOIT");
    await animationFrame();
    expect.verifySteps(["intended"]);
});

test.tags("desktop");
test("an unmapped OCD command reports itself instead of doing nothing", async () => {
    mockService("notification", {
        add: (message, options) => expect.step(`${options.type}:${options.title}`),
    });
    const view = await mountView({
        type: "form",
        resModel: "product",
        resId: 1,
        arch: `<form><field name="name"/></form>`,
    });

    // OCDEDIT was mapped to `.o_form_button_edit`, a selector that has matched
    // nothing since the form view lost its explicit edit mode. Scanning it was
    // a silent no-op rather than an unknown command.
    view.env.services.barcode.scan("OCDEDIT");
    await animationFrame();
    expect.verifySteps(["danger:Unknown barcode command"]);
});

test.tags("desktop");
test("a barcode_handler field ignores scans aimed at another active element", async () => {
    // Assert on what the record actually holds: entering the handler proves
    // nothing, since the guard is inside it.
    let field;
    patchWithCleanup(BarcodeHandlerField.prototype, {
        setup() {
            super.setup();
            field = this;
        },
    });
    const view = await mountView({
        type: "form",
        resModel: "product",
        resId: 1,
        arch: `<form>
                <field name="name"/>
                <field name="handler" widget="barcode_handler"/>
            </form>`,
    });
    const ui = view.env.services.ui;
    const stored = () => field.props.record.data[field.props.name];

    view.env.services.barcode.scan("12345");
    await animationFrame();
    expect(stored()).toBe("12345");

    // With a dialog owning the UI, the form behind it must not take the scan
    // -- it would swallow the barcode and leave the record dirty.
    const dialog = document.createElement("div");
    document.body.appendChild(dialog);
    ui.activateElement(dialog);
    view.env.services.barcode.scan("67890");
    await animationFrame();
    expect(stored()).toBe("12345");

    // ...and it takes scans again once the dialog closes.
    ui.deactivateElement(dialog);
    view.env.services.barcode.scan("13579");
    await animationFrame();
    expect(stored()).toBe("13579");
    dialog.remove();
});

test.tags("desktop");
test("cleanBarcode no longer rewrites scanned content", async () => {
    // It used to strip /Alt|Shift|Control/g out of the assembled string, so a
    // product coded "ShiftKnob" scanned as "Knob". Modifier keydowns are now
    // dropped before they reach the buffer, so there is nothing to strip.
    for (const barcode of ["ShiftKnob", "ControlValve", "Altima", "ALTIMA", "cobalt"]) {
        expect(barcodeService.cleanBarcode(barcode)).toBe(barcode);
    }
});
