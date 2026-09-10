/** @odoo-module native */
import { Component, useState } from "@odoo/owl";

import { useSetupAction } from "@web/core/action_hook";
import { useModelWithSampleData } from "@web/model/model";
import {
    addFieldDependencies,
    extractFieldsFromArchInfo,
} from "@web/model/relational_model";
import { standardViewProps } from "@web/views/standard_view_props";
import { useViewButtons } from "@web/views/view_button";
import { useViewChassis, ViewLayout } from "@web/views/view_components";

export class HierarchyController extends Component {
    static components = { ViewLayout };
    static props = {
        ...standardViewProps,
        Model: Function,
        Renderer: Function,
        buttonTemplate: String,
        archInfo: Object,
    };
    static template = "web_hierarchy.HierarchyView";

    setup() {
        this.chassis = useViewChassis();
        this.rootRef = this.chassis.rootRef;
        const { parentFieldName, childFieldName } = this.props.archInfo;
        const { activeFields, fields } = extractFieldsFromArchInfo(
            this.props.archInfo,
            this.props.fields,
        );
        const additionalFields = [{ name: parentFieldName }];
        if (childFieldName) {
            additionalFields.push({ name: childFieldName });
        }
        addFieldDependencies(activeFields, fields, additionalFields);
        const modelConfig = this.props.state?.modelState?.config || {};
        this.model = useState(
            useModelWithSampleData(this.props.Model, {
                config: modelConfig,
                resModel: this.props.resModel,
                activeFields,
                defaultOrderBy: this.props.archInfo.defaultOrder,
                fields,
                parentFieldName,
                childFieldName,
            }),
        );
        useViewButtons(this.rootRef, {
            reload: this.model.reload.bind(this.model),
        });
        useSetupAction({
            rootRef: this.rootRef,
            getLocalState: () => {
                return {
                    modelState: this.model.exportState(),
                };
            },
        });
    }

    get chassisProps() {
        const small = this.env.isSmall ? " o_action_delegate_scroll" : "";
        return {
            ...this.chassis.props,
            className: `o_hierarchy_view${small} ${this.props.className || ""}`,
            contentClassName: "d-flex",
        };
    }

    async openRecord(node, newWindow) {
        this.props.selectRecord(node.resId, {
            activeIds: this.model.resIds,
            newWindow,
        });
    }
}
