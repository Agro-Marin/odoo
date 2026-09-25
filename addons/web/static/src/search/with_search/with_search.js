// @ts-check
/** @odoo-module native */

import { Component, onWillStart, onWillUpdateProps, toRaw, useState } from "@odoo/owl";
import { getDefaultDomain } from "@web/components/domain_selector/utils";
import { DomainSelectorDialog } from "@web/components/domain_selector_dialog/domain_selector_dialog";
import {
    CallbackRecorder,
    provideActionCallbackRecorders,
    useActionCallbackRecorders,
    useSetupAction,
} from "@web/core/action_hook";
import { SEARCH_KEYS } from "@web/core/constants";
import { SearchModelEvent } from "@web/core/events";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { useBus, useService } from "@web/core/utils/hooks";
import { useViewConfig } from "@web/core/view_config_hooks";
import { provideWebContext } from "@web/core/web_context_hooks";
import { provideSearchModel, SearchModel } from "@web/search/search_model";
import { provideActiveView } from "@web/views/active_view";

export const withSearchProps = {
    slots: Object,
    SearchModel: { type: Function, optional: true },

    resModel: String,

    globalState: { type: Object, optional: true },
    searchModelArgs: { type: Object, optional: true },

    display: { type: Object, optional: true },

    context: { type: Object, optional: true },
    domain: { type: Array, element: [String, Array], optional: true },
    groupBy: { type: Array, element: String, optional: true },
    orderBy: { type: Array, element: Object, optional: true },

    searchViewArch: { type: String, optional: true },
    searchViewIR: { type: Object, optional: true },
    searchViewFields: { type: Object, optional: true },
    searchViewId: { type: [Number, Boolean], optional: true },

    irFilters: { type: Array, element: Object, optional: true },
    loadIrFilters: { type: Boolean, optional: true },

    activateFavorite: { type: Boolean, optional: true },
    dynamicFilters: { type: Array, element: Object, optional: true },
    hideCustomGroupBy: { type: Boolean, optional: true },
    searchMenuTypes: { type: Array, element: String, optional: true },
    canOrderByCount: { type: Boolean, optional: true },
    defaultGroupBy: { type: Array, element: String, optional: true },
};

export class WithSearch extends Component {
    static template = "web.WithSearch";
    static props = withSearchProps;

    setup() {
        const parentCallbacks = useActionCallbackRecorders();
        if (!parentCallbacks.__getContext__) {
            provideActionCallbackRecorders({ __getContext__: new CallbackRecorder() });
        }
        if (!parentCallbacks.__getOrderBy__) {
            provideActionCallbackRecorders({ __getOrderBy__: new CallbackRecorder() });
        }

        const SearchModelClass = this.props.SearchModel || SearchModel;
        this.searchModel = new SearchModelClass(
            SearchModelClass.useSearchScope(),
            {
                orm: useService("orm"),
                view: useService("view"),
                field: useService("field"),
                dialog: useService("dialog"),
                treeProcessor: useService("tree_processor"),
                DomainSelectorDialog,
                getDefaultDomain,
            },
            this.props.searchModelArgs,
        );

        const searchPanelState = this.props.globalState?.searchPanel
            ? JSON.parse(this.props.globalState?.searchPanel)
            : null;
        provideSearchModel(this.searchModel);
        provideActiveView(useViewConfig() ?? {}, this.searchModel);
        provideWebContext({ searchPanelState });

        this.state = useState({ searchModelUpdates: 0 });
        useBus(
            this.searchModel,
            SearchModelEvent.UPDATE,
            () => this.state.searchModelUpdates++,
        );
        useSetupAction({
            getGlobalState: () => ({
                searchModel: JSON.stringify(this.searchModel.exportState()),
            }),
        });

        onWillStart(async () => {
            const config = { ...toRaw(this.props) };
            if (config.globalState && config.globalState.searchModel) {
                config.state = JSON.parse(config.globalState.searchModel);
                delete config.globalState;
            }
            await this.searchModel.load(config);
        });

        const reloadKeepLast = new KeepLast({ rejectSuperseded: true });

        onWillUpdateProps(async (nextProps) => {
            /** @type {Record<string, any>} */
            const config = {};
            for (const key of SEARCH_KEYS) {
                if (nextProps[key] !== undefined) {
                    config[key] = nextProps[key];
                }
            }
            try {
                await reloadKeepLast.add(this.searchModel.reload(config));
            } catch (error) {
                if (!(error instanceof SupersededError)) {
                    throw error;
                }
            }
        });
    }

    get observedSearchModel() {
        void this.state.searchModelUpdates;
        return this.searchModel;
    }
}
