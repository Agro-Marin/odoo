// @ts-check
/** @odoo-module native */

import { Component, useRef, useState } from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { useModelWithSampleData } from "@web/model/model";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { ActionHelper } from "@web/views/action_helper";
import { standardViewProps } from "@web/views/standard_view_props";
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
    /** @type {ReturnType<typeof useSetupAction>} */
    actionState;

    setup() {
        this.model = useState(
            useModelWithSampleData(
                this.props.Model,
                this.props.modelParams,
                this.modelOptions,
            ),
        );
        this.actionState = useSetupAction({
            rootRef: useRef("root"),
            getLocalState: () => this.getLocalState(),
            getContext: () => this.getContext(),
        });
        this.searchBarToggler = useSearchBarToggler();
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
