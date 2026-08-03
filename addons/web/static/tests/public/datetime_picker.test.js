// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { mockService } from "@web/../tests/web_test_helpers";
import { DatetimePicker } from "@web/public/datetime_picker";

import { startInteraction } from "./helpers.js";

describe.current.tags("interaction_dev");

/**
 * Stands in for the datetime_picker service, recording what it was handed and
 * whether every teardown step ran.
 *
 * Teardown steps are only recorded on request: the shared helper stops the
 * interactions in an `after` hook, so a mock that always stepped would leave
 * every test that does not assert on them with unverified steps.
 *
 * @param {{ enableThrows?: boolean, trackSteps?: boolean }} [options]
 * @returns {{ props: any }}
 */
function mockPicker({ enableThrows = false, trackSteps = false } = {}) {
    /** @type {{ props: any }} */
    const captured = { props: null };
    /** @param {string} name */
    const step = (name) => trackSteps && expect.step(name);
    mockService("datetime_picker", {
        // A stub of the three methods `public/datetime_picker.js` calls, not a
        // DateTimePickerController — the interaction never reaches the rest.
        /**
         * Deliberately partial: these tests drive only enable/close/disable,
         * so the object is cast rather than padded with unused no-ops. It
         * type-checked before only because the service's own return type was
         * wrong; now that it is right, the gap has to be stated.
         *
         * @param {{ pickerProps: any }} arg
         * @returns {any}
         */
        create({ pickerProps }) {
            captured.props = pickerProps;
            return /** @type {any} */ ({
                enable: () => () => {
                    step("disableListeners");
                    if (enableThrows) {
                        throw new Error("disableListeners blew up");
                    }
                },
                close: () => step("close"),
                disable: () => step("disable"),
            });
        },
    });
    return captured;
}

test("an unparseable value leaves an empty picker, not a dead interaction", async () => {
    const captured = mockPicker();
    // the input is public: its value is server-rendered or visitor-typed, and
    // one the parser chokes on used to take the whole interaction down
    const { core } = await startInteraction(
        DatetimePicker,
        `<input data-widget="datetime-picker" value="not a date"/>`,
        { waitForStart: false },
    );
    await core.isReady;
    expect(core.interactions).toHaveLength(1);
    expect(captured.props.value).toBe(undefined);
});

test("reads the widget type and bounds off the dataset", async () => {
    const captured = mockPicker();
    await startInteraction(
        DatetimePicker,
        `<input data-widget="datetime-picker" data-widget-type="date"
                data-min-date="2023-02-01" data-max-date="2023-02-28" value=""/>`,
    );
    expect(captured.props.type).toBe("date");
    expect(captured.props.minDate.toISODate()).toBe("2023-02-01");
    expect(captured.props.maxDate.toISODate()).toBe("2023-02-28");
    // an empty input is not a parse failure: `parseDate` returns null for it
    expect(captured.props.value).toBe(null);
});

test("defaults to datetime and leaves absent bounds undefined", async () => {
    const captured = mockPicker();
    await startInteraction(
        DatetimePicker,
        `<input data-widget="datetime-picker" value=""/>`,
    );
    expect(captured.props.type).toBe("datetime");
    expect(captured.props.minDate).toBe(undefined);
    expect(captured.props.maxDate).toBe(undefined);
});

test("every teardown step runs even when an earlier one throws", async () => {
    mockPicker({ enableThrows: true, trackSteps: true });
    const { core } = await startInteraction(
        DatetimePicker,
        `<input data-widget="datetime-picker" value=""/>`,
    );
    // chained plainly, a failing `disableListeners()` left the picker open and
    // enabled: an overlay plus a set of document listeners outliving the page
    expect(() => core.stopInteractions()).toThrow(
        "Could not destroy some interactions",
    );
    expect.verifySteps(["disableListeners", "close", "disable"]);
});
