// @ts-check

/**
 * Pure unit tests for the EmbeddedActions model and its config handler.
 *
 * The tested methods are plain (async) functions that only touch this.orm,
 * this.configHandler and this.embeddedInfos, so tests build a minimal `this`
 * and invoke them directly (EmbeddedActions.prototype.<method>.call) rather
 * than mounting the full OWL component tree.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    EmbeddedActions,
    EmbeddedActionsConfigHandler,
} from "@web/search/embedded_actions_bar/embedded_actions_bar";

/**
 * Build a minimal `this` for deleteAction.
 * @param {Object} orm
 * @param {Function} setEmbeddedActionsConfig
 */
function makeSelf(orm, setEmbeddedActionsConfig) {
    return {
        embeddedInfos: {
            visibleEmbeddedActions: [7, 8],
            embeddedActions: [{ id: 7 }, { id: 8 }],
            currentEmbeddedAction: { id: 8 },
        },
        orm,
        configHandler: { setEmbeddedActionsConfig },
    };
}

/**
 * Build a config handler without hitting user.settings in the constructor.
 * @param {Object} [params]
 * @param {Object} [params.orm]
 * @param {Object} [params.notification]
 * @param {Object} [params.initialConfig]
 */
function makeConfigHandler({ orm, notification, initialConfig } = {}) {
    const handler = Object.create(EmbeddedActionsConfigHandler.prototype);
    handler.parentActionId = 1;
    handler.currentActiveId = false;
    handler.embeddedActionsKey = "1+";
    handler.embeddedActionsConfig = initialConfig || {};
    handler.orm = orm || { call: async () => true };
    handler.notification = notification || { add: () => {} };
    return handler;
}

describe("EmbeddedActions.deleteAction", () => {
    test("server refusal leaves the tab and settings intact", async () => {
        let settingsCalls = 0;
        const self = makeSelf(
            {
                unlink: async () => {
                    throw new Error("Access Denied");
                },
            },
            async () => {
                settingsCalls++;
            },
        );

        await expect(
            EmbeddedActions.prototype.deleteAction.call(self, { id: 7 }),
        ).rejects.toThrow();

        // unlink is refused before any local mutation or persistence: the tab
        // stays and res.users.settings is never written.
        expect(self.embeddedInfos.visibleEmbeddedActions).toEqual([7, 8]);
        expect(self.embeddedInfos.embeddedActions.map((a) => a.id)).toEqual([7, 8]);
        expect(settingsCalls).toBe(0);
    });

    test("successful unlink removes the tab and persists settings once", async () => {
        let savedConfig = null;
        let settingsCalls = 0;
        const self = makeSelf({ unlink: async () => true }, async (config) => {
            settingsCalls++;
            savedConfig = config;
        });

        await EmbeddedActions.prototype.deleteAction.call(self, { id: 7 });

        expect(self.embeddedInfos.visibleEmbeddedActions).toEqual([8]);
        expect(self.embeddedInfos.embeddedActions.map((a) => a.id)).toEqual([8]);
        expect(settingsCalls).toBe(1);
        expect(savedConfig).toEqual({
            embedded_actions_visibility: [8],
            embedded_actions_order: [8],
        });
    });
});

describe("EmbeddedActionsConfigHandler.setEmbeddedActionsConfig", () => {
    test("stores a deep copy: later caller mutations do not reach the cache", async () => {
        const handler = makeConfigHandler();
        const visibility = [7];

        await handler.setEmbeddedActionsConfig({
            embedded_actions_visibility: visibility,
        });
        visibility.push(8);

        expect(handler.getEmbeddedActionsConfig("embedded_actions_visibility")).toEqual(
            [7],
        );
    });

    test("RPC failure with an existing config reverts the array payload", async () => {
        const notifications = [];
        const handler = makeConfigHandler({
            orm: {
                call: async () => {
                    throw new Error("boom");
                },
            },
            notification: { add: (_msg, opts) => notifications.push(opts.type) },
            initialConfig: { "1+": { embedded_actions_visibility: [7, 8] } },
        });

        const saved = await handler.setEmbeddedActionsConfig({
            embedded_actions_visibility: [7],
        });

        expect(saved).toBe(false);
        expect(handler.getEmbeddedActionsConfig("embedded_actions_visibility")).toEqual(
            [7, 8],
        );
        expect(notifications).toEqual(["danger"]);
    });

    test("RPC failure without an existing config deletes the entry", async () => {
        const handler = makeConfigHandler({
            orm: {
                call: async () => {
                    throw new Error("boom");
                },
            },
        });

        const saved = await handler.setEmbeddedActionsConfig({
            embedded_visibility: true,
        });

        expect(saved).toBe(false);
        expect(handler.hasEmbeddedActionsConfig()).toBe(false);
    });

    test("success returns true and merges into the existing entry", async () => {
        const handler = makeConfigHandler({
            initialConfig: { "1+": { embedded_visibility: false } },
        });

        const saved = await handler.setEmbeddedActionsConfig({
            embedded_actions_order: [7, 8],
        });

        expect(saved).toBe(true);
        expect(handler.getEmbeddedActionsConfig("embedded_visibility")).toBe(false);
        expect(handler.getEmbeddedActionsConfig("embedded_actions_order")).toEqual([
            7, 8,
        ]);
    });
});

describe("EmbeddedActions.toggleActionVisibility", () => {
    test("toggles and persists a copy on success", async () => {
        let savedConfig = null;
        const self = {
            embeddedInfos: { visibleEmbeddedActions: [7] },
            configHandler: {
                setEmbeddedActionsConfig: async (config) => {
                    savedConfig = config;
                    return true;
                },
            },
        };

        await EmbeddedActions.prototype.toggleActionVisibility.call(self, 8);

        expect(self.embeddedInfos.visibleEmbeddedActions).toEqual([7, 8]);
        expect(savedConfig.embedded_actions_visibility).toEqual([7, 8]);
        expect(savedConfig.embedded_actions_visibility).not.toBe(
            self.embeddedInfos.visibleEmbeddedActions,
        );
    });

    test("persistence failure restores the visible actions (hide case)", async () => {
        const self = {
            embeddedInfos: { visibleEmbeddedActions: [7, 8] },
            configHandler: { setEmbeddedActionsConfig: async () => false },
        };

        await EmbeddedActions.prototype.toggleActionVisibility.call(self, 8);

        expect(self.embeddedInfos.visibleEmbeddedActions).toEqual([7, 8]);
    });

    test("persistence failure restores the visible actions (show case)", async () => {
        const self = {
            embeddedInfos: { visibleEmbeddedActions: [7] },
            configHandler: { setEmbeddedActionsConfig: async () => false },
        };

        await EmbeddedActions.prototype.toggleActionVisibility.call(self, 9);

        expect(self.embeddedInfos.visibleEmbeddedActions).toEqual([7]);
    });
});

describe("EmbeddedActions.toggleBar", () => {
    test("re-entrant call is ignored while a toggle is in flight", async () => {
        let applyCalls = 0;
        let release;
        const gate = new Promise((resolve) => {
            release = resolve;
        });
        const self = {
            embeddedInfos: { showEmbedded: false },
            async _applyBarVisibility() {
                applyCalls++;
                await gate;
            },
        };

        const first = EmbeddedActions.prototype.toggleBar.call(self);
        const second = EmbeddedActions.prototype.toggleBar.call(self);
        release();
        await Promise.all([first, second]);

        expect(applyCalls).toBe(1);
        expect(self.embeddedInfos.showEmbedded).toBe(true);
    });

    test("a failing _applyBarVisibility releases the guard and keeps the state", async () => {
        const self = {
            embeddedInfos: { showEmbedded: false },
            async _applyBarVisibility() {
                throw new Error("boom");
            },
        };

        await expect(EmbeddedActions.prototype.toggleBar.call(self)).rejects.toThrow();

        expect(self.embeddedInfos.showEmbedded).toBe(false);
        expect(self._togglingBar).toBe(false);

        // The guard is released: a retry goes through.
        self._applyBarVisibility = async () => {};
        await EmbeddedActions.prototype.toggleBar.call(self);
        expect(self.embeddedInfos.showEmbedded).toBe(true);
    });
});

describe("EmbeddedActions.saveNewAction", () => {
    /**
     * Build a minimal `this` for saveNewAction.
     * @param {Object} params
     * @param {Object} params.orm
     * @param {Object} params.currentEmbeddedAction
     */
    function makeSaveSelf({ orm, currentEmbeddedAction }) {
        const notifications = [];
        return {
            embeddedInfos: {
                newActionName: "My action",
                newActionIsShared: true,
                embeddedActions: [{ id: 7, name: "Existing" }],
                currentEmbeddedAction,
                visibleEmbeddedActions: [7],
            },
            orm,
            notificationService: {
                add: (_msg, opts) => notifications.push(opts.type),
            },
            configHandler: { setEmbeddedActionsConfig: async () => true },
            env: {
                config: { viewType: "list", actionId: 999 },
                searchModel: {
                    globalContext: { active_id: 5 },
                    createNewFavorite: async () => 1,
                },
            },
            _notifications: notifications,
        };
    }

    test("duplicate name returns false without creating anything", async () => {
        let created = false;
        const self = makeSaveSelf({
            orm: {
                create: async () => {
                    created = true;
                    return [123];
                },
            },
            currentEmbeddedAction: {
                parent_action_id: [1, "Parent"],
                action_id: [42, "Action"],
                parent_res_model: "res.partner",
            },
        });
        self.embeddedInfos.newActionName = "Existing";

        const saved = await EmbeddedActions.prototype.saveNewAction.call(self);

        expect(saved).toBe(false);
        expect(created).toBe(false);
        expect(self._notifications).toEqual(["danger"]);
    });

    test("[id, name] tuple action_id is normalized to the id", async () => {
        let createdValues = null;
        const self = makeSaveSelf({
            orm: {
                create: async (_model, [values]) => {
                    createdValues = values;
                    return [123];
                },
            },
            currentEmbeddedAction: {
                parent_action_id: [1, "Parent"],
                action_id: [42, "Action"],
                parent_res_model: "res.partner",
            },
        });

        const saved = await EmbeddedActions.prototype.saveNewAction.call(self);

        expect(saved).toBe(true);
        expect(createdValues.action_id).toBe(42);
        expect(createdValues.parent_action_id).toBe(1);
        expect(self.embeddedInfos.visibleEmbeddedActions).toEqual([7, 123]);
    });

    test("bare numeric action_id is used as-is, not replaced by the current action", async () => {
        let createdValues = null;
        const self = makeSaveSelf({
            orm: {
                create: async (_model, [values]) => {
                    createdValues = values;
                    return [123];
                },
            },
            // Synthetic parent entry built by executeActionButton: bare ids.
            currentEmbeddedAction: {
                parent_action_id: 1,
                action_id: 42,
                parent_res_model: "res.partner",
            },
        });

        await EmbeddedActions.prototype.saveNewAction.call(self);

        expect(createdValues.action_id).toBe(42);
    });
});
