// @ts-check
import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { CHAT_HUB_COMPACT_LS } from "@mail/core/common/chat_hub_model";
import { MESSAGE_SOUND } from "@mail/core/common/settings_model";
import {
    DISCUSS_SIDEBAR_COMPACT_LS,
    NO_MEMBERS_DEFAULT_OPEN_LS,
} from "@mail/core/public_web/discuss_app_model";
import {
    onLocalStorageChange,
    readLocalStorageItem,
    removeLocalStorageItem,
    setLocalStorageItem,
} from "@mail/utils/common/local_storage";
import { describe, expect, test } from "@odoo/hoot";
import { getService } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("headless");
defineMailModels();

test("a compute reading a mirrored key follows this tab's writes", async () => {
    await start();
    const store = getService("mail.store");
    expect(store.chatHub.compact).toBe(false);
    expect(store.settings.messageSound).toBe(true);
    setLocalStorageItem(store, CHAT_HUB_COMPACT_LS, "true");
    setLocalStorageItem(store, MESSAGE_SOUND, "false");
    expect(store.chatHub.compact).toBe(true);
    expect(store.settings.messageSound).toBe(false);
    expect(browser.localStorage.getItem(CHAT_HUB_COMPACT_LS)).toBe("true");
    removeLocalStorageItem(store, CHAT_HUB_COMPACT_LS);
    expect(store.chatHub.compact).toBe(false);
    expect(browser.localStorage.getItem(CHAT_HUB_COMPACT_LS)).toBe(null);
});

test("a compute reading a mirrored key follows another tab's writes", async () => {
    await start();
    const store = getService("mail.store");
    expect(store.discuss.isSidebarCompact).toBe(false);
    expect(store.discuss.isMemberPanelOpenByDefault).toBe(true);
    window.dispatchEvent(
        new StorageEvent("storage", {
            key: DISCUSS_SIDEBAR_COMPACT_LS,
            newValue: "true",
        }),
    );
    window.dispatchEvent(
        new StorageEvent("storage", {
            key: NO_MEMBERS_DEFAULT_OPEN_LS,
            newValue: "true",
        }),
    );
    expect(store.discuss.isSidebarCompact).toBe(true);
    expect(store.discuss.isMemberPanelOpenByDefault).toBe(false);
    window.dispatchEvent(new StorageEvent("storage", { key: null, newValue: null }));
    expect(store.discuss.isSidebarCompact).toBe(false);
    expect(store.discuss.isMemberPanelOpenByDefault).toBe(true);
});

test("a key is read from localStorage the first time and mirrored afterwards", async () => {
    browser.localStorage.setItem("mail.test.mirrored", "seeded");
    await start();
    const store = getService("mail.store");
    expect(readLocalStorageItem(store, "mail.test.mirrored")).toBe("seeded");
    const seen = [];
    const stop = onLocalStorageChange(store, "mail.test.mirrored", (value) =>
        seen.push(value),
    );
    window.dispatchEvent(
        new StorageEvent("storage", {
            key: "mail.test.mirrored",
            newValue: "elsewhere",
        }),
    );
    expect(readLocalStorageItem(store, "mail.test.mirrored")).toBe("elsewhere");
    stop();
    window.dispatchEvent(
        new StorageEvent("storage", { key: "mail.test.mirrored", newValue: "later" }),
    );
    expect(seen).toEqual(["elsewhere"]);
    expect(readLocalStorageItem(store, "mail.test.mirrored")).toBe("later");
});

test("the call device ids are computed from their keys and follow another tab", async () => {
    browser.localStorage.setItem("mail_user_setting_audio_input_device_id", "mic-1");
    await start();
    const store = getService("mail.store");
    expect(store.settings.audioInputDeviceId).toBe("mic-1");
    expect(store.settings.audioOutputDeviceId).toBe("");
    expect(store.settings.cameraInputDeviceId).toBe("");
    store.settings.setAudioOutputDevice("speaker-2");
    store.settings.setCameraInputDevice("cam-3");
    expect(store.settings.audioOutputDeviceId).toBe("speaker-2");
    expect(store.settings.cameraInputDeviceId).toBe("cam-3");
    expect(
        browser.localStorage.getItem("mail_user_setting_camera_input_device_id"),
    ).toBe("cam-3");
    window.dispatchEvent(
        new StorageEvent("storage", {
            key: "mail_user_setting_audio_input_device_id",
            newValue: "mic-9",
        }),
    );
    expect(store.settings.audioInputDeviceId).toBe("mic-9");
    window.dispatchEvent(new StorageEvent("storage", { key: null, newValue: null }));
    expect(store.settings.audioInputDeviceId).toBe("");
    expect(store.settings.cameraInputDeviceId).toBe("");
});
