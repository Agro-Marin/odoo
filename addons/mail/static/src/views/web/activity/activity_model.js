/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { RelationalModel } from "@web/model/relational_model/relational_model";
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
        // token guard (not KeepLast, which would resolve in a separate
        // microtask and split the load into an extra render): super.load()'s
        // record fetch is KeepLast-guarded, so without matching the two
        // overlapping loads (fast filter/pager change with RPCs reordering)
        // could leave activityData from one load and root.records from
        // another — the renderer then maps one load's resIds over the other's
        // records. A stale response is discarded instead of committed.
        // Stored on the RAW model: the model is a reactive proxy, so writing
        // the token through it would fire a spurious notification/render.
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
