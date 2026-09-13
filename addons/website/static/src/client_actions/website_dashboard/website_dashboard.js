/** @odoo-module native */
import { Component, useEffect, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { KeepLast } from "@web/core/utils/concurrency";
import { Layout } from "@web/search/layout";
import { DocumentationLink } from "@web/views/widgets";

const log = makeLogger("website.client_action.website_dashboard");

class WebsiteDashboard extends Component {
    static template = "website.WebsiteDashboardMain";
    static components = { Layout, DocumentationLink };
    static props = ["*"];
    setup() {
        super.setup();
        useLifecycleLog(log);
        this.keepLast = new KeepLast();

        this.state = useState({
            website: false,
            groups: {},
            websites: [],
            dashboards: {},
        });

        useEffect(
            () => {
                this.fetchData();
            },
            () => [this.state.website],
        );
    }

    get display() {
        return {
            controlPanel: {},
        };
    }

    async fetchData() {
        const endFetch = log.perf("fetch_dashboard_data", () => ({
            website: this.state.website,
        }));
        const dashboardData = await this.keepLast.add(
            rpc("/website/fetch_dashboard_data", {
                website_id: this.state.website,
            }),
        );
        endFetch(() => ({ keys: Object.keys(dashboardData) }));
        Object.assign(this.state, dashboardData);
    }
}

registry.category("actions").add("backend_dashboard", WebsiteDashboard);
