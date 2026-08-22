// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { RPCError } from "@web/core/network/rpc";
import { _t } from "@web/core/translation";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog/dialog";

export class CalendarQuickCreate extends Component {
    static template = "web.CalendarQuickCreate";
    static components = {
        Dialog,
    };
    static props = {
        title: { type: String, optional: true },
        close: Function,
        record: Object,
        model: Object,
        editRecord: Function,
    };

    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {ReturnType<typeof useAutofocus>} */
    titleRef;

    setup() {
        this.titleRef = useAutofocus({ refName: "title" });
        this.notification = useService("notification");
        this.creatingRecord = false;
    }

    get dialogTitle() {
        return _t("New Event");
    }

    get recordTitle() {
        return /** @type {HTMLInputElement} */ (this.titleRef.el).value.trim();
    }
    get record() {
        return {
            ...this.props.record,
            title: this.recordTitle,
        };
    }

    editRecord() {
        this.props.editRecord(this.record);
        this.props.close();
    }
    async createRecord() {
        if (this.creatingRecord) {
            return;
        }

        if (this.recordTitle) {
            try {
                this.creatingRecord = true;
                await this.props.model.createRecord(this.record);
                this.props.close();
            } catch (error) {
                if (!(error instanceof RPCError)) {
                    throw error;
                }
                this.editRecord();
            } finally {
                this.creatingRecord = false;
            }
        } else {
            this.titleRef.el?.classList.add("o_field_invalid");
            this.notification.add(_t("Meeting Subject"), {
                title: _t("Invalid fields"),
                type: "danger",
            });
        }
    }

    onInputKeyup(/** @type {KeyboardEvent} */ ev) {
        switch (ev.key) {
            case "Enter":
                this.createRecord();
                break;
            case "Escape":
                this.props.close();
                break;
        }
    }
    onCreateBtnClick() {
        this.createRecord();
    }
    onEditBtnClick() {
        this.editRecord();
    }
    onCancelBtnClick() {
        this.props.close();
    }
}
