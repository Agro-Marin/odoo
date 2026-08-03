/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { RelationalModel } from "@web/model/relational_model";
export class ActivityModel extends RelationalModel {
    static DEFAULT_LIMIT = 100;

    async load(params = {}) {
        this.originalDomain = params.domain ? [...params.domain] : [];
        // Ensure that only (active) records with at least one activity, "done" (archived) or not, are fetched.
        // We don't use active_test=false in the context because otherwise we would also get archived records.
        params.domain = [
            ...(params.domain || []),
            ["activity_ids.active", "in", [true, false]],
        ];
        if (params && "groupBy" in params) {
            params.groupBy = [];
        }
        await Promise.all([this.fetchActivityData(params), super.load(params)]);
    }

    async fetchActivityData(params) {
        // Token guard rather than KeepLast (which resolves in a separate microtask
        // and splits the load into an extra render): a stale response is discarded so
        // activityData and the KeepLast-guarded root.records come from the same load.
        // Kept on the RAW model, as writing through the reactive proxy would fire a
        // spurious notification/render.
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
