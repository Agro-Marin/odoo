/** @odoo-module native */
import { _t } from "@web/core/translation";
import { sortBy } from "@web/core/utils/collections/arrays";
import { GraphModel } from "@web/views/graph";

export class BurndownChartModel extends GraphModel {
    /** @override */
    setup(params) {
        super.setup(params);
        this.stageSeqAndNamePerId = {};
    }

    /**
     * @protected
     * @param {Object} context
     */
    async _fetchStageInfo(context) {
        const searchDomain = context.active_id
            ? [["project_ids", "in", context.active_id]]
            : [];
        const data = await this.orm.webSearchRead(
            "project.workflow.step",
            searchDomain,
            {
                specification: {
                    name: {},
                    sequence: {},
                },
            },
        );
        const stageSeqAndNamePerId = {};
        for (const { id, name, sequence } of data.records) {
            stageSeqAndNamePerId[id] = { name, sequence };
        }
        return stageSeqAndNamePerId;
    }

    /** @param {SearchParams} searchParams */
    async load(searchParams) {
        const { context, groupBy } = searchParams;

        if (groupBy.includes("step_id")) {
            if (context.stage_name_and_sequence_per_id) {
                this.stageSeqAndNamePerId = context.stage_name_and_sequence_per_id;
            } else if (!Object.keys(this.stageSeqAndNamePerId).length) {
                this.stageSeqAndNamePerId = await this._fetchStageInfo(context);
            }
        }
        await super.load(searchParams);
    }

    /** @override */
    prepareData() {
        super.prepareData();
        const { groupBy } = this.searchParams;
        const { mode } = this.metaData;
        if (mode === "line" && groupBy.includes("step_id")) {
            this.data.datasets = sortBy(this.data.datasets, (dataSet) => {
                const firstIdentifier = [...dataSet.identifiers][0];
                const group = Object.assign(...JSON.parse(firstIdentifier));
                const val = group.step_id;
                if (Array.isArray(val)) {
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
    async loadDataPoints(metaData) {
        metaData.measures.__count.string = _t("# of Tasks");
        return super.loadDataPoints(metaData);
    }
}
