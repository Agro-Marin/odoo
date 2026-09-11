// @ts-check
import { MOCK_SFU_CLIENT_STATE } from "@mail/../tests/discuss/call/mock_sfu_client";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");

test("mock SFU state enum matches the real client's", async () => {
    const { SFU_CLIENT_STATE } = await import("@odoo/sfu");
    expect(Object.entries(MOCK_SFU_CLIENT_STATE)).toEqual(
        Object.entries(SFU_CLIENT_STATE),
    );
});
