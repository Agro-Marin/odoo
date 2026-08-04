/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { ModelSelector } from "@web/components/model_selector/model_selector";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { memoize } from "@web/core/utils/functions";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
/** Selects a model among the accessible ones (getAvailableResModels), then one of
 * its records through a SelectCreateDialog list, like documents'
 * DocumentsDetailsPanel.
 **/

// Small hack, memoize uses the first argument as cache key, but we need the orm which will not be the same.
const getAvailableResModels = memoize((_null, orm) =>
    orm.call("mail.activity.schedule", "get_model_options"),
);

class ActivityModelSelector extends Component {
    static components = { ModelSelector };
    static template = "mail.ActivityModelSelector";
    static props = standardFieldProps;

    setup() {
        // Use a state for the model to not write on the record the model without record id
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({
            resModel: this.props.record.data.res_model,
            resModelName: this.props.record.data.res_model_name || "",
            models: [],
        });
        getAvailableResModels(null, this.orm).then(
            (models) => (this.state.models = models),
        );
    }

    async onModelSelected(value) {
        this.state.resModel = value.technical;
        this.state.resModelName = value.label || "";
        if (this.state.resModel) {
            this.dialog.add(
                SelectCreateDialog,
                {
                    title: _t("Select a Record To Link"),
                    noCreate: true,
                    multiSelect: false,
                    resModel: this.state.resModel,
                    onSelected: async (resId) => {
                        /* Changing the model changes the available activity
                         * types, which recomputes the fields depending on them
                         * (including the possibly already edited summary and
                         * note): save both to restore them after.
                         */
                        const persistDataThroughModelChange = {
                            summary: this.props.record.data.summary,
                            note: this.props.record.data.note,
                        };

                        await this.props.record.update(
                            {
                                res_model: this.state.resModel,
                                res_ids: resId,
                            },
                            { save: false },
                        );
                        const recordInfo = await this.orm.call(
                            this.state.resModel,
                            "name_search",
                            [],
                            {
                                domain: [["id", "in", resId]],
                            },
                        );
                        this.state.resModelName = recordInfo[0][1];

                        // recover saved inputs
                        this.props.record.update(persistDataThroughModelChange);
                    },
                },
                {
                    onClose: () => {
                        if (!this.props.record.data.res_ids) {
                            this.onRecordReset();
                        }
                    },
                },
            );
        }
    }

    onRecordReset() {
        // information to persist current summary and notes through res_model changes
        const persistDataThroughModelChange = {
            summary: this.props.record.data.summary,
            note: this.props.record.data.note,
        };
        this.props.record.update({
            res_model: false,
            res_ids: false,
        });
        this.props.record.update(persistDataThroughModelChange);
        return this.onModelSelected({ technical: false, label: false });
    }
}

registry.category("fields").add("activity_model_selector", {
    component: ActivityModelSelector,
});
