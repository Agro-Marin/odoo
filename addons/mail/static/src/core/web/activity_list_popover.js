/** @odoo-module native */
import { ActivityListPopoverItem } from "@mail/core/web/activity_list_popover_item";
import { compareDatetime } from "@mail/utils/common/misc";
import { Component, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {Object} Props
 * @property {number[]} activityIds
 * @property {function} close
 * @property {number} [defaultActivityTypeId]
 * @property {function} onActivityChanged
 * @property {number} resId
 * @property {string} resModel
 * @extends {Component<Props, Env>}
 */
export class ActivityListPopover extends Component {
    static components = { ActivityListPopoverItem };
    static props = [
        "activityIds",
        "close",
        "defaultActivityTypeId?",
        "onActivityChanged",
        "resId",
        /** Ids of record selection used to schedule activities in batch; it must include resId. */
        "resIds?",
        "resModel",
    ];
    static template = "mail.ActivityListPopover";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.store = useService("mail.store");
        // catch: updateFromProps calls activity_format (orm.silent suppresses
        // the error dialog but the promise still rejects) — an unhandled
        // rejection if the record vanished
        this.updateFromProps(this.props).catch(() => {});
        onWillUpdateProps((props) => this.updateFromProps(props).catch(() => {}));
    }

    get activities() {
        // Set membership instead of Array.includes: the getter is invoked once
        // per render plus once per state bucket (done/overdue/planned/today), so
        // the filter ran activityIds.includes for every stored activity on every
        // one of those passes -- O(activities x activityIds).
        const activityIds = new Set(this.props.activityIds);
        /** @type {import("models").Activity[]} */
        const allActivities = Object.values(this.store["mail.activity"].records);
        return allActivities
            .filter((activity) => activityIds.has(activity.id))
            .sort(
                (a, b) =>
                    compareDatetime(a.date_deadline, b.date_deadline) || a.id - b.id,
            );
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

    get doneActivities() {
        return this.activities.filter((activity) => activity.state === "done");
    }

    get overdueActivities() {
        return this.activities.filter((activity) => activity.state === "overdue");
    }

    get plannedActivities() {
        return this.activities.filter((activity) => activity.state === "planned");
    }

    get todayActivities() {
        return this.activities.filter((activity) => activity.state === "today");
    }

    async updateFromProps(props) {
        const data = await this.orm.silent.call("mail.activity", "activity_format", [
            props.activityIds,
        ]);
        this.store.insert(data);
    }
}
