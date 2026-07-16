import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { advanceTime, tick } from "@odoo/hoot-mock";
import { getService } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("getWhenReady resolves with the session once it is inserted", async () => {
    await start();
    const RtcSession = getService("mail.store")["discuss.channel.rtc.session"];
    let resolved;
    RtcSession.getWhenReady(101).then((session) => (resolved = session));
    await tick();
    // the session does not exist yet: the caller keeps waiting
    expect(resolved).toBe(undefined);
    RtcSession.insert({ id: 101 });
    await tick();
    expect(resolved?.id).toBe(101);
});

test("getWhenReady returns an already-present session immediately", async () => {
    await start();
    const RtcSession = getService("mail.store")["discuss.channel.rtc.session"];
    RtcSession.insert({ id: 102 });
    let resolved;
    RtcSession.getWhenReady(102).then((session) => (resolved = session));
    await tick();
    expect(resolved?.id).toBe(102);
});

test("getWhenReady's 120s fallback timer is cleared when the session arrives, so a later await of the same id is not evicted by the stale timer", async () => {
    await start();
    const RtcSession = getService("mail.store")["discuss.channel.rtc.session"];

    // First await: create the deferred (and its 120s fallback timer), then the
    // session arrives and resolves it. The fallback timer must be cleared here.
    let firstResolved = false;
    RtcSession.getWhenReady(303).then(() => (firstResolved = true));
    const firstSession = RtcSession.insert({ id: 303 });
    await tick();
    expect(firstResolved).toBe(true);

    // The session goes away; some time later the same id is awaited again,
    // creating a *fresh* deferred (and a fresh timer due at t+180s).
    firstSession.delete();
    await tick();
    await advanceTime(60_000);
    let secondResult;
    RtcSession.getWhenReady(303).then((session) => (secondResult = session));

    // Advance to t=120s — exactly when the FIRST await's fallback timer was due.
    // If that timer had not been cleared, its callback would delete the fresh
    // deferred from `awaitedRecords`; the session arriving next would then not
    // resolve it, hanging the caller until its own (much later) fallback fires.
    await advanceTime(60_000);
    RtcSession.insert({ id: 303 });
    await tick();
    expect(secondResult?.id).toBe(303);
});
