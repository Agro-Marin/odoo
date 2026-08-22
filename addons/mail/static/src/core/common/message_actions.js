/** @odoo-module native */
import { Action, ACTION_TAGS, UseActions } from "@mail/core/common/action";
import { QuickReactionMenu } from "@mail/core/common/quick_reaction_menu";
import { toRaw, useComponent, useState } from "@odoo/owl";
import { useEmojiPicker } from "@web/components/emoji_picker";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { luxon } from "@web/core/l10n/luxon";
import { download } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Deferred } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";

import { discussComponentRegistry } from "./discuss_component_registry.js";
const { DateTime } = luxon;

export const messageActionsRegistry = registry.category("mail.message/actions");

/** @typedef {import("@odoo/owl").Component} Component */
/**
 * @typedef {Component & { reactionPicker?: Object, optionsDropdown?: Object, root?: {el?: HTMLElement|null}, isActive?: boolean, shouldHideFromMessageListOnDelete?: boolean, openReactionMenu?: () => void, }} MessageActionOwner
 */
/**
 * @typedef {import("@mail/core/common/action").ActionDefinition<MessageActionOwner, ActionParams, MessageAction>} ActionDefinition
 */
/** @typedef {import("models").Message} Message */
/** @typedef {import("models").Thread} Thread */
/** @typedef {import("@mail/core/common/action").ActionParams<MessageActionOwner> & { action: MessageAction, message: Message, thread: Thread }} ActionParams */
/**
 * @typedef {Object} MessageActionSpecificDefinition
 * @property {boolean|((this: MessageAction, params: ActionParams) => boolean)} [condition=true]
 */
/**
 * @typedef {ActionDefinition & MessageActionSpecificDefinition} MessageActionDefinition
 */
/**
 * @param {string} id
 * @param {MessageActionDefinition} definition
 */
export function registerMessageAction(id, definition) {
    messageActionsRegistry.add(id, definition);
}

registerMessageAction("reaction", {
    component: QuickReactionMenu,
    /** @param {ActionParams} params */
    componentProps: ({ action, message, owner }) => ({
        action,
        message,
        messageActive: owner.isActive,
    }),
    componentCondition: () => !isMobileOS(),
    /** @param {ActionParams} params */
    condition: ({ message, thread }) => message.canAddReaction(thread),
    icon: "oi oi-smile-add",
    name: _t("Add a Reaction"),
    /** @param {ActionParams} params */
    onSelected({ owner }) {
        return owner.reactionPicker.open({
            el: owner.root?.el?.querySelector(`[name="${this.id}"]`),
        });
    },
    /** @param {ActionParams} params */
    setup: ({ message, owner, thread }) =>
        (owner.reactionPicker = useEmojiPicker(undefined, {
            /** @param {string} emoji */
            onSelect: (emoji) => {
                const reaction = message.reactions.find(
                    ({ content, personas }) =>
                        content === emoji && thread.effectiveSelf.in(personas),
                );
                if (!reaction) {
                    message.react(emoji);
                }
            },
        })),
    sequence: 10,
});
registerMessageAction("reply-to", {
    /** @param {ActionParams} params */
    condition: ({ message: msg, thread: thr }) => {
        const message = toRaw(msg);
        const thread = toRaw(thr);
        return (
            message.canReplyTo(thread) ||
            (!(thread?.isChannelKind || thread?.isMailbox) &&
                message.isNote &&
                !message.isSelfAuthored)
        );
    },
    icon: "fa-solid fa-reply",
    name: _t("Reply"),
    /** @param {ActionParams} params */
    onSelected: ({ message: msg, owner, thread: thr }) => {
        const message = toRaw(msg);
        const thread = toRaw(thr);
        const composer = thread.composer;
        if (message.eq(composer.replyToMessage)) {
            composer.replyToMessage = undefined;
            return;
        }
        if (thread.isChannelKind || thread.isMailbox) {
            composer.replyToMessage = message;
        }
        if (thread.isChannelKind) {
            return;
        }
        if (
            !message.isSelfAuthored &&
            message.model !== "discuss.channel" &&
            message.author
        ) {
            composer.insertReplyFromNote(message);
        }
        owner.env.inChatter?.toggleComposer("note", { force: true });
        composer.restoredFromFullComposer = false;
        if (!composer.isFocused) {
            composer.autofocus++;
        }
    },
    /** @param {ActionParams} params */
    sequence: ({ message, store, thread }) =>
        thread?.eq(store.inbox) || message.isSelfAuthored ? 55 : 20,
});
registerMessageAction("toggle-star", {
    /** @param {ActionParams} params */
    condition: ({ message }) => message.canToggleStar,
    /** @param {ActionParams} params */
    icon: ({ message }) =>
        message.starred
            ? "fa-solid fa-star o-mail-Message-starred"
            : "fa-regular fa-star",
    /** @param {ActionParams} params */
    name: ({ message }) => (message.starred ? _t("Remove Star") : _t("Add Star")),
    /** @param {ActionParams} params */
    onSelected: ({ message }) => message.toggleStar(),
    sequence: 30,
});
registerMessageAction("mark-as-read", {
    /** @param {ActionParams} params */
    condition: ({ store, thread }) => thread?.eq(store.inbox),
    icon: "fa-solid fa-check",
    name: _t("Mark as Read"),
    /** @param {ActionParams} params */
    onSelected: ({ message }) => message.setDone(),
    sequence: 40,
});
registerMessageAction("reactions", {
    /** @param {ActionParams} params */
    condition: ({ message }) => message.reactions.length,
    icon: "fa-regular fa-face-smile",
    name: _t("View Reactions"),
    /** @param {ActionParams} params */
    onSelected: ({ owner }) => owner.openReactionMenu(),
    sequence: 50,
});
registerMessageAction("unfollow", {
    /** @param {ActionParams} params */
    condition: ({ message, thread }) => message.canUnfollow(thread),
    icon: "fa-solid fa-user-times",
    name: _t("Unfollow"),
    /** @param {ActionParams} params */
    onSelected: ({ message }) => message.unfollow(),
    sequence: 60,
});
registerMessageAction("edit", {
    /** @param {ActionParams} params */
    condition: ({ message }) => message.editable,
    icon: "fa-solid fa-pencil",
    name: _t("Edit"),
    /** @param {ActionParams} params */
    onSelected: ({ message, owner, thread }) => {
        message.enterEditMode(thread);
        owner.optionsDropdown?.close();
    },
    /** @param {ActionParams} params */
    sequence: ({ message }) => (message.isSelfAuthored ? 20 : 115),
});
registerMessageAction("delete", {
    /** @param {ActionParams} params */
    condition: ({ message }) => message.editable,
    icon: "fa-solid fa-trash-can",
    name: _t("Delete"),
    /** @param {ActionParams} params */
    onSelected: async ({ message: msg, owner, store }) => {
        const message = toRaw(msg);
        const def = new Deferred();
        store.env.services.dialog.add(
            discussComponentRegistry.get("MessageConfirmDialog"),
            {
                message,
                prompt: _t(
                    "Are you sure you want to bid farewell to this message forever?",
                ),
                onConfirm: () => {
                    def.resolve(true);
                    message.remove({
                        removeFromThread: owner.shouldHideFromMessageListOnDelete,
                    });
                },
            },
            { context: owner, onClose: () => def.resolve(false) },
        );
        return def;
    },
    sequence: 120,
    tags: ACTION_TAGS.DANGER,
});
registerMessageAction("download_files", {
    /** @param {ActionParams} params */
    condition: ({ message, store }) =>
        message.attachment_ids.length > 1 &&
        store.self_partner?.main_user_id?.share === false,
    icon: "fa-solid fa-download",
    name: _t("Download Files"),
    /** @param {ActionParams} params */
    onSelected: ({ message }) =>
        download({
            data: {
                file_ids: message.attachment_ids.map((rec) => rec.id),
                zip_name: `attachments_${DateTime.local().toFormat("HHmmddMMyyyy")}.zip`,
            },
            url: "/mail/attachment/zip",
        }),
    sequence: 55,
});
registerMessageAction("toggle-translation", {
    /** @param {ActionParams} params */
    condition: ({ message }) => message.isTranslatable(message.thread),
    /** @param {ActionParams} params */
    icon: ({ message }) =>
        `fa-solid fa-language ${message.showTranslation ? "o-mail-Message-translated" : ""}`,
    /** @param {ActionParams} params */
    name: ({ message }) => (message.showTranslation ? _t("Revert") : _t("Translate")),
    /** @param {ActionParams} params */
    onSelected: ({ message }) => message.onClickToggleTranslation(),
    sequence: 100,
});
registerMessageAction("copy-message", {
    /** @param {ActionParams} params */
    condition: ({ message }) => isMobileOS() && !message.isBodyEmpty,
    /** @param {ActionParams} params */
    onSelected: ({ message }) => message.copyMessageText(),
    name: _t("Copy to Clipboard"),
    icon: "fa-solid fa-copy",
    sequence: 30,
});
registerMessageAction("copy-link", {
    /** @param {ActionParams} params */
    condition: ({ message, thread }) =>
        message.message_type &&
        message.message_type !== "user_notification" &&
        thread &&
        (!thread.access_token || thread.hasReadAccess),
    icon: "fa-solid fa-link",
    name: _t("Copy Link"),
    /** @param {ActionParams} params */
    onSelected: ({ message }) => message.copyLink(),
    sequence: 110,
});

/** @extends {Action<MessageActionOwner, MessageActionDefinition>} */
export class MessageAction extends Action {
    /** @type {() => Message} */
    messageFn;
    /** @type {() => Thread} */
    threadFn;
    /**
     * @param {Object} param0
     * @param {MessageActionOwner} param0.owner
     * @param {string} param0.id
     * @param {MessageActionDefinition} param0.definition
     * @param {import("models").Store} [param0.store]
     * @param {Message|(() => Message)} [param0.message]
     * @param {Thread|(() => Thread)} [param0.thread]
     */
    constructor({ message, thread }) {
        super(...arguments);
        this.messageFn = typeof message === "function" ? message : () => message;
        this.threadFn = typeof thread === "function" ? thread : () => thread;
    }

    get params() {
        return Object.assign(super.params, {
            message: this.messageFn(),
            thread: this.threadFn(),
        });
    }
}

/** @extends {UseActions<MessageAction>} */
class UseMessageActions extends UseActions {
    ActionClass = MessageAction;
}

/**
 * @param {Object} [param0={}]
 * @param {Message|(() => Message)} [param0.message]
 * @param {Thread|(() => Thread)} [param0.thread]
 */
export function useMessageActions({ message, thread } = {}) {
    const component = useComponent();
    const transformedActions = messageActionsRegistry.getEntries().map(
        ([id, definition]) =>
            new MessageAction({
                owner: component,
                id,
                definition,
                message,
                thread,
            }),
    );
    for (const action of transformedActions) {
        action.setup();
    }
    const state = useState(
        new UseMessageActions(component, transformedActions, useService("mail.store")),
    );
    return state;
}
