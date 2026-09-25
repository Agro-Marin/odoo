// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registry } from "@web/core/registry";
import { recordResParams } from "@web/views/view_button/view_button";

import { activateTarget } from "./numbers/targets.js";

/**
 * @typedef {import("./interpreter/interpreter.js").Proposal} Proposal
 * @typedef {{
 *   services: Record<string, any>,
 *   submit: (text: string) => Promise<void>,
 *   undo: () => Promise<void>,
 *   showHelp: () => void,
 *   showNumbers: () => void,
 *   hideNumbers: () => void,
 *   targetView: (proposal: Proposal) => import("@web/views/active_view").ActiveView,
 *   getService: (name: string) => any,
 *   startSession: (session: { label: string, stop: () => Promise<any> }) => void,
 *   report: (message: string) => void,
 * }} ExecutionContext
 * @typedef {(() => Promise<any> | any) | null} Undo
 */

/**
 * What another module teaches the executor: a proposal kind the interpreter
 * emits, carried out by `(proposal, context) => Promise<Undo>`.
 */
export const voiceExecutorRegistry = registry.category("voice_executors");

const HOTKEYS = {
    next: "alt+f",
    previous: "alt+d",
    new_record: "alt+c",
    save: "alt+s",
    discard: "alt+j",
};

/**
 * The same path the keyboard takes, so a spoken "save" goes through the
 * controller's save coordinator exactly as Alt+S does.
 *
 * @param {Record<string, any>} services
 * @param {string} hotkey
 */
function press(services, hotkey) {
    return services.hotkey.dispatch({
        activeElement: services.ui.activeElement,
        hotkey,
        isRepeated: false,
        target: document.body,
        shouldProtectEditable: false,
    });
}

/**
 * @param {Record<string, any>} services
 * @param {Proposal} proposal
 */
export function targetView(services, proposal) {
    const view = proposal.target ?? services.active_view.current;
    if (!view || !services.active_view.has(view)) {
        throw new Error(_t("The view this was said to is no longer open."));
    }
    return view;
}

/**
 * @param {Proposal} proposal
 * @param {ExecutionContext} context
 * @returns {Promise<Undo>}
 */
export async function execute(proposal, context) {
    const { services } = context;
    switch (proposal.kind) {
        case "help":
            context.showHelp();
            return null;
        case "open_home":
            await services.home_menu.toggle(true);
            return () => services.home_menu.toggle(false);
        case "open_menu":
            await services.menu.selectMenu(proposal.menu);
            if (proposal.then) {
                await new Promise((resolve) => requestAnimationFrame(resolve));
                await context.submit(proposal.then);
            }
            return null;
        case "switch_view":
            await services.action.switchView(proposal.viewType);
            return null;
        case "back":
            targetView(services, proposal).config.historyBack();
            return null;
        case "pager":
            press(
                services,
                HOTKEYS[/** @type {"next" | "previous"} */ (proposal.direction)],
            );
            return null;
        case "new_record":
        case "save":
        case "discard":
            press(services, HOTKEYS[proposal.kind]);
            return null;
        case "undo":
            await context.undo();
            return null;
        case "clear_search":
            await targetView(services, proposal).searchModel.clearQuery();
            return null;
        case "search": {
            const { searchModel } = targetView(services, proposal);
            const before = new Set(
                searchModel.facets.map((/** @type {any} */ f) => f.groupId),
            );
            await searchModel.applySearchSpec(proposal.spec);
            const added = searchModel.facets
                .map((/** @type {any} */ f) => f.groupId)
                .filter((/** @type {any} */ groupId) => !before.has(groupId));
            return async () => {
                for (const groupId of added) {
                    await searchModel.deactivateGroup(groupId);
                }
            };
        }
        case "open_record": {
            const { controller } = targetView(services, proposal);
            await controller.openRecord(controller.model.root.records[proposal.index]);
            return null;
        }
        case "set_field": {
            const record = targetView(services, proposal).controller.model.root;
            const previous = record.data[proposal.fieldName];
            await record.update({ [proposal.fieldName]: proposal.value });
            return () => record.update({ [proposal.fieldName]: previous });
        }
        case "click_button": {
            const { controller } = targetView(services, proposal);
            const record = controller.model.root;
            await controller.env.onClickViewButton({
                clickParams: proposal.button.clickParams,
                getResParams: () => recordResParams(record),
            });
            return null;
        }
        case "show_numbers":
            context.showNumbers();
            return null;
        case "hide_numbers":
            context.hideNumbers();
            return null;
        case "click_target":
            if (!proposal.element?.isConnected) {
                throw new Error(_t("That is no longer on screen."));
            }
            activateTarget(proposal.element);
            return null;
        case "run_command":
            await proposal.command.action();
            return null;
    }
    const extension = voiceExecutorRegistry.get(proposal.kind, null);
    if (extension) {
        return extension(proposal, context);
    }
    throw new Error(`Unknown proposal "${proposal.kind}"`);
}
