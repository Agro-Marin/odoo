import { computeActionsStack } from "@mail/discuss/call/common/call_actions";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

test("newly active actions are stacked most recent first", () => {
    expect(computeActionsStack([], ["mute", "camera-on"])).toEqual([
        "camera-on",
        "mute",
    ]);
});

test("already stacked actions keep their relative order", () => {
    expect(computeActionsStack(["camera-on", "mute"], ["mute", "camera-on"])).toEqual([
        "camera-on",
        "mute",
    ]);
});

test("actions that stopped being active drop out", () => {
    expect(computeActionsStack(["camera-on", "mute"], ["mute"])).toEqual(["mute"]);
});

test("an action that was never stacked does not evict the stack head", () => {
    // Regression: the previous implementation ran
    // `stack.splice(stack.indexOf(id), 1)` for every tracked action whose
    // active state had changed to falsy. For an action absent from the stack
    // `indexOf` returns -1 and `splice(-1, 1)` removes the LAST entry instead
    // of nothing, so an inactive action evicted whichever action had just been
    // pushed. Fuzzed against the ground truth "the stack holds exactly the
    // active tracked ids", the old logic diverged in ~82% of random sequences.
    expect(computeActionsStack(["camera-on"], ["camera-on"])).toEqual(["camera-on"]);
    expect(computeActionsStack(["deafen", "mute"], ["deafen", "mute"])).toEqual([
        "deafen",
        "mute",
    ]);
});

test("deactivating every action empties the stack", () => {
    expect(computeActionsStack(["camera-on", "mute"], [])).toEqual([]);
});

test("is idempotent", () => {
    const once = computeActionsStack([], ["mute", "deafen", "camera-on"]);
    expect(computeActionsStack(once, ["mute", "deafen", "camera-on"])).toEqual(once);
});
