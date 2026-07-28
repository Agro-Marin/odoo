// @ts-check
/** @odoo-module native */

/** @module @web/ui/notification/notification_container - Renders all active notifications with fade-out transitions */

import { Component, useState, xml } from "@odoo/owl";
import { Transition } from "@web/components/transition";
import { ErrorHandler } from "@web/core/utils/components";

import { Notification } from "./notification.js";
export class NotificationContainer extends Component {
    static props = {
        notifications: Object,
    };

    static template = xml`
        <div class="o_notification_manager">
            <t t-foreach="notifications" t-as="notification" t-key="notification">
                <ErrorHandler onError="(error) => this.handleError(notification, error)">
                    <Transition leaveDuration="0" immediate="true" name="'o_notification_fade'" t-slot-scope="transition">
                        <Notification t-props="notification_value.props" className="(notification_value.props.className || '') + ' ' + transition.className"/>
                    </Transition>
                </ErrorHandler>
            </t>
        </div>`;
    static components = { ErrorHandler, Notification, Transition };

    /** Make the notifications map reactive so the container re-renders on changes. */
    setup() {
        /** @type {Object<string, { props: Object }>} */
        this.notifications = useState(this.props.notifications);
    }

    /**
     * Drop the faulty notification instead of letting the error escape to
     * MainComponentsContainer, which would unregister the whole container and
     * silently kill every later notification for the session.
     *
     * @param {string} key
     * @param {Error} error
     */
    handleError(key, error) {
        this.notifications[key]?.props.close();
        Promise.resolve().then(() => {
            throw error;
        });
    }
}
