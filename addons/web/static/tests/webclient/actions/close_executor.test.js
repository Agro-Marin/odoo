// @ts-check

import { expect, test } from "@odoo/hoot";
import { executeCloseAction } from "@web/webclient/actions/action_executors/close";

/**
 * @param {Object} [overrides]
 */
function makeFakeAm(overrides = {}) {
    /** @type {Record<string, any[]>} */
    const calls = { removeDialog: [] };
    const am = {
        dialog: null,
        _removeDialog: async (infos) => {
            calls.removeDialog.push(infos);
            return "removed";
        },
        ...overrides,
    };
    am.__calls = calls;
    return am;
}

test("with a dialog open: delegates to _removeDialog and forwards infos", async () => {
    const am = makeFakeAm({ dialog: { remove() {} } });
    let onCloseCalled = false;
    await executeCloseAction(
        am,
        { infos: "the-infos" },
        { onClose: () => (onCloseCalled = true) },
    );
    expect(am.__calls.removeDialog).toEqual(["the-infos"]);
    expect(onCloseCalled).toBe(false);
});

test("with no dialog: calls options.onClose with infos", async () => {
    const am = makeFakeAm();
    const seen = [];
    await executeCloseAction(
        am,
        { infos: { ok: true } },
        { onClose: (i) => seen.push(i) },
    );
    expect(seen).toEqual([{ ok: true }]);
    expect(am.__calls.removeDialog).toEqual([]);
});

test("with no dialog and no onClose: resolves without throwing", async () => {
    const am = makeFakeAm();
    expect(await executeCloseAction(am, { infos: 1 }, {})).toBe(undefined);
    expect(am.__calls.removeDialog).toEqual([]);
});

test("action and options both default: no dialog, no callback, no throw", async () => {
    const am = makeFakeAm();
    expect(await executeCloseAction(am)).toBe(undefined);
});

test("am.dialog is read live, not captured when the executor is bound", async () => {
    const am = makeFakeAm();
    const close = () => executeCloseAction(am, { infos: "late" }, {});
    am.dialog = { remove() {} };
    await close();
    expect(am.__calls.removeDialog).toEqual(["late"]);
});

test("returns the _removeDialog promise so callers can await the teardown", async () => {
    const am = makeFakeAm({ dialog: { remove() {} } });
    expect(await executeCloseAction(am, {}, {})).toBe("removed");
});

test("propagates an onClose rejection to the caller", async () => {
    const am = makeFakeAm();
    await expect(
        executeCloseAction(
            am,
            {},
            {
                onClose: () => Promise.reject(new Error("onClose blew up")),
            },
        ),
    ).rejects.toThrow(/onClose blew up/);
});

test("an explicit `dialog: null` means THERE WAS NONE, not `close whatever is open`", async () => {
    const am = makeFakeAm({ dialog: { remove() {} } });
    await executeCloseAction(am, { infos: "x" }, { dialog: null });
    expect(am.__calls.removeDialog).toEqual([]);
});

test("an explicit `dialog` still closes that dialog", async () => {
    const remove = () => {};
    const am = makeFakeAm({ dialog: { remove } });
    await executeCloseAction(am, { infos: "x" }, { dialog: { remove } });
    expect(am.__calls.removeDialog).toEqual(["x"]);
});
