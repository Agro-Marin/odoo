// @ts-check
/** @odoo-module native */

import { Component, toRaw, useRef, useState } from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { useModelWithSampleData } from "@web/model/model";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { ActionHelper } from "@web/views/action_helper";
import { standardViewProps } from "@web/views/standard_view_props";
import { useViewChassis } from "@web/views/view_layout";
import { computeModelOptions } from "@web/views/view_utils";

export class ReportController extends Component {
    static components = { Layout, SearchBar, CogMenu, ActionHelper };
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
                // The model keeps these; handing it a reactive proxy of the
                // props makes every read of metaData a subscription.
                toRaw(this.props.modelParams),
                this.modelOptions,
            ),
        );
        this.actionState = useSetupAction({
            rootRef: useRef("root"),
            getLocalState: () => this.getLocalState(),
            getContext: () => this.getContext(),
        });
        this.chassis = useViewChassis();
        // One toggler under two names: `chassis.props` carries it to
        // `ViewLayout`, and the templates that predate ViewLayout read this.
        this.searchBarToggler = this.chassis.searchBarToggler;
    }

    /**
     * @returns {Object}
     */
    get modelOptions() {
        return /** @type {any} */ (computeModelOptions(this.env, this.props.display));
    }

    /**
     * @returns {Object}
     */
    getLocalState() {
        return { metaData: this.model.metaData };
    }

    /**
     * @returns {Object}
     */
    getContext() {
        return {};
    }
}
