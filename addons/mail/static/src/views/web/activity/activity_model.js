// @ts-check
/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { RelationalModel } from "@web/model/relational_model";

const log = makeLogger("mail.activity.view");
export class ActivityModel extends RelationalModel {
    static DEFAULT_LIMIT = 100;
    /** @type {number | undefined} */
    _activityDataToken;

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
        delete params.limit;
        const endLoad = log.perf("load");
        await Promise.all([this.fetchActivityData(params), super.load(params)]);
        endLoad({
            resModel: this.config.resModel,
            records: this.root?.records?.length,
        });
    }

    /** @param {Object} params */
    async fetchActivityData(params) {
        const raw = toRaw(this);
        const token = (raw._activityDataToken = (raw._activityDataToken ?? 0) + 1);
        const endFetch = log.perf("get_activity_data");
        const activityData = await this.orm.call(
            "mail.activity",
            "get_activity_data",
            [],
            {
                res_model: this.config.resModel,
                context: params.context,
                domain: params.domain || this.env.searchModel.domain,
                limit: params.limit || this.initialLimit,
                offset: params.offset || 0,
                fetch_done: false,
            },
        );
        endFetch({
            token,
            superseded: token !== raw._activityDataToken,
            activityTypes: activityData?.activity_types?.length,
            records: Object.keys(activityData?.grouped_activities ?? {}).length,
        });
        if (token === raw._activityDataToken) {
            this.activityData = activityData;
        }
    }
}
