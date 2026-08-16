/** @odoo-module native */
import { isRecord, STORE_SYM } from "@mail/model/misc";
import { Component, toRaw } from "@odoo/owl";
import { DropdownState } from "@web/components/dropdown";
import { useService } from "@web/core/utils/hooks";
import { SignalStore } from "@web/core/utils/reactive";
export const ACTION_TAGS = Object.freeze({
    DANGER: "DANGER",
    SUCCESS: "SUCCESS",
    PRIMARY: "PRIMARY",
    IMPORTANT_BADGE: "IMPORTANT_BADGE",
    WARNING_BADGE: "WARNING_BADGE",
    CALL_LAYOUT: "CALL_LAYOUT",
    JOIN_LEAVE_CALL: "JOIN_LEAVE_CALL",
});

/** @typedef {import("@mail/model/record").Record} Record */
/**
 * @typedef {Component|Record} ActionOwner
 */
/**
 * @template {ActionOwner} [O=ActionOwner]
 * @typedef {{ action: Action<O>, store: import("models").Store, owner: O }} ActionParams
 */
/**
 * @template {ActionOwner} [O=ActionOwner]
 * @template {ActionParams<O>} [P=ActionParams<O>] what a definition callback is
 * @template {Action<O>} [A=Action<O>] the `this` a definition callback runs
 * @typedef {Object} ActionDefinition
 * @property {boolean|((this: A, params: P) => boolean)} [badge]
 * @property {string|((this: A, params: P) => string)} [badgeIcon]
 * @property {string|((this: A, params: P) => string)} [badgeText]
 * @property {string|((this: A, params: P) => string)} [btnClass]
 * @property {import("@odoo/owl").ComponentConstructor<any, import("@web/env").OdooEnv>} [component]
 * @property {boolean|((this: A, params: P) => boolean)} [componentCondition=true]
 * @property {(this: A, params: P) => Object} [componentProps]
 * @property {boolean|((this: A, params: P) => boolean)} [disabledCondition]
 * @property {boolean} [dropdown]
 * @property {import("@odoo/owl").ComponentConstructor<any, import("@web/env").OdooEnv>|((this: A, params: P) => import("@odoo/owl").ComponentConstructor<any, import("@web/env").OdooEnv>)} [dropdownComponent]
 * @property {Object|((this: A, params: P) => Object)} [dropdownComponentProps]
 * @property {string|((this: A, params: P) => string)} [dropdownMenuClass]
 * @property {string|((this: A, params: P) => string)} [dropdownPosition]
 * @property {DropdownState|((this: A, params: P) => DropdownState)} [dropdownState]
 * @property {string|((this: A, params: P) => string)} [dropdownTemplate]
 * @property {Object|((this: A, params: P) => Object)} [dropdownTemplateParams]
 * @property {boolean|((this: A, params: P) => boolean)} [hasBtnBg]
 * @property {string|((this: A, params: P) => string)} [hotkey]
 * @property {string|((this: A, params: P) => string)} [icon]
 * @property {boolean|((this: A, params: P) => boolean)} [inlineName=false]
 * @property {boolean|((this: A, params: P) => boolean)} [isActive]
 * @property {string|((this: A, params: P) => string)} [name]
 * @property {(this: A, params: P, ev: Event) => void|Promise<any>} [onSelected]
 * @property {number|((this: A, params: P) => number)} [sequence]
 * @property {number|((this: A, params: P) => number)} [sequenceGroup]
 * @property {number|((this: A, params: P) => number)} [sequenceQuick]
 * @property {(this: A, params: P) => void} [setup]
 * @property {string|string[]|((this: A, params: P) => string|string[])} [tags]
 * @property {Action<O>[]|Array<Action<O>[]>} [actions]
 * @property {boolean} [isMoreAction]
 */
/**
 * @template {ActionOwner} [O=ActionOwner] what hosts this action. A subclass
 * @template {ActionDefinition<O, any, any>} [D=ActionDefinition<O, any, any>] the
 */
export class Action {
    /** @type {D} */
    definition;
    /** @type {O} */
    owner;
    /** @type {string} */
    id;
    /** @type {import("models").Store} */
    store;

    /**
     * @param {Object} params
     * @param {O} params.owner
     * @param {string} params.id
     * @param {D} params.definition
     * @param {import("models").Store} [params.store]
     */
    constructor({ owner, id, definition, store }) {
        this.definition = definition;
        this.id = id;
        this.owner = owner;
        const rawOwner = /** @type {any} */ (toRaw(owner));
        this.store =
            store ??
            (rawOwner[STORE_SYM]
                ? /** @type {import("models").Store} */ (owner)
                : isRecord(owner)
                  ? /** @type {import("@mail/model/record").Record} */ (owner).store
                  : useService("mail.store"));
    }

    get params() {
        return { action: this, store: this.store, owner: this.owner };
    }

    /**
     * @param {string} name
     * @returns {any}
     */
    _option(name) {
        const value = /** @type {Record<string, any>} */ (this.definition)[name];
        return typeof value === "function" ? value.call(this, this.params) : value;
    }

    /**
     * @param {string} name
     * @param {any} fallback
     */
    _optionOr(name, fallback) {
        const value = /** @type {Record<string, any>} */ (this.definition)[name];
        return typeof value === "function"
            ? value.call(this, this.params)
            : (value ?? fallback);
    }

    /** @param {string} name */
    _callOption(name) {
        return /** @type {Record<string, any>} */ (this.definition)[name]?.call(
            this,
            this.params,
        );
    }

    /** @param {ActionParams<O>} action */
    _badge(action) {}
    get badge() {
        return this._badge(this.params) ?? this._option("badge");
    }

    /** @param {ActionParams<O>} action */
    _badgeIcon(action) {}
    get badgeIcon() {
        return this._badgeIcon(this.params) ?? this._option("badgeIcon");
    }

    /** @param {ActionParams<O>} action */
    _badgeText(action) {}
    get badgeText() {
        return this._badgeText(this.params) ?? this._option("badgeText");
    }

    /** @param {ActionParams<O>} action */
    _btnClass(action) {}
    get btnClass() {
        return this._btnClass(this.params) ?? this._option("btnClass");
    }

    /** @param {ActionParams<O>} action */
    _component(action) {}
    get component() {
        return this._component(this.params) ?? this.definition.component;
    }

    /** @param {ActionParams<O>} action */
    _componentCondition(action) {}
    get componentCondition() {
        return (
            this._componentCondition(this.params) ??
            this._optionOr("componentCondition", true)
        );
    }

    /** @param {ActionParams<O>} action */
    _componentProps(action) {}
    get componentProps() {
        return this._componentProps(this.params) ?? this._callOption("componentProps");
    }

    /** @param {ActionParams<O>} action */
    _condition(action) {}
    get condition() {
        return this._condition(this.params) ?? this._optionOr("condition", true);
    }

    /** @param {ActionParams<O>} action */
    _disabledCondition(action) {}
    get disabledCondition() {
        return Boolean(
            this._disabledCondition(this.params) ??
            this._callOption("disabledCondition"),
        );
    }

    /** @param {ActionParams<O>} action */
    _dropdown(action) {}
    get dropdown() {
        return this._dropdown(this.params) ?? this.definition.dropdown;
    }

    /** @param {ActionParams<O>} action */
    _dropdownComponent(action) {}
    get dropdownComponent() {
        return (
            this._dropdownComponent(this.params) ??
            (typeof this.definition.dropdownComponent === "function" &&
            Object.getPrototypeOf(this.definition.dropdownComponent) !== Component
                ? this.definition.dropdownComponent.call(this, this.params)
                : this.definition.dropdownComponent)
        );
    }

    /** @param {ActionParams<O>} action */
    _dropdownComponentProps(action) {}
    get dropdownComponentProps() {
        return (
            this._dropdownComponentProps(this.params) ??
            this._option("dropdownComponentProps")
        );
    }

    /** @param {ActionParams<O>} action */
    _dropdownMenuClass(action) {}
    get dropdownMenuClass() {
        return (
            this._dropdownMenuClass(this.params) ?? this._option("dropdownMenuClass")
        );
    }

    /** @param {ActionParams<O>} action */
    _dropdownPosition(action) {}
    get dropdownPosition() {
        return this._dropdownPosition(this.params) ?? this._option("dropdownPosition");
    }

    /** @param {ActionParams<O>} action */
    _dropdownState(action) {}
    get dropdownState() {
        return this._dropdownState(this.params) ?? this._option("dropdownState");
    }

    /** @param {ActionParams<O>} action */
    _dropdownTemplate(action) {}
    get dropdownTemplate() {
        return this._dropdownTemplate(this.params) ?? this._option("dropdownTemplate");
    }

    /** @param {ActionParams<O>} action */
    _dropdownTemplateParams(action) {}
    get dropdownTemplateParams() {
        return (
            this._dropdownTemplateParams(this.params) ??
            this._option("dropdownTemplateParams")
        );
    }

    /** @param {ActionParams<O>} action */
    _hasBtnBg(action) {}
    get hasBtnBg() {
        return this._hasBtnBg(this.params) ?? this._option("hasBtnBg");
    }

    /** @param {ActionParams<O>} action */
    _hotkey(action) {}
    get hotkey() {
        return this._hotkey(this.params) ?? this._option("hotkey");
    }

    /** @param {ActionParams<O>} action */
    _icon(action) {}
    get icon() {
        return this._icon(this.params) ?? this._option("icon");
    }

    /** @param {ActionParams<O>} action */
    _inlineName(action) {}
    get inlineName() {
        return this._inlineName(this.params) ?? this._option("inlineName") ?? false;
    }

    /** @param {ActionParams<O>} action */
    _isActive(action) {}
    get isActive() {
        return Boolean(this._isActive(this.params) ?? this._option("isActive"));
    }

    /** @param {ActionParams<O>} action */
    _name(action) {}
    get name() {
        return this._name(this.params) ?? this._option("name");
    }

    /** @param {ActionParams<O>} action */
    _onSelected(action, ev) {}
    /** @param {Event} ev */
    onSelected(ev) {
        return (
            this._onSelected(this.params, ev) ??
            this.definition.onSelected?.call(this, this.params, ev)
        );
    }

    /** @param {ActionParams<O>} action */
    _sequence(action) {}
    get sequence() {
        return this._sequence(this.params) ?? this._option("sequence");
    }

    /** @param {ActionParams<O>} action */
    _sequenceGroup(action) {}
    get sequenceGroup() {
        return this._sequenceGroup(this.params) ?? this._option("sequenceGroup");
    }

    /** @param {ActionParams<O>} action */
    _sequenceQuick(action) {}
    get sequenceQuick() {
        return this._sequenceQuick(this.params) ?? this._option("sequenceQuick");
    }

    /** @param {ActionParams<O>} action */
    _setup(action) {}
    setup() {
        return (
            this._setup(this.params) ?? this.definition.setup?.call(this, this.params)
        );
    }

    /** @param {ActionParams<O>} action */
    _tags(action) {}
    get tags() {
        const res = this._tags(this.params) ?? this._option("tags");
        return Array.isArray(res) ? res : [res];
    }

    get tagClassNames() {
        return this.tags.map((tag) => `o-tag-${tag}`).join(" ");
    }
}

/**
 * @template {Action<any>} [A=Action] the action class this family builds.
 */
export class UseActions extends SignalStore {
    /**
     * @type {new (...args: any[]) => A}
     */
    ActionClass = /** @type {any} */ (Action);
    /** @type {Component} */
    component;
    /** @type {Map<string, A>} */
    moreActions = new Map();
    /** @type {A[]} */
    transformedActions;
    /** @type {import("models").Store} */
    store;

    /**
     * @param {Component} component
     * @param {A[]} transformedActions
     * @param {import("models").Store} store
     */
    constructor(component, transformedActions, store) {
        super();
        this.component = component;
        this.transformedActions = transformedActions;
        this.store = store;
    }

    /**
     * @param {ActionDefinition} data
     * @param {string} id
     * @returns {A}
     */
    more(data = {}, id) {
        if (!toRaw(this).moreActions.get(id)) {
            toRaw(this).moreActions.set(
                id,
                new this.ActionClass({
                    owner: this.component,
                    id: `more-action:${id}`,
                    definition: {
                        ...data,
                        dropdown: true,
                        dropdownState: new DropdownState(),
                        icon: data?.icon ?? "oi oi-ellipsis-v",
                        /** @param {ActionParams} params */
                        isActive: ({ action }) => action.dropdownState.isOpen,
                        isMoreAction: true,
                        sequence: data.sequence ?? 1000,
                    },
                    store: this.store,
                }),
            );
        }
        const moreAction = this.moreActions.get(id);
        moreAction.definition.actions = data.actions;
        return moreAction;
    }

    get actions() {
        const actions = this.transformedActions
            .filter((action) => action.condition)
            .sort((a1, a2) => a1.sequence - a2.sequence);
        return actions;
    }

    get partition() {
        const actions = this.transformedActions.filter((action) => action.condition);
        const quick = actions
            .filter((a) => a.sequenceQuick)
            .sort((a1, a2) => a1.sequenceQuick - a2.sequenceQuick);
        const grouped = actions.filter((a) => a.sequenceGroup);
        /** @type {{[sequenceGroup: string]: A[]}} */
        const groups = {};
        for (const a of grouped) {
            if (!(a.sequenceGroup in groups)) {
                groups[a.sequenceGroup] = [];
            }
            groups[a.sequenceGroup].push(a);
        }
        const sortedGroups = Object.entries(groups).sort(
            ([groupId1], [groupId2]) => Number(groupId1) - Number(groupId2),
        );
        for (const [, actions] of sortedGroups) {
            actions.sort((a1, a2) => a1.sequence - a2.sequence);
        }
        const group = sortedGroups.map(([groupId, actions]) => actions);
        const other = actions
            .filter((a) => !a.sequenceQuick && !a.sequenceGroup)
            .sort((a1, a2) => a1.sequence - a2.sequence);
        return { quick, group, other };
    }
}
