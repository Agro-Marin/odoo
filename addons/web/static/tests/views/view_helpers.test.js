// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { deleteConfirmationMessage } from "@web/ui/dialog/confirmation_dialog";
import { deleteConfirmationProps } from "@web/views/view_hook";
import { exportableFields } from "@web/views/view_utils";

describe.current.tags("headless");

test("exportableFields: active, present, exportable, not properties, then the caller's filter", () => {
    const fields = {
        a: { name: "a", type: "char" },
        b: { name: "b", type: "char", exportable: false },
        c: { name: "c", type: "properties" },
        d: { name: "d", type: "integer" },
    };
    const activeFields = { a: {}, b: {}, c: {}, d: {}, ghost: {} };
    expect(exportableFields(fields, activeFields).map((f) => f.name)).toEqual([
        "a",
        "d",
    ]);
    expect(
        exportableFields(fields, activeFields, (f) => f.type === "integer").map(
            (f) => f.name,
        ),
    ).toEqual(["d"]);
    expect(exportableFields(fields, {})).toEqual([]);
});

test("deleteConfirmationProps: one record or several", async () => {
    let confirmed = 0;
    const single = deleteConfirmationProps(() => confirmed++);
    expect(single.body).toBe(deleteConfirmationMessage);
    expect(single.confirmLabel).toBe("Delete");
    expect(single.cancelLabel).toBe("No, keep it");
    expect(single.title).toBe("Bye-bye, record!");
    single.confirm();
    single.cancel();
    expect(confirmed).toBe(1);
    const multi = deleteConfirmationProps(() => {}, { multi: true });
    expect(multi.body).toBe("Are you sure you want to delete these records?");
});
