import { MOCK_SFU_CLIENT_STATE } from "@mail/../tests/discuss/call/mock_sfu_client";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");

test("mock SFU state enum matches the real client's", async () => {
    // The real module ships in the lazy mail.assets_odoo_sfu bundle, so the
    // mock hand-duplicates its state enum; without this gate nothing would
    // catch the two drifting apart (tests would keep passing against states
    // the real client never enters). Native-ESM import by URL: the module is
    // not in the unit-test bundle's import map, and loadBundle is blocked by
    // hoot's fetch mock (module loads are not).
    const { SFU_CLIENT_STATE } = await import("/mail/static/lib/odoo_sfu/odoo_sfu.js");
    expect({ ...MOCK_SFU_CLIENT_STATE }).toEqual({ ...SFU_CLIENT_STATE });
});
