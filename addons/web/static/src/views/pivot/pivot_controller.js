// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_controller */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { useModelWithSampleData } from "@web/model/model";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { ActionHelper } from "@web/views/action_helper";
import { standardViewProps } from "@web/views/standard_view_props";
import { computeModelOptions } from "@web/views/view_utils";

export class PivotController extends Component {
    static template = "web.PivotView";
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

    setup() {
        this.model = useState(
            useModelWithSampleData(
                this.props.Model,
                this.props.modelParams,
                this.modelOptions,
            ),
        );

        const { setScrollFromState } = useSetupAction({
            rootRef: useRef("root"),
            getLocalState: () => {
                const { data, metaData } = this.model;
                return { data, metaData };
            },
            getContext: () => this.getContext(),
        });
        useEffect(
            (isReady) => {
                if (isReady) {
                    setScrollFromState();
                }
            },
            () => [this.model.isReady],
        );
        this.searchBarToggler = useSearchBarToggler();
    }

    /**
     * @returns {boolean}
     */
    get displayNoContent() {
        if (this.props.info.noContentHelp === false) {
            return false;
        }
        const { metaData, useSampleModel } = this.model;
        return (
            useSampleModel || !this.model.hasData() || !metaData.activeMeasures.length
        );
    }

    /** @returns {Object} */
    get modelOptions() {
        return /** @type {any} */ (computeModelOptions(this.env, this.props.display));
    }

    /**
     * @returns {Object}
     */
    getContext() {
        return {
            pivot_measures: this.model.metaData.activeMeasures,
            pivot_column_groupby: this.model.metaData.fullColGroupBys,
            pivot_row_groupby: this.model.metaData.fullRowGroupBys,
        };
    }
}
