// @ts-check
/** @odoo-module native */
import { isToday } from "@mail/utils/common/dates";
import { useHover } from "@mail/utils/common/hooks";
import { provideMailContext, useMailContext } from "@mail/utils/common/mail_context";
import { Component, useRef } from "@odoo/owl";
import { ActionSwiper } from "@web/components/action_swiper";
import { luxon } from "@web/core/l10n/luxon";
import { useService } from "@web/core/utils/hooks";
const { DateTime } = luxon;

export const notificationItemProps = [
    "counter?",
    "datetime?",
    "first?",
    "hasMarkAsReadButton?",
    "iconSrc?",
    "important?",
    "muted?",
    "onClick",
    "onSwipeLeft?",
    "onSwipeRight?",
    "slots?",
    "isActive?",
    "nameMaxLine?",
    "textMaxLine?",
    "thread?",
];

export class NotificationItem extends Component {
    static components = { ActionSwiper };
    static props = notificationItemProps;
    static defaultProps = {
        counter: 0,
        muted: 0,
    };
    static template = "mail.NotificationItem";

    setup() {
        super.setup();
        this.isToday = isToday;
        this.DateTime = DateTime;
        this.ui = useService("ui");
        this.store = useService("mail.store");
        this.markAsReadRef = useRef("markAsRead");
        this.rootHover = useHover("root");
        provideMailContext({ inNotificationItem: true });
        this.mailContext = useMailContext();
    }

    get dateText() {
        if (isToday(this.props.datetime)) {
            return this.props.datetime?.toLocaleString(DateTime.TIME_SIMPLE);
        }
        if (this.props.datetime?.year === DateTime.now().year) {
            return this.props.datetime?.toLocaleString({
                month: "short",
                day: "numeric",
            });
        }
        return this.props.datetime?.toLocaleString(DateTime.DATE_MED);
    }

    /** @param {MouseEvent} ev */
    onClick(ev) {
        this.props.onClick(
            this.markAsReadRef.el?.contains(/** @type {Node} */ (ev.target)),
        );
    }
}
