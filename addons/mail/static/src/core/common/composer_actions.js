/** @odoo-module native */
import { Action, ACTION_TAGS, UseActions } from "@mail/core/common/action";
import { toRaw, useComponent, useEffect, useRef, useState } from "@odoo/owl";
import { useEmojiPicker } from "@web/components/emoji_picker";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { markEventHandled } from "@web/core/utils/dom/events";
import { useService } from "@web/core/utils/hooks";
export const composerActionsRegistry = registry.category("mail.composer/actions");

/** @typedef {import("@odoo/owl").Component} Component */
/**
 * @typedef {{ isOpen?: boolean, open: (options?: {el?: HTMLElement|null}) => void, close: () => void, }} ComposerPicker
 */
/**
 * @typedef {Component & { voiceRecorder?: {isOpen?: boolean}, sendMessageState?: {active: boolean}, isSendButtonDisabled?: boolean, fullComposer?: {isOpen?: boolean}, fileUploaderRef?: {el?: HTMLElement|null}, allowUpload?: boolean, setActivePicker?: (picker: ComposerPicker|null) => void, getActivePicker?: () => ComposerPicker|null, pickerTargetRef?: {el?: HTMLElement|null}, quickActionsRef?: {el?: HTMLElement|null}, moreActionsRef?: {el?: HTMLElement|null}, extraActionsRef?: {el?: HTMLElement|null}, sendMessage?: () => void|Promise<void>, sendGifMessage?: (gif: any) => void|Promise<void>, addEmoji?: (str: string) => any, onClickInsertCannedResponse?: (ev: Event) => void, onClickFullComposer?: (ev: Event) => void, }} ComposerActionOwner
 */
/**
 * @typedef {import("@mail/core/common/action").ActionDefinition<ComposerActionOwner, ActionParams, ComposerAction>} ActionDefinition
 */
/** @typedef {import("models").Composer} Composer */
/** @typedef {import("@mail/core/common/action").ActionParams<ComposerActionOwner> & { action: ComposerAction, composer: Composer }} ActionParams */
/**
 * @typedef {Object} ComposerActionSpecificDefinition
 * @property {boolean|((this: ComposerAction, params: ActionParams) => boolean)} [condition=true]
 * @property {boolean} [isPicker]
 * @property {string|((comp: Component) => string)} [pickerName]
 */
/**
 * @typedef {ActionDefinition & ComposerActionSpecificDefinition} ComposerActionDefinition
 */
/**
 * @param {string} id
 * @param {ComposerActionDefinition} definition
 */
export function registerComposerAction(id, definition) {
    composerActionsRegistry.add(id, definition);
}

/**
 * @param {import("@odoo/owl").Component} component
 * @param {ComposerAction} action
 * @param {Event} ev
 */
export function pickerOnClick(component, action, ev) {
    let anchorEl;
    if (component.ui.isSmall) {
        anchorEl = component.pickerTargetRef.el;
    } else if (!anchorEl) {
        if (action.sequenceQuick) {
            anchorEl = component.quickActionsRef.el;
        } else {
            anchorEl = component.moreActionsRef.el ?? component.extraActionsRef.el;
        }
    }
    const previousPicker = component.getActivePicker();
    previousPicker?.close();
    if (toRaw(previousPicker) === toRaw(action.picker)) {
        component.setActivePicker(null);
    } else {
        component.setActivePicker(action.picker);
        component.getActivePicker().open({ el: anchorEl });
    }
}

/**
 * @param {ComposerAction} action
 * @param {() => ComposerPicker} func
 */
export function pickerSetup(action, func) {
    const component = useComponent();
    component.pickerTargetRef = useRef("picker-target");
    component.quickActionsRef = useRef("quick-actions");
    component.moreActionsRef = useRef("more-actions");
    component.extraActionsRef = useRef("extra-actions");
    action.ref = useRef(action.id);
    action.picker = func();
}

registerComposerAction("send-message", {
    /** @param {ActionParams} params */
    btnClass: ({ action }) =>
        action.isActive ? "o-sendMessageActive o-text-white shadow-sm" : "",
    /** @param {ActionParams} params */
    condition: ({ composer, owner, store }) =>
        (store.env.isSmall && composer.message) ||
        (!owner.env.inChatter && !composer.message),
    /** @param {ActionParams} params */
    disabledCondition: ({ owner }) => owner.isSendButtonDisabled,
    icon: "fa-regular fa-paper-plane",
    /** @param {ActionParams} params */
    isActive: ({ owner }) => owner.sendMessageState.active,
    /** @param {ActionParams} params */
    name: ({ composer, owner }) =>
        composer.message
            ? _t("Save editing")
            : composer.targetThread?.isChannelKind
              ? _t("Send")
              : owner.props.type === "note"
                ? _t("Log")
                : _t("Send"),
    /** @param {ActionParams} params */
    onSelected: ({ owner }) => owner.sendMessage(),
    /** @param {ActionParams} params */
    setup: ({ owner }) => {
        owner.sendMessageState = useState({ active: false });
        useEffect(
            () => {
                owner.sendMessageState.active = !owner.isSendButtonDisabled;
            },
            () => [owner.isSendButtonDisabled],
        );
    },
    sequenceQuick: 30,
});
registerComposerAction("add-emoji", {
    icon: "fa-regular fa-face-smile",
    isPicker: true,
    pickerName: _t("Emoji"),
    name: _t("Add Emojis"),
    /**
     * @param {ActionParams} params
     * @param {Event} ev
     */
    onSelected({ owner }, ev) {
        pickerOnClick(owner, this, ev);
        markEventHandled(ev, "Composer.onClickAddEmoji");
    },
    /** @param {ActionParams} params */
    setup({ owner }) {
        pickerSetup(this, () =>
            useEmojiPicker(
                undefined,
                {
                    /** @param {string} emoji */
                    onSelect: (emoji) => owner.addEmoji(emoji),
                    onClose: () => owner.setActivePicker(null),
                },
                { arrow: false },
            ),
        );
    },
    sequenceQuick: 20,
});
registerComposerAction("upload-files", {
    /** @param {ActionParams} params */
    condition: ({ owner }) => owner.allowUpload,
    icon: "fa-solid fa-paperclip",
    name: _t("Attach Files"),
    /**
     * @param {ActionParams} params
     * @param {Event} ev
     */
    onSelected: ({ composer: comp, owner }, ev) => {
        owner.fileUploaderRef.el?.click();
        const composer = toRaw(comp);
        markEventHandled(ev, "composer.clickOnAddAttachment");
        composer.autofocus++;
    },
    /** @param {ActionParams} params */
    setup: ({ owner }) => (owner.fileUploaderRef = useRef("file-uploader")),
    sequence: 20,
});
registerComposerAction("open-full-composer", {
    /** @param {ActionParams} params */
    condition: ({ composer, owner }) =>
        !composer.message &&
        owner.props.showFullComposer &&
        composer.targetThread &&
        !composer.targetThread.isChannelKind &&
        !owner.env.inFrontendPortalChatter,
    /** @param {ActionParams} params */
    hasBtnBg: ({ composer, owner }) =>
        (composer.restoredFromFullComposer && !owner.fullComposer.isOpen) || undefined,
    hotkey: "shift+c",
    icon: "fa-solid fa-up-right-and-down-left-from-center",
    /** @param {ActionParams} params */
    isActive: ({ composer, owner }) =>
        (composer.restoredFromFullComposer && !owner.fullComposer.isOpen) || undefined,
    name: _t("Open Full Composer"),
    /** @param {ActionParams} params */
    onSelected: ({ owner }) => owner.onClickFullComposer(),
    sequence: 30,
    /** @param {ActionParams} params */
    tags: ({ composer, owner }) =>
        composer.restoredFromFullComposer && !owner.fullComposer.isOpen
            ? [ACTION_TAGS.PRIMARY]
            : undefined,
});
registerComposerAction("add-canned-response", {
    /** @param {ActionParams} params */
    condition: ({ composer, store }) =>
        store.hasCannedResponses &&
        composer.targetThread &&
        store.env.services["mail.suggestion"]
            .getSupportedDelimiters(composer.targetThread)
            .find(([delimiter]) => delimiter === "::"),
    icon: "fa-regular fa-file-lines",
    name: _t("Insert a Canned response"),
    /**
     * @param {ActionParams} params
     * @param {Event} ev
     */
    onSelected: ({ owner }, ev) => owner.onClickInsertCannedResponse(ev),
    sequence: 5,
});

/** @extends {Action<ComposerActionOwner, ComposerActionDefinition>} */
export class ComposerAction extends Action {
    /** @type {() => Composer} */
    composerFn;
    /**
     * @type {ComposerPicker}
     */
    picker;
    /** @type {{el?: HTMLElement|null}} */
    ref;

    /**
     * @param {Object} param0
     * @param {Composer|(() => Composer)} param0.composer
     */
    constructor({ composer }) {
        super(...arguments);
        this.composerFn = typeof composer === "function" ? composer : () => composer;
    }

    /**
     * @param {ActionParams} param0
     * @param {Composer} param0.composer
     */
    _disabledCondition({ composer }) {
        if (composer.restoredFromFullComposer && this.id !== "open-full-composer") {
            return true;
        }
        return super._disabledCondition(...arguments);
    }

    get params() {
        return Object.assign(super.params, { composer: this.composerFn() });
    }

    get isPicker() {
        return this.definition.isPicker;
    }

    get pickerName() {
        return typeof this.definition.pickerName === "function"
            ? this.definition.pickerName(this._component)
            : this.definition.pickerName;
    }
}

/** @extends {UseActions<ComposerAction>} */
class UseComposerActions extends UseActions {
    /**
     * @type {ComposerPicker|null}
     */
    activePicker = null;

    get partition() {
        const res = super.partition;
        const actions = this.transformedActions.filter((action) => action.condition);
        const groupedPickers = Object.groupBy(
            actions.filter((a) => a.isPicker),
            /** @param {ComposerAction} a */
            (a) => (a.sequenceQuick ? "quick" : "other"),
        );
        groupedPickers.quick?.sort((a1, a2) => a1.sequenceQuick - a2.sequenceQuick);
        groupedPickers.other?.sort((a1, a2) => a1.sequence - a2.sequence);
        const pickers = (groupedPickers.other ?? []).concat(groupedPickers.quick ?? []);
        return Object.assign(res, { pickers });
    }
}

/**
 * @param {Object} [params0={}]
 * @param {Composer|(() => Composer)} [params0.composer]
 */
export function useComposerActions({ composer } = {}) {
    const component = useComponent();
    const transformedActions = composerActionsRegistry
        .getEntries()
        .map(
            ([id, definition]) =>
                new ComposerAction({ owner: component, id, definition, composer }),
        );
    for (const action of transformedActions) {
        action.setup();
    }
    const state = useState(
        new UseComposerActions(component, transformedActions, useService("mail.store")),
    );
    component.getActivePicker = () => state.activePicker;
    component.setActivePicker = /** @param {ComposerPicker|null} newActivePicker */ (
        newActivePicker,
    ) => (state.activePicker = newActivePicker);
    return state;
}
