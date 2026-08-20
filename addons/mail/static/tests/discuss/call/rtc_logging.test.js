import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");
defineMailModels();

test("log() survives being called before the first call join", async () => {
    // `state.logs` starts as `{}` — truthy, but with no `entriesBySessionId`.
    // Any rtc_session removal on any thread reaches Rtc.disconnect() -> log(),
    // so with the logRtc setting on this runs before joinCall() has ever built
    // the per-call log object.
    const env = await start();
    const store = env.services["mail.store"];
    const rtc = store.rtc;
    store.settings.logRtc = true;
    const session = store["discuss.channel.rtc.session"].insert({ id: 1 });
    expect(rtc.state.logs).toEqual({});
    expect(() =>
        rtc.log(session, "peer removed", { step: "peer removed" }),
    ).not.toThrow();
    expect(session.logStep).toBe("peer removed");
});
