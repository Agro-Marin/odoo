// @ts-check
/** @odoo-module native */

import { Component, toRaw, useState } from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { useModelWithSampleData } from "@web/model/model";
import { standardViewProps } from "@web/views/standard_view_props";
import { useViewChassis, ViewLayout } from "@web/views/view_components";
import { computeModelOptions } from "@web/views/view_utils";

export class ReportController extends Component {
    static components = { ViewLayout };
    static props = {
        ...standardViewProps,
        Model: Function,
        modelParams: Object,
        Renderer: Function,
        buttonTemplate: String,
    };

    /** @type {any} */
    model;
    /** @type {any} */
    searchBarToggler;
    /** @type {ReturnType<typeof useViewChassis>} */
    chassis;
    /** @type {ReturnType<typeof useSetupAction>} */
    actionState;

    setup() {
        this.model = useState(
            useModelWithSampleData(
                this.props.Model,
                toRaw(this.props.modelParams),
                this.modelOptions,
            ),
        );
        this.chassis = useViewChassis(this.chassisHooks);
        this.searchBarToggler = this.chassis.searchBarToggler;
        this.actionState = useSetupAction({
            rootRef: this.chassis.rootRef,
            getLocalState: () => this.getLocalState(),
            getContext: () => this.getContext(),
        });
    }

    /** @returns {Record<string, () => any>} */
    get chassisHooks() {
        return {};
    }

    /** @returns {Object} */
    get modelOptions() {
        return /** @type {any} */ (computeModelOptions(this.env, this.props.display));
    }

    /** @returns {Object} */
    getLocalState() {
        return { metaData: this.model.metaData };
    }

    /** @returns {Object} */
    getContext() {
        return {};
    }
}
