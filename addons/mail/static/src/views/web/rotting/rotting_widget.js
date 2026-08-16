/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    buildM2OFieldDescription,
    Many2OneField,
} from "@web/fields/relational/many2one";
import { standardFieldProps } from "@web/fields/standard_field_props";
/**
 * @param {string} modelName
 * @param {number} rotDays
 * @returns {string}
 */
export function getRottingDaysTitle(modelName, rotDays) {
    switch (modelName) {
        case "crm.lead":
            return _t(
                "This lead has been stuck in this stage for %(numberOfDays)s days.",
                {
                    numberOfDays: rotDays,
                },
            );
        case "hr.applicant":
            return _t(
                "This applicant has been stuck in this stage for %(numberOfDays)s days.",
                {
                    numberOfDays: rotDays,
                },
            );
        case "project.task":
            return _t(
                "This task has been stuck in this stage for %(numberOfDays)s days.",
                {
                    numberOfDays: rotDays,
                },
            );
    }
    return _t("This record has been stuck in this stage for %(numberOfDays)s days.", {
        numberOfDays: rotDays,
    });
}

export class KanbanRottingField extends Component {
    static props = {
        ...standardFieldProps,
    };
    static template = "mail.KanbanRottingField";

    get dayCount() {
        return _t("%(numberOfDays)sd", {
            numberOfDays: this.props.record.data.rotting_days,
        });
    }

    get title() {
        return getRottingDaysTitle(
            this.props.record.model.config.resModel,
            this.props.record.data.rotting_days,
        );
    }
}

export class Many2OneFieldRotting extends Many2OneField {
    static template = "mail.Many2OneFieldRotting";

    get dayCount() {
        return _t("%(numberOfDays)sd", {
            numberOfDays: this.props.record.data.rotting_days,
        });
    }
}

registry.category("fields").add("kanban.rotting", {
    component: KanbanRottingField,
});

registry.category("fields").add("list.badge_rotting", {
    ...buildM2OFieldDescription(Many2OneFieldRotting),
});
