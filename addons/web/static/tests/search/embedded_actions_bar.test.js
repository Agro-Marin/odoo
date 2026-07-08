// @ts-check

/**
 * Pure unit tests for EmbeddedActions.deleteAction.
 *
 * deleteAction is a plain async method that only touches this.orm,
 * this.configHandler and this.embeddedInfos, so tests build a minimal `this`
 * and invoke the method directly (EmbeddedActions.prototype.deleteAction.call)
 * rather than mounting the full OWL component tree.
 */

import { describe, expect, test } from "@odoo/hoot";
import { EmbeddedActions } from "@web/search/embedded_actions_bar/embedded_actions_bar";

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
