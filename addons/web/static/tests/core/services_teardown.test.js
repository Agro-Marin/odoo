// @ts-check

import { describe, destroy, expect, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import { Component, onMounted, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    getService,
    makeMockEnv,
    mockService,
    models,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { UserEvent } from "@web/core/events";
import { featureFlag } from "@web/core/feature_flags";
import { fileUploadService } from "@web/core/file_upload/file_upload_service";
import { _makeUser, user, userBus } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { _resetPwaInstallPrompt } from "@web/ui/pwa/pwa_service";

const ROUTE = "/web/binary/upload_attachment";

class Teardown extends models.Model {
    _name = "teardown";
    name = fields.Char();
}
defineModels([Teardown]);

describe.current.tags("desktop");

describe("connection recovery outlives nothing", () => {
    test("a lost connection reported after destroy does not re-arm the poll", async () => {
        const { UncaughtPromiseError } =
            await import("@web/core/errors/uncaught_errors");
        const { ConnectionLostError } = await import("@web/core/network/rpc");
        const { lostConnectionHandler, connectionRecoveryService } =
            await import("@web/components/errors/error_handlers");
        await makeMockEnv();
        onRpc("/web/webclient/version_info", () => {
            expect.step("probe");
            return {};
        });

        const error = new UncaughtPromiseError();
        error.unhandledRejectionEvent = /** @type {any} */ ({
            preventDefault: () => {},
        });
        /** @type {string[]} */
        const notifications = [];
        const env = {
            services: {
                notification: {
                    add: (/** @type {any} */ message) => {
                        notifications.push(String(message));
                        return () => {};
                    },
                },
            },
        };

        const recovery = connectionRecoveryService.start(/** @type {any} */ (env));
        recovery.destroy();

        // Destroy used to DELETE the per-env state, so a late error allocated a
        // fresh `destroyed: false` one and started polling an env nobody shows.
        expect(
            lostConnectionHandler(
                /** @type {any} */ (env),
                error,
                new ConnectionLostError("/x"),
            ),
        ).toBe(true);
        await advanceTime(120_000);
        expect.verifySteps([]);
        expect(notifications).toEqual([]);
    });
});

describe("hotkey iframe registration", () => {
    test("destroy() detaches listeners added through registerIframe", async () => {
        await makeMockEnv();
        const hotkeyService = getService("hotkey");
        const iframe = document.createElement("iframe");
        document.body.appendChild(iframe);
        await Promise.resolve();
        const iframeWindow = /** @type {any} */ (iframe.contentWindow);

        /** @type {string[]} */
        const attached = [];
        const realAdd = iframeWindow.addEventListener.bind(iframeWindow);
        const realRemove = iframeWindow.removeEventListener.bind(iframeWindow);
        iframeWindow.addEventListener = (
            /** @type {string} */ type,
            /** @type {any} */ fn,
            /** @type {any} */ opts,
        ) => {
            attached.push(type);
            realAdd(type, fn, opts);
        };
        iframeWindow.removeEventListener = (
            /** @type {string} */ type,
            /** @type {any} */ fn,
            /** @type {any} */ opts,
        ) => {
            const index = attached.indexOf(type);
            if (index > -1) {
                attached.splice(index, 1);
            }
            realRemove(type, fn, opts);
        };

        hotkeyService.registerIframe(iframe);
        expect(attached.length).toBe(4);
        hotkeyService.destroy();
        expect(attached).toEqual([]);
        iframe.remove();
    });

    test("the disposer returned by registerIframe stays idempotent", async () => {
        await makeMockEnv();
        const hotkeyService = getService("hotkey");
        const iframe = document.createElement("iframe");
        document.body.appendChild(iframe);
        await Promise.resolve();

        const remove = hotkeyService.registerIframe(iframe);
        remove();
        remove();
        expect(() => hotkeyService.destroy()).not.toThrow();
        iframe.remove();
    });
});

describe("file upload teardown", () => {
    test("destroying the env aborts the in-flight upload and silences it", async () => {
        /** @type {any[]} */
        const notifications = [];
        /** @type {any[]} */
        const created = [];
        patchWithCleanup(fileUploadService, {
            createXhr() {
                const xhr = /** @type {any} */ ({
                    status: 0,
                    responseText: "",
                    upload: { addEventListener() {} },
                    /** @type {Record<string, Function>} */
                    listeners: {},
                    open() {},
                    send() {},
                    aborted: false,
                    abort() {
                        this.aborted = true;
                        this.listeners.abort?.();
                    },
                    addEventListener(
                        /** @type {string} */ type,
                        /** @type {Function} */ cb,
                    ) {
                        this.listeners[type] = cb;
                    },
                });
                created.push(xhr);
                return xhr;
            },
        });
        mockService("notification", {
            add: (/** @type {any} */ message) => {
                notifications.push(String(message));
                return () => {};
            },
        });

        // Goes through the real registry, so this also proves env.destroy()
        // actually reaches a service's destroy() — the premise of this file.
        const env = await makeMockEnv();
        const fileUpload = getService("file_upload");
        const upload = await fileUpload.upload(ROUTE, [new File(["x"], "x.txt")]);
        expect(created).toHaveLength(1);
        expect(created[0].aborted).toBe(false);
        expect(fileUpload.uploads[upload.id]).toBe(upload);

        env.destroy();
        expect(created[0].aborted).toBe(true);
        expect(upload.state).toBe("abort");
        expect(fileUpload.uploads[upload.id]).toBe(undefined);

        // A failure landing after teardown must not push into a dead UI.
        created[0].listeners.error?.();
        expect(notifications).toEqual([]);
    });
});

describe("user cache invalidation ownership", () => {
    test("_makeUser does not add a userBus listener of its own", async () => {
        let added = 0;
        const realAdd = userBus.addEventListener.bind(userBus);
        userBus.addEventListener = (
            /** @type {string} */ type,
            /** @type {any} */ fn,
            /** @type {any} */ opts,
        ) => {
            if (type === UserEvent.ACTIVE_COMPANIES_CHANGED) {
                added++;
            }
            realAdd(type, fn, opts);
        };
        try {
            _makeUser({ uid: 1, user_context: {} });
            _makeUser({ uid: 1, user_context: {} });
        } finally {
            userBus.addEventListener = realAdd;
        }
        expect(added).toBe(0);
    });

    test("a company switch still invalidates the live user's group cache", async () => {
        await makeMockEnv();
        onRpc("has_group", () => {
            expect.step("has_group");
            return true;
        });
        await user.hasGroup("base.group_user_probe");
        await user.hasGroup("base.group_user_probe");
        expect.verifySteps(["has_group"]);

        userBus.trigger(UserEvent.ACTIVE_COMPANIES_CHANGED);
        await user.hasGroup("base.group_user_probe");
        expect.verifySteps(["has_group"]);
    });

    test("invalidation follows a patched-in user, which is what tests install", async () => {
        await makeMockEnv();
        onRpc("has_group", () => {
            expect.step("has_group");
            return true;
        });
        // `patchWithCleanup(user, _makeUser(...))` is the established idiom
        // (user.test.js, daterange_field.test.js). Routing invalidation through
        // the live binding has to reach THAT closure's caches, not the original's.
        patchWithCleanup(user, _makeUser({ uid: 7, user_context: {} }));
        await user.hasGroup("base.group_patched_probe");
        await user.hasGroup("base.group_patched_probe");
        expect.verifySteps(["has_group"]);

        userBus.trigger(UserEvent.ACTIVE_COMPANIES_CHANGED);
        await user.hasGroup("base.group_patched_probe");
        expect.verifySteps(["has_group"]);
    });
});

describe("pwa install-prompt latch", () => {
    test("a parked prompt does not survive into the next test", async () => {
        const ev = /** @type {any} */ (new CustomEvent("beforeinstallprompt"));
        ev.preventDefault = () => {};
        ev.prompt = async () => ({ outcome: "accepted" });
        browser.BeforeInstallPromptEvent = ev;

        // Fired with no service running, so the module-level latch parks it.
        // Nothing consumes it — exactly the shape that leaked: the NEXT test's
        // service claimed it and reported an install prompt it never saw.
        browser.dispatchEvent(ev);
        _resetPwaInstallPrompt();

        await makeMockEnv();
        expect(getService("pwa").isAvailable).toBe(false);
    });

    test("a prompt parked before start is still claimed by the service", async () => {
        const ev = /** @type {any} */ (new CustomEvent("beforeinstallprompt"));
        ev.preventDefault = () => {};
        ev.prompt = async () => ({ outcome: "accepted" });
        browser.BeforeInstallPromptEvent = ev;

        // The reset must not defeat the latch's actual purpose.
        browser.dispatchEvent(ev);
        await makeMockEnv();
        expect(getService("pwa").isAvailable).toBe(true);
    });
});

describe("async service protection", () => {
    test("a pwa manifest landing after unmount does not reach the component", async () => {
        /** @type {(value: any) => void} */
        /** @type {(value: any) => void} */
        let releaseManifest = () => {};
        const manifestPromise = new Promise((resolve) => {
            releaseManifest = resolve;
        });
        mockService("pwa", {
            getManifest: () => manifestPromise,
            show: async () => {},
        });

        /** @type {string[]} */
        const writes = [];
        class Consumer extends Component {
            /** @type {string[]} */
            static props = [];
            static template = xml`<div class="consumer"/>`;
            setup() {
                const pwa = useService("pwa");
                onMounted(async () => {
                    const manifest = await pwa.getManifest();
                    // Reached only if the call was NOT protected: by now the
                    // component is destroyed and this write targets dead state.
                    writes.push(/** @type {any} */ (manifest).name);
                });
            }
        }

        const component = await mountWithCleanup(Consumer);
        destroy(component);
        releaseManifest({ name: "Odoo PWA" });
        await animationFrame();

        expect(writes).toEqual([]);
    });
});

describe("feature flag URL memoization", () => {
    // This pair is deliberately ordered: the first test's only job is to prime
    // the module-level override cache the way any incidental read does, so the
    // second can show that a correctly-patched URL is still honoured.
    test("an incidental read on a clean URL primes the cache", async () => {
        expect(featureFlag("teardown_probe_flag")).toBe(false);
    });

    test("a URL patched afterwards is still honoured, not answered from the memo", async () => {
        patchWithCleanup(browser.location, {
            href: "http://localhost/odoo?features=teardown_probe_flag:42",
        });
        // `patchWithCleanup` restores browser.location but cannot reach a memo
        // derived from it, so without a global reset this answered `false` and
        // the test silently asserted nothing.
        expect(featureFlag("teardown_probe_flag")).toBe(42);
    });
});

describe("command service teardown", () => {
    test("destroying the env releases control+k and the registrations", async () => {
        const env = await makeMockEnv();
        const command = getService("command");
        command.add("probe command", () => {}, { global: true });
        expect(command.getCommands(document.body)).toHaveLength(1);

        /** @type {string[]} */
        const opened = [];
        patchWithCleanup(command, {
            openMainPalette: () => opened.push("opened"),
        });

        env.destroy();
        expect(command.getCommands(document.body)).toHaveLength(0);

        // The palette hotkey was registered at start() and never released, so
        // it stayed live in a hotkey service the same teardown just emptied.
        await press(["control", "k"]);
        expect(opened).toEqual([]);
    });
});

describe("orm empty id lists", () => {
    test("id-addressed reads short-circuit instead of round-tripping", async () => {
        await makeMockEnv();
        onRpc(({ method }) => {
            expect.step(method);
        });
        const orm = getService("orm");
        expect(await orm.read("teardown", [], ["name"])).toEqual([]);
        expect(await orm.unlink("teardown", [])).toBe(true);
        expect(
            await orm.webRead("teardown", [], { specification: { name: {} } }),
        ).toEqual([]);
        expect(await orm.webResequence("teardown", [])).toEqual([]);
        expect.verifySteps([]);
    });

    test("webSave with no ids still reaches the server, because that is a create", async () => {
        await makeMockEnv();
        onRpc(({ method }) => {
            expect.step(method);
        });
        const orm = getService("orm");
        await orm.webSave("teardown", [], { name: "created" }, { specification: {} });
        expect.verifySteps(["web_save"]);
    });
});
