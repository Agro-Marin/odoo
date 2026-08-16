/** @odoo-module native */
import { Action, UseActions } from "@mail/core/common/action";
import { SearchMessagesPanel } from "@mail/core/common/search_messages_panel";
import { useComponent, useState, useSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { markEventHandled } from "@web/core/utils/dom/events";
import { useService } from "@web/core/utils/hooks";
export const threadActionsRegistry = registry.category("mail.thread/actions");

/** @typedef {import("@odoo/owl").Component} Component */
/** @typedef {import("models").Thread} Thread */
/**
 * @typedef {Component & { threadActions?: UseThreadActions, isDiscussSidebarChannelActions?: boolean, isDiscussContent?: boolean, root?: {el?: HTMLElement|null}, state?: Object, thread?: Thread, close?: () => void, toggleFold?: () => void, }} ThreadActionOwner
 */
/**
 * @typedef {import("@mail/core/common/action").ActionDefinition<ThreadActionOwner, ActionParams, ThreadAction>} ActionDefinition
 */
/** @typedef {import("@mail/core/common/action").ActionParams<ThreadActionOwner> & { action: ThreadAction, thread: Thread }} ActionParams */
/**
 * @typedef {Object} ThreadActionSpecificDefinition
 * @property {import("@odoo/owl").ComponentConstructor<any, import("@web/env").OdooEnv>} [actionPanelComponent]
 * @property {(this: ThreadAction, params: ActionParams) => Object} [actionPanelComponentProps]
 * @property {(this: ThreadAction, params: ActionParams & { nextActiveAction?: Object }) => void} [close]
 * @property {boolean|((this: ThreadAction, params: ActionParams) => boolean)} [condition=true]
 * @property {string|((this: ThreadAction, params: ActionParams) => string)} [nameClass]
 * @property {(this: ThreadAction, params: ActionParams) => void} [open]
 * @property {string|((this: ThreadAction, params: ActionParams) => string)} [panelOuterClass]
 * @property {boolean} [toggle]
 */
/**
 * @typedef {ActionDefinition & ThreadActionSpecificDefinition} ThreadActionDefinition
 */
/**
 * @param {string} id
 * @param {ThreadActionDefinition} definition
 */
export function registerThreadAction(id, definition) {
    threadActionsRegistry.add(id, definition);
}

registerThreadAction("fold-chat-window", {
    /** @param {ActionParams} params */
    condition: ({ owner }) =>
        owner.props.chatWindow && !owner.isDiscussSidebarChannelActions,
    icon: "oi oi-fw oi-minus",
    /** @param {ActionParams} params */
    name: ({ owner }) => (!owner.props.chatWindow?.isOpen ? _t("Open") : _t("Fold")),
    /** @param {ActionParams} params */
    open: ({ owner }) => owner.toggleFold(),
    /** @param {ActionParams} params */
    sequence: 99,
    sequenceQuick: 20,
});
registerThreadAction("rename-thread", {
    /** @param {ActionParams} params */
    condition: ({ owner, thread }) =>
        thread &&
        owner.props.chatWindow?.isOpen &&
        (thread.is_editable || thread.isDirectChat) &&
        !owner.isDiscussSidebarChannelActions,
    icon: "fa-solid fa-pencil",
    name: _t("Rename Thread"),
    /** @param {ActionParams} params */
    open: ({ owner }) => (owner.state.editingName = true),
    sequence: 30,
    sequenceGroup: 20,
});
registerThreadAction("close", {
    /** @param {ActionParams} params */
    condition: ({ owner }) =>
        owner.props.chatWindow && !owner.isDiscussSidebarChannelActions,
    icon: "oi oi-close",
    name: _t("Close Chat Window (ESC)"),
    /** @param {ActionParams} params */
    open: ({ owner }) => owner.close(),
    sequence: 100,
    sequenceQuick: 10,
});
registerThreadAction("search-messages", {
    actionPanelComponent: SearchMessagesPanel,
    /** @param {ActionParams} params */
    condition: ({ owner, thread }) =>
        (thread?.isChannelKind || thread?.isMailbox) &&
        (!owner.props.chatWindow || owner.props.chatWindow.isOpen) &&
        !owner.isDiscussSidebarChannelActions,
    hotkey: "f",
    panelOuterClass: "o-mail-SearchMessagesPanel bg-inherit",
    icon: "oi oi-fw oi-search",
    /** @param {ActionParams} params */
    name: ({ action }) =>
        action.isActive ? _t("Close Search") : _t("Search Messages"),
    sequence: 20,
    sequenceGroup: 20,
    /** @param {ActionParams} params */
    setup: ({ action }) =>
        useSubEnv({
            searchMenu: {
                open: () => action.open(),
                close: () => {
                    if (action.isActive) {
                        action.close();
                    }
                },
            },
        }),
    toggle: true,
});
/** @extends {Action<ThreadActionOwner, ThreadActionDefinition>} */
export class ThreadAction extends Action {
    /**
     * @type {import("@web/ui/popover/popover_hook").PopoverHookReturnType|null}
     */
    popover = null;
    /** @type {() => Thread} */
    threadFn;

    /**
     * @param {Object} param0
     * @param {ThreadActionOwner} param0.owner
     * @param {string} param0.id
     * @param {ThreadActionDefinition} param0.definition
     * @param {import("models").Store} [param0.store]
     * @param {Thread|(() => Thread)} [param0.thread]
     */
    constructor({ thread }) {
        super(...arguments);
        this.threadFn = typeof thread === "function" ? thread : () => thread;
    }

    get params() {
        return Object.assign(super.params, { thread: this.threadFn() });
    }

    get actionPanelComponent() {
        return this.definition.actionPanelComponent;
    }

    get actionPanelComponentCondition() {
        return (
            this.isActive &&
            this.actionPanelComponent &&
            this.condition &&
            !this.popover
        );
    }

    get actionPanelComponentProps() {
        return this.definition.actionPanelComponentProps?.call(this, this.params);
    }

    /**
     * @param {Object} [options]
     * @param {ThreadAction} [options.nextActiveAction]
     */
    close({ nextActiveAction } = {}) {
        if (this.toggle) {
            this.owner.threadActions.activeAction =
                this.owner.threadActions.actionStack.pop();
        }
        this.definition.close?.call(
            this,
            Object.assign(this.params, { nextActiveAction }),
        );
    }

    get isActive() {
        return this.id === this.owner.threadActions.activeAction?.id;
    }

    get nameClass() {
        return this._option("nameClass");
    }

    /**
     * @param {MouseEvent} [ev]
     * @param {object} [param0]
     * @param {boolean} [param0.keepPrevious]
     */
    onSelected(ev, { keepPrevious } = {}) {
        if (ev) {
            markEventHandled(ev, "ThreadAction.onSelected");
        }
        if (this.toggle && this.isActive) {
            this.close();
        } else {
            this.open({ keepPrevious });
        }
    }

    /**
     * @param {object} [param0]
     * @param {boolean} [param0.keepPrevious]
     */
    open({ keepPrevious } = {}) {
        if (this.toggle) {
            if (this.owner.threadActions.activeAction) {
                if (keepPrevious) {
                    this.owner.threadActions.actionStack.push(
                        this.owner.threadActions.activeAction,
                    );
                } else {
                    this.owner.threadActions.activeAction.close({
                        nextActiveAction: this,
                    });
                }
            }
            this.owner.threadActions.activeAction = this;
        }
        this.definition.open?.call(this, this.params);
    }

    get panelOuterClass() {
        return this._option("panelOuterClass");
    }

    get toggle() {
        return this.definition.toggle;
    }
}

/** @extends {UseActions<ThreadAction>} */
class UseThreadActions extends UseActions {
    ActionClass = ThreadAction;
    /** @type {ThreadAction[]} */
    actionStack = [];
    /** @type {ThreadAction|null} */
    activeAction = null;
}

/**
 * @param {Object} [params0={}]
 * @param {Thread|(() => Thread)} [params0.thread]
 */
export function useThreadActions({ thread } = {}) {
    const component = useComponent();
    const transformedActions = threadActionsRegistry
        .getEntries()
        .map(
            ([id, definition]) =>
                new ThreadAction({ owner: component, id, definition, thread }),
        );
    for (const action of transformedActions) {
        action.setup();
    }
    return useState(
        new UseThreadActions(component, transformedActions, useService("mail.store")),
    );
}
