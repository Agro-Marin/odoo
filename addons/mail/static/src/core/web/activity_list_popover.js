/** @odoo-module native */
import { ActivityListPopoverItem } from "@mail/core/web/activity_list_popover_item";
import { compareDatetime } from "@mail/utils/common/misc";
import { Component, onWillRender, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {Object} Props
 * @property {number[]} activityIds
 * @property {function} close
 * @property {number} [defaultActivityTypeId]
 * @property {function} onActivityChanged
 * @property {number} resId
 * @property {string} resModel
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class ActivityListPopover extends Component {
    static components = { ActivityListPopoverItem };
    static props = [
        "activityIds",
        "close",
        "defaultActivityTypeId?",
        "onActivityChanged",
        "resId",
        "resIds?",
        "resModel",
    ];
    static template = "mail.ActivityListPopover";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.store = useService("mail.store");
        this.updateFromProps(this.props).catch(() => {});
        onWillUpdateProps(
            /** @param {{activityIds: number[]}} props */ (props) =>
                this.updateFromProps(props).catch(() => {}),
        );
        onWillRender(() => this.computeActivityBuckets());
    }

    computeActivityBuckets() {
        /** @type {import("models").Activity[]} */
        this.activities = this.props.activityIds
            .map((id) => this.store["mail.activity"].get(id))
            .filter(Boolean)
            .sort(
                (a, b) =>
                    compareDatetime(a.date_deadline, b.date_deadline) || a.id - b.id,
            );
        this.doneActivities = [];
        this.overdueActivities = [];
        this.plannedActivities = [];
        this.todayActivities = [];
        const buckets = {
            done: this.doneActivities,
            overdue: this.overdueActivities,
            planned: this.plannedActivities,
            today: this.todayActivities,
        };
        for (const activity of this.activities) {
            buckets[activity.state]?.push(activity);
        }
    }

    onClickAddActivityButton() {
        this.store
            .scheduleActivity(
                this.props.resModel,
                this.props.resIds ? this.props.resIds : [this.props.resId],
                this.props.defaultActivityTypeId,
            )
            .then(() => this.props.onActivityChanged());
        this.props.close();
    }

    /** @param {{activityIds: number[]}} props */
    async updateFromProps(props) {
        const data = await this.orm.silent.call("mail.activity", "activity_format", [
            props.activityIds,
        ]);
        this.store.insert(data);
    }
}
