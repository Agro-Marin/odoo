/** @odoo-module native */
import { registry } from '@web/core/registry';
import { formatSelection } from "@web/fields/formatters";
import {
    StateSelectionField,
    stateSelectionField,
} from "@web/fields/selection/state_selection/state_selection_field";

import { STATUS_COLORS, STATUS_COLOR_PREFIX } from '../../utils/project_utils.js';

export class ProjectStateSelectionField extends StateSelectionField {
    setup() {
        super.setup();
        this.colorPrefix = STATUS_COLOR_PREFIX;
        this.colors = STATUS_COLORS;
    }

    /**
     * @override
     */
    get options() {
        return super.options.filter(o => o[0] !== 'to_define');
    }

    /**
     * @override
     */
    get label() {
        // `to_define` is hidden from the dropdown options but is a real
        // selection value: format against the full selection so records in
        // that state don't render an empty label.
        return formatSelection(this.currentValue, {
            selection: this.props.record.fields[this.props.name].selection,
        });
    }
}

export const projectStateSelectionField = {
    ...stateSelectionField,
    component: ProjectStateSelectionField,
};

registry.category("fields").add("project_state_selection", projectStateSelectionField);
