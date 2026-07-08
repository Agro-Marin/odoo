// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getService, makeMockEnv } from "@web/../tests/web_test_helpers";

describe.current.tags("headless");

test("pop() is floored at 0 (unbalanced pop does not go negative)", async () => {
    await makeMockEnv();
    const service = await getService("form_dialog_stack");
    expect(service.count).toBe(0);
    expect(service.isEmpty).toBe(true);

    // Unbalanced pop() must not drive count negative — which would leave
    // isEmpty falsy forever.
    service.pop();
    expect(service.count).toBe(0);
    expect(service.isEmpty).toBe(true);

    // Balanced push/pop still tracks correctly afterwards.
    service.push();
    expect(service.count).toBe(1);
    expect(service.isEmpty).toBe(false);
    service.pop();
    expect(service.count).toBe(0);
    expect(service.isEmpty).toBe(true);
});
