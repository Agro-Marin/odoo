/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { GraphModel } from "@web/views/graph/graph_model";
import { sortBy } from "@web/core/utils/collections/arrays";

export class BurndownChartModel extends GraphModel {
    /**
     * @override
     */
    setup(params) {
        super.setup(params);
        this.stageSeqAndNamePerId = {};
    }

    /**
     * Fetch the sequence of each stage in the project. This function alters this.stageSeqAndNamePerId
     * @protected
     * @param {Object} context
     */
    async _fetchStageInfo(context) {
        const searchDomain = context.active_id
            ? [["project_ids", "in", context.active_id]]
            : [];
        const data = await this.orm.webSearchRead("project.workflow.step", searchDomain, {
            specification: {
                name: {},
                sequence: {},
            },
        });
        const stageSeqAndNamePerId = {};
        for (const { id, name, sequence } of data.records) {
            stageSeqAndNamePerId[id] = { name, sequence };
        }
        return stageSeqAndNamePerId;
    }

    /**
     * @param {SearchParams} searchParams
     */
    async load(searchParams) {
        const { context, groupBy } = searchParams;

        if (groupBy.includes("step_id")) {
            if (context.stage_name_and_sequence_per_id) {
                // Provided by the server actions that open the chart. (Do not
                // additionally require default_project_id: no producer sets
                // it, the gate would make this payload dead weight.)
                this.stageSeqAndNamePerId = context.stage_name_and_sequence_per_id;
            } else if (!Object.keys(this.stageSeqAndNamePerId).length) {
                // Page reload / direct navigation: fetch once and keep it —
                // step names and sequences don't change with search
                // interactions, and refetching on every filter or group-by
                // change costs one RPC each.
                this.stageSeqAndNamePerId = await this._fetchStageInfo(context);
            }
        }
        await super.load(searchParams);
    }

    /**
     * @override
     */
    _prepareData() {
        super._prepareData();
        const { groupBy } = this.searchParams;
        const { mode } = this.metaData;
        if (mode === "line" && groupBy.includes("step_id")) {
            this.data.datasets = sortBy(this.data.datasets, (dataSet) => {
                const firstIdentifier = [...dataSet.identifiers][0];
                const group = Object.assign(...JSON.parse(firstIdentifier));
                const val = group.step_id;
                if (Array.isArray(val)) {
                    // `??`: a real sequence of 0 must not fall back to -1.
                    return this.stageSeqAndNamePerId[val[0]]?.sequence ?? -1;
                }
                return -1;
            });
        }
    }

    /**
     * @protected
     * @override
     */
    async _loadDataPoints(metaData) {
        metaData.measures.__count.string = _t("# of Tasks");
        return super._loadDataPoints(metaData);
    }
}
