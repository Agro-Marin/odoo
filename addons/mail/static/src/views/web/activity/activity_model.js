/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { RelationalModel } from "@web/model/relational_model";
export class ActivityModel extends RelationalModel {
    static DEFAULT_LIMIT = 100;

    /** @param {Object} [params={}] */
    async load(params = {}) {
        this.originalDomain = params.domain ? [...params.domain] : [];
        params.domain = [
            ...(params.domain || []),
            ["activity_ids.active", "in", [true, false]],
        ];
        if (params && "groupBy" in params) {
            params.groupBy = [];
        }
        await Promise.all([this.fetchActivityData(params), super.load(params)]);
    }

    /** @param {Object} params */
    async fetchActivityData(params) {
        const raw = toRaw(this);
        const token = (raw._activityDataToken = (raw._activityDataToken ?? 0) + 1);
        const activityData = await this.orm.call(
            "mail.activity",
            "get_activity_data",
            [],
            {
                res_model: this.config.resModel,
                context: params.context,
                domain: params.domain || this.env.searchModel._domain,
                limit: params.limit || this.initialLimit,
                offset: params.offset || 0,
                fetch_done: false,
            },
        );
        if (token === raw._activityDataToken) {
            this.activityData = activityData;
        }
    }
}
