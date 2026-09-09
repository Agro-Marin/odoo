/** @odoo-module native */
import { Component, onWillUpdateProps, useState } from "@odoo/owl";
import { formatDate } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { useService } from "@web/core/utils/hooks";

const { DateTime } = luxon;

export class ProjectMilestone extends Component {
    static props = {
        context: Object,
        milestone: Object,
    };
    static template = "project.ProjectMilestone";

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.milestone = useState({ ...this.props.milestone });
        onWillUpdateProps(this.onWillUpdateProps);
    }

    get resModel() {
        return "project.milestone";
    }

    get deadline() {
        if (!this.milestone.date_deadline) {
            return "";
        }
        return formatDate(DateTime.fromISO(this.milestone.date_deadline));
    }

    get colorClass() {
        return this.milestone.is_deadline_exceeded &&
            !this.milestone.can_be_marked_as_done
            ? "text-danger"
            : this.milestone.can_be_marked_as_done
              ? "text-success"
              : "";
    }

    get checkboxIcon() {
        return this.milestone.is_reached
            ? "fa-solid fa-square-check"
            : "fa-regular fa-square";
    }

    onWillUpdateProps(nextProps) {
        if (nextProps.milestone) {
            Object.assign(this.milestone, nextProps.milestone);
        }
    }

    async toggleIsReached() {
        if (!this.write_mutex) {
            this.write_mutex = true;
            try {
                Object.assign(
                    this.milestone,
                    await this.orm.call(this.resModel, "update_is_reached", [
                        [this.milestone.id],
                        !this.milestone.is_reached,
                    ]),
                );
            } finally {
                this.write_mutex = false;
            }
        }
    }
}
