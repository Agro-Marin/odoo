// @ts-check
/** @odoo-module native */

/** @module @web/views/view_components/multi_create_popover */

import { Component } from "@odoo/owl";
import { TimePicker } from "@web/components/time_picker/time_picker";
import { useCallbackRecorder } from "@web/core/action_hook";
import { DateTime } from "@web/core/l10n/luxon";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { Record } from "@web/model/record";
import { FormRenderer } from "@web/views/form/form_renderer";

export class MultiCreatePopover extends Component {
    static template = "web.MultiCreatePopover";
    static components = {
        FormRenderer,
        Record,
        TimePicker,
    };
    static props = {
        close: Function,
        multiCreateArchInfo: Object,
        multiCreateRecordProps: Object,
        onAdd: Function,
        callbackRecorder: Object,
        timeRange: { type: [Object, { value: null }] },
    };

    /** @type {{ timeRange: any }} */
    multiCreateData;
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;

    setup() {
        this.notification = useService("notification");

        this.multiCreateData = {
            timeRange: this.props.timeRange && { ...this.props.timeRange },
        };
        this.multiCreateArchInfo = this.props.multiCreateArchInfo;
        this.multiCreateRecordProps = {
            ...this.props.multiCreateRecordProps,
            hooks: {
                lifecycle: {
                    onRootLoaded: (record) => {
                        this.multiCreateData.record = record;
                    },
                },
                ui: {
                    onDisplayInvalidFields: () =>
                        this.notification.add(_t("Missing required fields"), {
                            type: "danger",
                        }),
                },
            },
        };

        useCallbackRecorder(this.props.callbackRecorder, () => this.multiCreateData);
    }

    /** @param {{ start: any, end: any }} timeRange */
    setMultiCreateTimeRange(timeRange) {
        Object.assign(this.multiCreateData.timeRange, timeRange);
    }

    /**
     * @returns {Promise<boolean>}
     */
    async isValidMultiCreateData() {
        const isValid = await this.multiCreateData.record.checkValidity({
            displayNotification: true,
        });
        if (!isValid) {
            return false;
        }
        if (this.multiCreateData.timeRange) {
            const { start, end } = this.multiCreateData.timeRange;
            if (!start || !end) {
                this.notification.add(_t("Invalid time range"), {
                    title: "User Error",
                    type: "warning",
                });
                return false;
            }
            if (
                DateTime.fromObject(start.toObject()) >
                DateTime.fromObject(end.toObject())
            ) {
                this.notification.add(_t("Start time should be before end time"), {
                    title: "User Error",
                    type: "warning",
                });
                return false;
            }
        }
        return true;
    }

    async onAdd() {
        const isValid = await this.isValidMultiCreateData();
        if (isValid) {
            this.props.onAdd(this.multiCreateData);
            this.props.close();
        }
    }
}
