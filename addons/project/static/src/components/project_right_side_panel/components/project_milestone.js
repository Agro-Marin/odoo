/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { formatDate } from "@web/core/l10n/dates";
import { useService } from '@web/core/utils/hooks';
import { Component, useState, onWillUpdateProps } from "@odoo/owl";

const { DateTime } = luxon;

export class ProjectMilestone extends Component {
    static props = {
        context: Object,
        milestone: Object,
    };
    static template = "project.ProjectMilestone";

    setup() {
        this.orm = useService('orm');
        this.dialog = useService("dialog");
        // Own reactive copy: updates below use Object.assign to mutate this
        // proxy in place. Reassigning this.milestone to a plain object (as the
        // code used to) would discard the reactive proxy; copying instead of
        // wrapping props avoids mutating the parent's prop object.
        this.milestone = useState({ ...this.props.milestone });
        onWillUpdateProps(this.onWillUpdateProps);
    }

    get resModel() {
        return 'project.milestone';
    }

    get deadline() {
        if (!this.milestone.deadline) {
            return "";
        }
        return formatDate(DateTime.fromISO(this.milestone.deadline));
    }

    // Derived from the reactive milestone copy: plain getters re-evaluate on
    // render, so no manual resynchronization is needed.
    get colorClass() {
        return this.milestone.is_deadline_exceeded && !this.milestone.can_be_marked_as_done
            ? "text-danger"
            : this.milestone.can_be_marked_as_done
              ? "text-success"
              : "";
    }

    get checkboxIcon() {
        return this.milestone.is_reached ? "fa-solid fa-square-check" : "fa-regular fa-square";
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
                Object.assign(this.milestone, await this.orm.call(
                    this.resModel,
                    'toggle_is_reached',
                    [[this.milestone.id], !this.milestone.is_reached],
                ));
            } finally {
                // Always release the lock, even if the RPC rejects, otherwise a
                // single transient failure permanently disables the checkbox.
                this.write_mutex = false;
            }
        }
    }
}
