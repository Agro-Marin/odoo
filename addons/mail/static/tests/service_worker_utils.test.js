import {
    arrayBufferToBase64Url,
    notificationTargetPath,
    pickTargetClient,
    planPushNotification,
    PUSH_NOTIFICATION_ACTION,
} from "@mail/service_worker_utils";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

test("arrayBufferToBase64Url produces unpadded base64url", () => {
    const buffer = new Uint8Array([0xfb, 0xff, 0xbf]).buffer;
    const encoded = arrayBufferToBase64Url(buffer);
    expect(encoded).toBe("-_-_");
    expect(encoded).not.toInclude("+");
    expect(encoded).not.toInclude("/");
    expect(encoded).not.toInclude("=");
});

test("planPushNotification: empty/invalid payload -> generic", () => {
    expect(planPushNotification(undefined).type).toBe("generic");
    expect(planPushNotification({}).type).toBe("generic");
    expect(planPushNotification({ options: { data: { type: "CALL" } } }).type).toBe(
        "generic",
    );
});

test("planPushNotification: CALL shows the notification", () => {
    const plan = planPushNotification({
        title: "Incoming call",
        options: { data: { type: "CALL" }, actions: [{ action: "ACCEPT" }] },
    });
    expect(plan.type).toBe("show");
    expect(plan.title).toBe("Incoming call");
    expect(plan.options.actions).toHaveLength(1);
});

test("planPushNotification: CALL on Android drops the ACCEPT action (no mutation)", () => {
    const notification = {
        title: "Incoming call",
        options: {
            data: { type: "CALL" },
            actions: [{ action: "ACCEPT" }, { action: "DECLINE" }],
        },
    };
    const plan = planPushNotification(notification, { isAndroid: true });
    expect(plan.type).toBe("show");
    expect(plan.options.actions.map((a) => a.action)).toEqual([
        PUSH_NOTIFICATION_ACTION.DECLINE,
    ]);
    expect(notification.options.actions).toHaveLength(2);
});

test("planPushNotification: tag-less CANCEL is ignored, tagged CANCEL cancels", () => {
    expect(
        planPushNotification({ title: "", options: { data: { type: "CANCEL" } } }).type,
    ).toBe("ignore");
    const plan = planPushNotification({
        title: "",
        options: { data: { type: "CANCEL" }, tag: "call-42" },
    });
    expect(plan.type).toBe("cancel");
    expect(plan.tag).toBe("call-42");
});

test("planPushNotification: default payload -> handshake", () => {
    const plan = planPushNotification({
        title: "New message",
        options: { data: { model: "discuss.channel", res_id: 5 } },
    });
    expect(plan.type).toBe("handshake");
});

test("notificationTargetPath maps dotted models and shorthand", () => {
    expect(notificationTargetPath("discuss.channel", 7)).toBe(
        "/odoo/discuss.channel/7",
    );
    expect(notificationTargetPath("project", 3)).toBe("/odoo/m-project/3");
});

function windowClient(id, { focused = false, visible = false, path = "/odoo" } = {}) {
    return {
        id,
        focused,
        visibilityState: visible ? "visible" : "hidden",
        url: `https://example.com${path}`,
    };
}

test("pickTargetClient: nothing to pick from", () => {
    expect(pickTargetClient([])).toBe(undefined);
    expect(pickTargetClient([windowClient("a")], { source: { id: "a" } })).toBe(
        undefined,
    );
});

test("pickTargetClient: a focused window beats a visible one, which beats a hidden one", () => {
    const hidden = windowClient("hidden");
    const visible = windowClient("visible", { visible: true });
    const focused = windowClient("focused", { focused: true });
    expect(pickTargetClient([hidden, visible, focused])).toBe(focused);
    expect(pickTargetClient([hidden, visible])).toBe(visible);
    expect(pickTargetClient([hidden])).toBe(hidden);
});

test("pickTargetClient: a matching URL breaks ties and never outranks focus", () => {
    const onDiscuss = windowClient("discuss", { path: "/odoo/discuss" });
    const elsewhere = windowClient("elsewhere", { path: "/odoo/contacts" });
    const focusedElsewhere = windowClient("focused", {
        focused: true,
        path: "/odoo/contacts",
    });
    const urlRegexes = [/\/odoo\/discuss/];
    expect(pickTargetClient([elsewhere, onDiscuss], { urlRegexes })).toBe(onDiscuss);
    expect(pickTargetClient([onDiscuss, focusedElsewhere], { urlRegexes })).toBe(
        focusedElsewhere,
    );
});

test("pickTargetClient: the message source is never picked", () => {
    const source = windowClient("source", { focused: true });
    const other = windowClient("other");
    expect(pickTargetClient([source, other], { source })).toBe(other);
});
