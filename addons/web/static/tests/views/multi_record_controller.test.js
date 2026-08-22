// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { FormController } from "@web/views/form/form_controller";
import { MultiRecordController } from "@web/views/multi_record_controller";

describe.current.tags("headless");

test("setupModel is abstract and names the class that skipped it", () => {
    const controller = { constructor: { name: "SomeListController" } };
    expect(() => MultiRecordController.prototype.setupModel.call(controller)).toThrow(
        /SomeListController must implement setupModel\(\)/,
    );
});

test("initMultiRecordBehavior refuses a second call", () => {
    const controller = {
        constructor: { name: "SomeKanbanController" },
        _multiRecordBehaviorReady: true,
    };
    expect(() =>
        MultiRecordController.prototype.initMultiRecordBehavior.call(controller),
    ).toThrow(/SomeKanbanController called initMultiRecordBehavior\(\) twice/);
});

test("setupInteractions is optional", () => {
    expect(() =>
        MultiRecordController.prototype.setupInteractions.call({}),
    ).not.toThrow();
});

describe("FormController.archiveRecord", () => {
    /**
     * @param {Object} [overrides]
     * @param {Object} [archiveDialogProps]
     */
    function propsReachingTheDialog(overrides, archiveDialogProps = {}) {
        /** @type {any} */
        let seen;
        let archived = 0;
        const controller = {
            dialogService: { add: (_cls, props) => (seen = props) },
            model: { root: { archive: () => archived++ } },
            archiveDialogProps,
        };
        FormController.prototype.archiveRecord.call(controller, overrides);
        return { seen, archived: () => archived };
    }

    test("defaults supply the confirm, and archiveDialogProps extends them", () => {
        const { seen, archived } = propsReachingTheDialog(undefined, {
            body: "custom body",
        });
        expect(seen.body).toBe("custom body");
        expect(seen.confirmLabel.toString()).toBe("Archive");
        seen.confirm();
        expect(archived()).toBe(1);
    });

    test("overrides win over archiveDialogProps, and neither has to know about confirm", () => {
        const { seen, archived } = propsReachingTheDialog(
            { body: "from the caller", confirmLabel: "Archive Account" },
            { body: "from the getter" },
        );
        expect(seen.body).toBe("from the caller");
        expect(seen.confirmLabel).toBe("Archive Account");
        seen.confirm();
        expect(archived()).toBe(1);
    });
});
