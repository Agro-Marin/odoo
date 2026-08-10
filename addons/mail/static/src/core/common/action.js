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

/** @typedef {import("@odoo/owl").Component} Component */
/** @typedef {import("@mail/model/record").Record} Record */
/** @typedef {Component|Record} ActionOwner */
/**
 * Argument every action hook and definition callback receives: the `params`
 * getter of the action, which owner-specific subclasses extend (e.g. `message`
 * and `thread` for message actions).
 *
 * @typedef {{ action: Action, store: import("models").Store, owner: ActionOwner }} ActionParams
 */

/**
 * @typedef {Object} ActionDefinition
 * @property {boolean|(params: ActionParams) => boolean} [badge]
 * @property {string|(params: ActionParams) => string} [badgeIcon]
 * @property {string|(params: ActionParams) => string} [badgeText]
 * @property {string|(params: ActionParams) => string} [btnClass]
 * @property {Component} [component]
 * @property {boolean|(params: ActionParams) => boolean} [componentCondition=true]
 * @property {(params: ActionParams) => Object} [componentProps]
 * @property {boolean|(params: ActionParams) => boolean} [disabledCondition]
 * @property {boolean} [dropdown]
 * @property {Component|(params: ActionParams) => Component} [dropdownComponent]
 * @property {Object|(params: ActionParams) => Object} [dropdownComponentProps]
 * @property {string|(params: ActionParams) => string} [dropdownMenuClass]
 * @property {string|(params: ActionParams) => string} [dropdownPosition]
 * @property {DropdownState|(params: ActionParams) => DropdownState} [dropdownState]
 * @property {string|(params: ActionParams) => string} [dropdownTemplate]
 * @property {Object|(params: ActionParams) => Object} [dropdownTemplateParams]
 * @property {boolean|(params: ActionParams) => boolean} [hasBtnBg]
 * @property {string|(params: ActionParams) => string} [hotkey]
 * @property {string|(params: ActionParams) => string} [icon]
 * @property {boolean|(params: ActionParams) => boolean} [inlineName=false]
 * @property {boolean|(params: ActionParams) => boolean} [isActive]
 * @property {string|(params: ActionParams) => string} [name]
 * @property {(params: ActionParams, ev: Event) => void} [onSelected]
 * @property {number|(params: ActionParams) => number} [sequence]
 * @property {boolean|(params: ActionParams) => boolean} [sequenceGroup]
 * @property {boolean|(params: ActionParams) => boolean} [sequenceQuick]
 * @property {() => void} [setup]
 * @property {string|string[]|(params: ActionParams) => string|string[]} [tags]
 */

export class Action {
    /** @type {ActionDefinition}  User-defined explicit definition of this action */
    definition;
    /** @type {ActionOwner} Entity that is using this action */
    owner;
    /** @type {string} Unique id of this action. */
    id;
    /** @type {import("models").Store} */
    store;

    /** param `store` is required for actions made with new Action() by hand in components and outside component.setup() */
    constructor({ owner, id, definition, store }) {
        this.definition = definition;
        this.id = id;
        this.owner = owner;
        const rawOwner = toRaw(owner);
        this.store =
            store ??
            (rawOwner[STORE_SYM]
                ? owner
                : isRecord(owner)
                  ? owner.store
                  : useService("mail.store"));
    }

    get params() {
        return { action: this, store: this.store, owner: this.owner };
    }

    /** @param {ActionParams} action @returns {boolean|undefined} */
    _badge(action) {}
    /** Condition for showing badge on this action */
    get badge() {
        return (
            this._badge(this.params) ??
            (typeof this.definition.badge === "function"
                ? this.definition.badge.call(this, this.params)
                : this.definition.badge)
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _badgeIcon(action) {}
    /** When action shows badge @see badge this property tells the icon inside badge */
    get badgeIcon() {
        return (
            this._badgeIcon(this.params) ??
            (typeof this.definition.badgeIcon === "function"
                ? this.definition.badgeIcon.call(this, this.params)
                : this.definition.badgeIcon)
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _badgeText(action) {}
    /** When action shows badge @see badge this property tells the text inside badge. */
    get badgeText() {
        return (
            this._badgeText(this.params) ??
            (typeof this.definition.badgeText === "function"
                ? this.definition.badgeText.call(this, this.params)
                : this.definition.badgeText)
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _btnClass(action) {}
    get btnClass() {
        return (
            this._btnClass(this.params) ??
            (typeof this.definition.btnClass === "function"
                ? this.definition.btnClass.call(this, this.params)
                : this.definition.btnClass)
        );
    }

    /** @param {ActionParams} action @returns {Component|undefined} */
    _component(action) {}
    /** When provided, this component is mounted for this action. UI/UX of action is fully managed by the component */
    get component() {
        return this._component(this.params) ?? this.definition.component;
    }

    /** @param {ActionParams} action @returns {boolean|undefined} */
    _componentCondition(action) {}
    /** When provided, action.component is conditionally picked based on this condition. When condition is false, the usual UI/UX of action from other explicit definitions is chosen */
    get componentCondition() {
        return (
            this._componentCondition(this.params) ??
            (typeof this.definition.componentCondition === "function"
                ? this.definition.componentCondition.call(this, this.params)
                : (this.definition.componentCondition ?? true))
        );
    }

    /** @param {ActionParams} action @returns {Object|undefined} */
    _componentProps(action) {}
    /** Props to pass to the component of this action. */
    get componentProps() {
        return (
            this._componentProps(this.params) ??
            this.definition.componentProps?.call(this, this.params)
        );
    }

    /** @param {ActionParams} action @returns {boolean|undefined} */
    _condition(action) {}
    /** Condition for availability of this action */
    get condition() {
        return (
            this._condition(this.params) ??
            (typeof this.definition.condition === "function"
                ? this.definition.condition.call(this, this.params)
                : (this.definition.condition ?? true))
        );
    }

    /** @param {ActionParams} action @returns {boolean|undefined} */
    _disabledCondition(action) {}
    /** Condition to disable the button of this action (but still display it). */
    get disabledCondition() {
        return Boolean(
            this._disabledCondition(this.params) ??
            this.definition.disabledCondition?.call(this, this.params),
        );
    }

    /** @param {ActionParams} action @returns {boolean|undefined} */
    _dropdown(action) {}
    /** Determines whether this action opens a dropdown on selection. */
    get dropdown() {
        return this._dropdown(this.params) ?? this.definition.dropdown;
    }

    /** @param {ActionParams} action @returns {Component|undefined} */
    _dropdownComponent(action) {}
    /** When action is a dropdown @see dropdown, this determines an optional component to use for the content slot */
    get dropdownComponent() {
        return (
            this._dropdownComponent(this.params) ??
            (typeof this.definition.dropdownComponent === "function" &&
            Object.getPrototypeOf(this.definition.dropdownComponent) !== Component
                ? this.definition.dropdownComponent.call(this, this.params)
                : this.definition.dropdownComponent)
        );
    }

    /** @param {ActionParams} action @returns {Object|undefined} */
    _dropdownComponentProps(action) {}
    /** When action is a dropdown @see dropdown, this determines optional props to pass to component of the content slot of dropdown. */
    get dropdownComponentProps() {
        return (
            this._dropdownComponentProps(this.params) ??
            (typeof this.definition.dropdownComponentProps === "function"
                ? this.definition.dropdownComponentProps.call(this, this.params)
                : this.definition.dropdownComponentProps)
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _dropdownMenuClass(action) {}
    /** When action is a dropdown @see dropdown, this determines an optional menu class for the dropdown, in addition to default dropdown menu classes */
    get dropdownMenuClass() {
        return (
            this._dropdownMenuClass(this.params) ??
            (typeof this.definition.dropdownMenuClass === "function"
                ? this.definition.dropdownMenuClass.call(this, this.params)
                : this.definition.dropdownMenuClass)
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _dropdownPosition(action) {}
    /** When action is a dropdown @see dropdown, this determines the preferred position of the dropdown */
    get dropdownPosition() {
        return (
            this._dropdownPosition(this.params) ??
            (typeof this.definition.dropdownPosition === "function"
                ? this.definition.dropdownPosition.call(this, this.params)
                : this.definition.dropdownPosition)
        );
    }

    /** @param {ActionParams} action @returns {DropdownState|undefined} */
    _dropdownState(action) {}
    /** When action is a dropdown @see dropdown, this determines the preferred position of the dropdown */
    get dropdownState() {
        return (
            this._dropdownState(this.params) ??
            (typeof this.definition.dropdownState === "function"
                ? this.definition.dropdownState.call(this, this.params)
                : this.definition.dropdownState)
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _dropdownTemplate(action) {}
    /** When action is a dropdown @see dropdown, this determines an optional template to use for the content slot */
    get dropdownTemplate() {
        return (
            this._dropdownTemplate(this.params) ??
            (typeof this.definition.dropdownTemplate === "function"
                ? this.definition.dropdownTemplate.call(this, this.params)
                : this.definition.dropdownTemplate)
        );
    }

    /** @param {ActionParams} action @returns {Object|undefined} */
    _dropdownTemplateParams(action) {}
    /**
     * When action is a dropdown @see dropdown, this determines optional params to pass to template of the content slot of dropdown.
     * The params are provided to template in object `templateParams` with named parameters as given by explicit definition.
     * For example: `{ myParam1: 1 }` is retrieved in template with `templateParams.myParam1`.
     */
    get dropdownTemplateParams() {
        return (
            this._dropdownTemplateParams(this.params) ??
            (typeof this.definition.dropdownTemplateParams === "function"
                ? this.definition.dropdownTemplateParams.call(this, this.params)
                : this.definition.dropdownTemplateParams)
        );
    }

    /** @param {ActionParams} action @returns {boolean|undefined} */
    _hasBtnBg(action) {}
    get hasBtnBg() {
        return (
            this._hasBtnBg(this.params) ??
            (typeof this.definition.hasBtnBg === "function"
                ? this.definition.hasBtnBg.call(this, this.params)
                : this.definition.hasBtnBg)
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _hotkey(action) {}
    /** Determines whether this action has a keyboard hotkey to trigger the onSelected */
    get hotkey() {
        return (
            this._hotkey(this.params) ??
            (typeof this.definition.hotkey === "function"
                ? this.definition.hotkey.call(this, this.params)
                : this.definition.hotkey)
        );
    }

    /** @param {ActionParams} action @returns {string|Object|undefined} */
    _icon(action) {}
    /**
     * Icon for the button this action.
     * - When a string, this is considered an icon as classname (.fa and .oi).
     * - When an object with property `template`, this is an icon rendered in template.
     *   Template params are provided in `params` and passed to template as a `t-set="templateParams"`
     */
    get icon() {
        return (
            this._icon(this.params) ??
            (typeof this.definition.icon === "function"
                ? this.definition.icon.call(this, this.params)
                : this.definition.icon)
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _inlineName(action) {}
    /** If set, when action is used in inline, shows action name in addition to icon. */
    get inlineName() {
        return (
            this._inlineName(this.params) ??
            (typeof this.definition.inlineName === "function"
                ? this.definition.inlineName.call(this, this.params)
                : this.definition.inlineName) ??
            false
        );
    }

    /** @param {ActionParams} action @returns {boolean|undefined} */
    _isActive(action) {}
    /** States whether this action is currently active. */
    get isActive() {
        return Boolean(
            this._isActive(this.params) ??
            (typeof this.definition.isActive === "function"
                ? this.definition.isActive.call(this, this.params)
                : this.definition.isActive),
        );
    }

    /** @param {ActionParams} action @returns {string|undefined} */
    _name(action) {}
    /** Name of this action, displayed to the user. */
    get name() {
        return (
            this._name(this.params) ??
            (typeof this.definition.name === "function"
                ? this.definition.name.call(this, this.params)
                : this.definition.name)
        );
    }

    /** @param {ActionParams} action @param {Event} ev @returns {true|undefined} */
    _onSelected(action, ev) {}
    /** Action to execute when this action is selected @param {Event} ev */
    onSelected(ev) {
        return (
            this._onSelected(this.params, ev) ??
            this.definition.onSelected?.call(this, this.params, ev)
        );
    }

    /** @param {ActionParams} action @returns {number|undefined} */
    _sequence(action) {}
    /** Determines the order of this action (smaller first). */
    get sequence() {
        return (
            this._sequence(this.params) ??
            (typeof this.definition.sequence === "function"
                ? this.definition.sequence.call(this, this.params)
                : this.definition.sequence)
        );
    }

    /** @param {ActionParams} action @returns {number|undefined} */
    _sequenceGroup(action) {}
    get sequenceGroup() {
        return (
            this._sequenceGroup(this.params) ??
            (typeof this.definition.sequenceGroup === "function"
                ? this.definition.sequenceGroup.call(this, this.params)
                : this.definition.sequenceGroup)
        );
    }

    /** @param {ActionParams} action @returns {number|undefined} */
    _sequenceQuick(action) {}
    get sequenceQuick() {
        return (
            this._sequenceQuick(this.params) ??
            (typeof this.definition.sequenceQuick === "function"
                ? this.definition.sequenceQuick.call(this, this.params)
                : this.definition.sequenceQuick)
        );
    }

    /** @param {ActionParams} action @returns {true|undefined} */
    _setup(action) {}
    /** setup is executed when the owner is being setup. */
    setup() {
        return (
            this._setup(this.params) ?? this.definition.setup?.call(this, this.params)
        );
    }

    /** @param {ActionParams} action @returns {string|string[]|undefined} */
    _tags(action) {}
    /** If set, list of tags of this action. */
    get tags() {
        const res =
            this._tags(this.params) ??
            (typeof this.definition.tags === "function"
                ? this.definition.tags.call(this, this.params)
                : this.definition.tags);
        return Array.isArray(res) ? res : [res];
    }

    get tagClassNames() {
        return this.tags.map((tag) => `o-tag-${tag}`).join(" ");
    }
}

export class UseActions extends SignalStore {
    ActionClass = Action;
    /** @type {Component} */
    component;
    /** @type {Map<string, Action>} */
    moreActions = new Map();
    /** @type {Action[]} */
    transformedActions;
    /** @type {import("models").Store} */
    store;

    constructor(component, transformedActions, store) {
        super();
        this.component = component;
        this.transformedActions = transformedActions;
        this.store = store;
    }

    /**
     * @typedef {Object} MoreActionSpecificDefinition
     * @property {Action[]|Array<Action[]>} actions
     */
    /** @typedef {ActionDefinition & MoreActionSpecificDefinition} MoreActionDefinition */
    /** @param {MoreActionDefinition} [data] */
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
                        isActive: ({ action }) => action.dropdownState.isOpen,
                        isMoreAction: true,
                        sequence: data.sequence ?? 1000,
                    },
                    store: this.store,
                }),
            );
        }
        // Read (and update) the action through `this` (usually a `useState`
        // proxy): reads like `moreAction.isActive` must subscribe the caller
        // to the dropdown open state, including right after creation.
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
        const groups = {};
        for (const a of grouped) {
            if (!(a.sequenceGroup in groups)) {
                groups[a.sequenceGroup] = [];
            }
            groups[a.sequenceGroup].push(a);
        }
        const sortedGroups = Object.entries(groups).sort(
            ([groupId1], [groupId2]) => groupId1 - groupId2,
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
