// @ts-check

// Direct, mount-free unit tests for the DateTimePickerController extracted from
// the datetime picker service (audit F39). These exercise input DOM sync,
// popover open/close and value marking/applying WITHOUT a full component mount —
// the whole point of the extraction — by driving the controller methods against
// a fake popover and plain <input> elements.

import { beforeEach, expect, getFixture, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { DateTimePickerController } from "@web/components/datetime/datetime_picker_service";
import { localization } from "@web/core/l10n/localization";
import { luxon } from "@web/core/l10n/luxon";

const { DateTime } = luxon;

beforeEach(() => {
    patchWithCleanup(localization, {
        dateFormat: "MM/dd/yyyy",
        dateTimeFormat: "MM/dd/yyyy HH:mm:ss",
    });
});

/**
 * Fake popover mirroring the makePopover contract used by the controller:
 * open()/close()/isOpen, and calling the provided onClose on close (as the real
 * popover service does when the popover is removed).
 *
 * @param {{ onClose?: () => any }} options
 */
function makeFakePopover(options) {
    let open = false;
    return {
        lastTarget: /** @type {any} */ (null),
        lastProps: /** @type {any} */ (null),
        open(/** @type {any} */ target, /** @type {any} */ props) {
            this.lastTarget = target;
            this.lastProps = props;
            open = true;
        },
        close() {
            if (open) {
                open = false;
                options.onClose?.();
            }
        },
        get isOpen() {
            return open;
        },
    };
}

/**
 * Builds a controller wired to a fake popover, a fake env and a caller-owned
 * registry, so no popover service / component mount is needed.
 *
 * @param {Record<string, any>} [params]
 * @param {{ dateTimePickerList?: Set<any> }} [opts]
 */
function createController(params = {}, opts = {}) {
    const dateTimePickerList = opts.dateTimePickerList || new Set();
    const env = { isSmall: false };
    /** @type {any} */
    let popover;
    const fullParams = {
        createPopover: (/** @type {any} */ _component, /** @type {any} */ options) => {
            popover = makeFakePopover(options);
            return popover;
        },
        ...params,
    };
    const controller = new DateTimePickerController(
        fullParams,
        env,
        /* popoverService */ null,
        dateTimePickerList,
    );
    return { controller, dateTimePickerList, getPopover: () => popover };
}

/**
 * Creates <input> elements attached to the hoot fixture (so they are connected).
 *
 * @param {number} count
 */
function makeInputs(count = 1) {
    const fixture = getFixture();
    const inputs = [];
    for (let i = 0; i < count; i++) {
        const input = document.createElement("input");
        input.type = "text";
        fixture.appendChild(input);
        inputs.push(input);
    }
    return inputs;
}

test("updateInput formats a value into the input and clears on falsy", () => {
    const [input] = makeInputs(1);
    const { controller } = createController({
        getInputs: () => [input],
        pickerProps: { type: "date", value: false },
    });

    controller.updateInput(input, DateTime.fromSQL("2023-06-06"));
    expect(input.value).toBe("06/06/2023");

    controller.updateInput(input, false);
    expect(input.value).toBe("");
});

test("enable() syncs inputs and wires listeners; disable removes them", () => {
    const [input] = makeInputs(1);
    const { controller } = createController({
        getInputs: () => [input],
        pickerProps: { type: "date", value: DateTime.fromSQL("2023-06-06") },
    });

    const removeListeners = controller.enable();
    // Input synced from the current value.
    expect(input.value).toBe("06/06/2023");
    expect(controller.disableListeners).toBe(removeListeners);

    // A "click" now opens the popover through the wired listener.
    input.dispatchEvent(new Event("click"));
    expect(controller.isOpen()).toBe(true);
    controller.saveAndClose();
    expect(controller.isOpen()).toBe(false);

    // Teardown detaches the handlers: a click no longer opens.
    removeListeners();
    expect(controller.disableListeners).toBe(null);
    input.dispatchEvent(new Event("click"));
    expect(controller.isOpen()).toBe(false);
});

test("updateValueFromInputs parses inputs into state and notifies onChange", () => {
    const [input] = makeInputs(1);
    const onChange = (/** @type {any} */ v) =>
        expect.step(`change:${v ? v.toISODate() : v}`);
    const { controller } = createController({
        getInputs: () => [input],
        onChange,
        pickerProps: { type: "date", value: false },
    });

    input.value = "07/07/2023";
    controller.updateValueFromInputs();

    expect(controller.pickerProps.value.toISODate()).toBe("2023-07-07");
    expect.verifySteps(["change:2023-07-07"]);

    // An unparseable input restores the current value (no change fired).
    input.value = "not a date";
    controller.updateValueFromInputs();
    expect(controller.pickerProps.value.toISODate()).toBe("2023-07-07");
    expect(input.value).toBe("07/07/2023");
    expect.verifySteps([]);
});

test("open()/close() drive the popover with the reactive pickerProps", () => {
    const [input] = makeInputs(1);
    const { controller, getPopover } = createController({
        target: input,
        getInputs: () => [input],
        pickerProps: { type: "date", value: false },
    });

    expect(controller.isOpen()).toBe(false);

    controller.open(0);
    expect(controller.isOpen()).toBe(true);
    expect(controller.pickerProps.focusedDateIndex).toBe(0);
    // Popover opened on the target with the controller's own reactive props.
    expect(getPopover().lastTarget).toBe(input);
    expect(getPopover().lastProps.pickerProps).toBe(controller.pickerProps);

    controller.picker.close();
    expect(controller.isOpen()).toBe(false);
});

test("open() closes other pickers sharing the service registry", () => {
    const list = new Set();
    const [inputA] = makeInputs(1);
    const [inputB] = makeInputs(1);
    const a = createController(
        {
            target: inputA,
            getInputs: () => [inputA],
            pickerProps: { type: "date", value: false },
        },
        { dateTimePickerList: list },
    );
    const b = createController(
        {
            target: inputB,
            getInputs: () => [inputB],
            pickerProps: { type: "date", value: false },
        },
        { dateTimePickerList: list },
    );

    a.controller.open(0);
    expect(a.controller.isOpen()).toBe(true);

    // Opening B must close A (open() iterates the shared registry first).
    b.controller.open(0);
    expect(b.controller.isOpen()).toBe(true);
    expect(a.controller.isOpen()).toBe(false);
});

test("apply() fires onApply only when the value actually changed", async () => {
    const [input] = makeInputs(1);
    const onApply = (/** @type {any} */ v) =>
        expect.step(`apply:${v ? v.toISODate() : v}`);
    const { controller } = createController({
        getInputs: () => [input],
        onApply,
        pickerProps: { type: "date", value: false },
    });

    // First real change applies.
    controller.pickerProps.value = DateTime.fromSQL("2023-07-07");
    await controller.apply();
    expect.verifySteps(["apply:2023-07-07"]);

    // Same value again: deduped, no apply.
    await controller.apply();
    expect.verifySteps([]);

    // New value applies again.
    controller.pickerProps.value = DateTime.fromSQL("2023-08-08");
    await controller.apply();
    expect.verifySteps(["apply:2023-08-08"]);
});

test("onSelect marks the value and applies for a single date picker", async () => {
    const [input] = makeInputs(1);
    const onChange = (/** @type {any} */ v) =>
        expect.step(`change:${v ? v.toISODate() : v}`);
    const onApply = (/** @type {any} */ v) =>
        expect.step(`apply:${v ? v.toISODate() : v}`);
    const { controller } = createController({
        getInputs: () => [input],
        onChange,
        onApply,
        pickerProps: { type: "date", value: false },
    });

    // Simulate the picker component selecting a day (popover closed).
    await controller.pickerProps.onSelect(DateTime.fromSQL("2023-09-09"), "date");

    expect(controller.pickerProps.value.toISODate()).toBe("2023-09-09");
    expect.verifySteps(["change:2023-09-09", "apply:2023-09-09"]);
});

test("dispose() tears down: closes popover, removes listeners, releases registry, guards apply (F1)", async () => {
    const list = new Set();
    const [input] = makeInputs(1);
    const onApply = (/** @type {any} */ v) => expect.step(`apply:${v}`);
    const { controller } = createController(
        {
            target: input,
            getInputs: () => [input],
            onApply,
            pickerProps: { type: "date", value: false },
        },
        { dateTimePickerList: list },
    );

    controller.enable();
    controller.open(0);
    expect(controller.isOpen()).toBe(true);
    expect(list.has(controller.picker)).toBe(true);

    controller.dispose();

    expect(controller.destroyed).toBe(true);
    expect(controller.isOpen()).toBe(false);
    expect(controller.disableListeners).toBe(null);
    expect(list.has(controller.picker)).toBe(false);

    // After teardown, apply must be a no-op even with a pending value change.
    controller.pickerProps.value = DateTime.fromSQL("2024-01-01");
    await controller.apply();
    expect.verifySteps([]);
});

test("constructor tolerates an absent pickerProps (F13)", () => {
    let controller;
    expect(() => {
        controller = createController({ getInputs: () => [] }).controller;
    }).not.toThrow();
    // Falls back to DateTimePicker default props.
    expect(controller.pickerProps.type).toBe("datetime");
});

test("getPopoverTarget range mode falls back when the first input is disconnected (F14)", () => {
    // input0 is NOT attached (disconnected) → getInput(0) returns null.
    const input0 = document.createElement("input");
    const [input1] = makeInputs(1);
    const { controller } = createController({
        getInputs: () => [input0, input1],
        pickerProps: { type: "date", range: true, value: [false, false] },
    });

    // No target set, range true, first input disconnected: must not throw and
    // must fall back to getInput(1).
    expect(controller.getPopoverTarget()).toBe(input1);
});
