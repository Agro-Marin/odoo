/** @odoo-module native */
import { discussComponentRegistry } from "@mail/core/common/discuss_component_registry";
import { Message } from "@mail/core/common/message";
import { messageActionOpenFullComposer } from "@mail/core/web/message_actions_patch";
import {
    formatChar,
    formatFieldFloat,
    formatInteger,
    formatMonetary,
    formatText,
} from "@web/core/formatters";
import {
    deserializeDate,
    deserializeDateTime,
    formatDate,
    formatDateTime,
} from "@web/core/l10n/dates";
import { _t } from "@web/core/translation";
import { markEventHandled } from "@web/core/utils/dom/events";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { usePopover } from "@web/ui/popover";
patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.action = useService("action");
        this.avatarCard = usePopover(discussComponentRegistry.get("AvatarCardPopover"));
    },
    get authorAvatarAttClass() {
        return {
            ...super.authorAvatarAttClass,
            "o_redirect cursor-pointer": this.hasAuthorClickable(),
        };
    },
    getAuthorAttClass() {
        return {
            ...super.getAuthorAttClass(),
            "cursor-pointer o-hover-text-underline": this.hasAuthorClickable(),
        };
    },
    getAuthorText() {
        return this.hasAuthorClickable() ? _t("Open card") : undefined;
    },
    getAvatarContainerAttClass() {
        return {
            ...super.getAvatarContainerAttClass(),
            "cursor-pointer": this.hasAuthorClickable(),
        };
    },
    hasAuthorClickable() {
        return this.message.author_id?.main_user_id;
    },
    /** @param {MouseEvent} ev */
    onClickAuthor(ev) {
        if (this.hasAuthorClickable()) {
            markEventHandled(ev, "Message.ClickAuthor");
            const target = ev.currentTarget;
            if (!this.avatarCard.isOpen) {
                this.avatarCard.open(target, {
                    id: this.message.author_id.main_user_id.id,
                });
            }
        }
    },

    async onClickMessageForward() {
        await this.messageActions.actions.find((a) => a.name === "forward")?.onClick();
    },

    async onClickMessageReplyAll() {
        await this.messageActions.actions
            .find((a) => a.name === "reply-all")
            ?.onClick();
    },

    /**
     * @param {string} name
     * @param {Object} context
     */
    openFullComposer(name, context) {
        messageActionOpenFullComposer(name, context, this);
    },

    openRecord() {
        this.message.thread.open({ focus: true });
        this.message.thread.highlightMessage = this.message;
    },

    /**
     * @param {{fieldType: string, floatPrecision?: number, currencyId?: number}} trackingFieldInfo
     * @param {*} trackingValue
     * @returns {string}
     */
    formatTracking(trackingFieldInfo, trackingValue) {
        switch (trackingFieldInfo.fieldType) {
            case "boolean":
                return trackingValue ? _t("Yes") : _t("No");
            case "char":
            case "many2one":
            case "selection":
                return formatChar(trackingValue);
            case "date": {
                const value = trackingValue
                    ? deserializeDate(trackingValue)
                    : trackingValue;
                return formatDate(value);
            }
            case "datetime": {
                const value = trackingValue
                    ? deserializeDateTime(trackingValue)
                    : trackingValue;
                return formatDateTime(value);
            }
            case "float":
                return formatFieldFloat(trackingValue, {
                    digits: trackingFieldInfo.floatPrecision,
                });
            case "integer":
                return formatInteger(trackingValue);
            case "text":
                return formatText(trackingValue);
            case "monetary":
                return formatMonetary(trackingValue, {
                    currencyId: trackingFieldInfo.currencyId,
                });
            default:
                return trackingValue;
        }
    },

    /**
     * @param {{fieldType: string, floatPrecision?: number, currencyId?: number}} trackingFieldInfo
     * @param {*} trackingValue
     * @returns {string}
     */
    formatTrackingOrNone(trackingFieldInfo, trackingValue) {
        const formattedValue = this.formatTracking(trackingFieldInfo, trackingValue);
        return formattedValue
            ? (this.props.messageSearch?.highlight(formattedValue) ?? formattedValue)
            : _t("None");
    },
});
