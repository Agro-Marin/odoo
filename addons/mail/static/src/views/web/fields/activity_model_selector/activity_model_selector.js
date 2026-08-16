/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { ModelSelector } from "@web/components/model_selector/model_selector";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { memoize } from "@web/core/utils/functions";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { SelectCreateDialog } from "@web/views/view_dialogs";

const getAvailableResModels = memoize(
    /**
     * @param {null} _null
     * @param {import("@web/core/network/orm_service").ORM} orm
     */
    (_null, orm) => orm.call("mail.activity.schedule", "get_model_options"),
);

class ActivityModelSelector extends Component {
    static components = { ModelSelector };
    static template = "mail.ActivityModelSelector";
    static props = standardFieldProps;

    setup() {
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

    /** @param {{technical: string, label?: string}} value */
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
                    /** @param {number[]} resId */
                    onSelected: async (resId) => {
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
