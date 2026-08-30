/** @odoo-module native */
import { CrmKanbanModel } from "@crm/views/crm_kanban/crm_kanban_model";

export class ForecastKanbanModel extends CrmKanbanModel {
    setup(params, { fillTemporalService }) {
        super.setup(...arguments);
        this.fillTemporalService = fillTemporalService;
        this.forceNextRecompute = !params.state?.groups;
        this.originalDomain = null;
        this.fillTemporalDomain = null;
    }

    async webReadGroup(config) {
        if (this.isForecastGroupBy(config)) {
            config.context = this.fillTemporalPeriod(config).getContext({
                context: config.context,
            });
            if (!this.originalDomain || this.fillTemporalDomain !== config.domain) {
                this.originalDomain = config.domain || [];
            }
            this.fillTemporalDomain = this.fillTemporalPeriod(config).getDomain({
                domain: this.originalDomain,
                forceStartBound: false,
            });
            config.domain = this.fillTemporalDomain;
        }
        return super.webReadGroup(...arguments);
    }

    async loadGroupedList(config) {
        const res = await super.loadGroupedList(...arguments);
        if (this.isForecastGroupBy(config)) {
            const lastGroup = res.groups.filter((grp) => grp.value).slice(-1)[0];
            if (lastGroup) {
                this.fillTemporalPeriod(config).setEnd(lastGroup.range.to);
            }
        }
        return res;
    }

    isForecastGroupBy(config) {
        const forecastField = config.context.forecast_field;
        const name = config.groupBy[0].split(":")[0];
        return forecastField && forecastField === name;
    }

    fillTemporalPeriod(config) {
        const [groupByFieldName, granularity] = config.groupBy[0].split(":");
        const groupByField = config.fields[groupByFieldName];
        const minGroups =
            (config.context.fill_temporal && config.context.fill_temporal.min_groups) ||
            undefined;
        const { name, type } = groupByField;
        const forceRecompute = this.forceNextRecompute;
        this.forceNextRecompute = false;
        return this.fillTemporalService.getFillTemporalPeriod({
            modelName: config.resModel,
            field: {
                name,
                type,
            },
            granularity: granularity || "month",
            minGroups,
            forceRecompute,
        });
    }
}

ForecastKanbanModel.services = [...CrmKanbanModel.services, "fillTemporalService"];
