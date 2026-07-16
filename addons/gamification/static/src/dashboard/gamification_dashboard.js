/** @odoo-module native */
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/services/user";
import { _t } from "@web/core/l10n/translation";
import { Layout } from "@web/search/layout";
import {
    getBadgeLevelClass,
    getRarityBadgeClass,
    getStreakIcon,
    getTrendIcon,
} from "./gamification_dashboard_utils.js";

class GamificationDashboard extends Component {
    static template = "gamification.Dashboard";
    static components = { Layout };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        // Layout display config — a stable reference so <Layout> is not handed a
        // fresh prop object on every render.
        this.display = { controlPanel: {} };

        // Expose the pure presentation helpers to the template.  The logic lives
        // in gamification_dashboard_utils so it can be unit-tested standalone.
        this.getBadgeLevelClass = getBadgeLevelClass;
        this.getRarityBadgeClass = getRarityBadgeClass;
        this.getStreakIcon = getStreakIcon;
        this.getTrendIcon = getTrendIcon;

        this.state = useState({
            profile: {},
            streaks: [],
            goals: [],
            badges: [],
            activity_feed: [],
            achievements: [],
            leaderboard: [],
            analytics: null,
            loading: true,
            // Send-kudos form state
            kudosFormOpen: false,
            kudosRecipientId: false,
            kudosCategoryId: false,
            kudosMessage: "",
            kudosSending: false,
            // Lookup data for the kudos form
            kudosUsers: [],
            kudosCategories: [],
        });

        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            // The two calls are independent and analytics is optional (the
            // template guards on it).  Load them concurrently but do NOT let an
            // analytics failure take down the whole dashboard, and always clear
            // the loading flag so a failure can never leave a stuck spinner.
            const [dataResult, analyticsResult] = await Promise.allSettled([
                this.orm.call("res.users", "get_gamification_dashboard_data", []),
                this.orm.call(
                    "gamification.engagement.snapshot",
                    "get_analytics_summary",
                    [],
                ),
            ]);
            if (dataResult.status === "rejected") {
                throw dataResult.reason;
            }
            Object.assign(this.state, dataResult.value, {
                analytics:
                    analyticsResult.status === "fulfilled"
                        ? analyticsResult.value
                        : null,
            });
        } finally {
            this.state.loading = false;
        }
    }

    async refresh() {
        await this.loadData();
        this.notification.add(_t("Dashboard refreshed"), {
            type: "info",
            sticky: false,
        });
    }

    // ── Navigation ─────────────────────────────────────────────────

    openAction(xmlId) {
        return this.actionService.doAction(xmlId);
    }

    // ── Send Kudos ─────────────────────────────────────────────────

    async toggleKudosForm() {
        if (!this.state.kudosFormOpen && this.state.kudosUsers.length === 0) {
            // Load recipients (everyone but the current user) and categories.
            const [users, categories] = await Promise.all([
                this.orm.searchRead(
                    "res.users",
                    [
                        ["active", "=", true],
                        ["share", "=", false],
                        ["id", "!=", user.userId],
                    ],
                    ["name"],
                    { order: "name", limit: 100 },
                ),
                this.orm.searchRead(
                    "gamification.kudos.category",
                    [["active", "=", true]],
                    ["name", "icon", "karma_granted"],
                    { order: "sequence" },
                ),
            ]);
            this.state.kudosUsers = users;
            this.state.kudosCategories = categories;
        }
        this.state.kudosFormOpen = !this.state.kudosFormOpen;
    }

    async sendKudos() {
        const { kudosRecipientId, kudosCategoryId, kudosMessage } = this.state;
        if (!kudosRecipientId || !kudosCategoryId || !kudosMessage.trim()) {
            this.notification.add(_t("Please fill in all fields"), {
                type: "warning",
            });
            return;
        }
        this.state.kudosSending = true;
        try {
            const result = await this.orm.call(
                "res.users",
                "send_kudos_from_dashboard",
                [kudosRecipientId, kudosCategoryId, kudosMessage],
            );
            this.notification.add(
                _t("Kudos sent to %(name)s! (+%(karma)s karma)", {
                    name: result.recipient_name,
                    karma: result.karma_granted,
                }),
                { type: "success" },
            );
            // Reset form and refresh feed
            this.state.kudosRecipientId = false;
            this.state.kudosCategoryId = false;
            this.state.kudosMessage = "";
            this.state.kudosFormOpen = false;
            await this.loadData();
        } catch (e) {
            // Business errors (UserError/ValidationError) carry the human-readable
            // text on ``data.message``; the top-level ``message`` is the generic
            // "Odoo Server Error" wrapper.
            this.notification.add(
                e.data?.message || e.message || _t("Failed to send kudos"),
                {
                    type: "danger",
                },
            );
        } finally {
            this.state.kudosSending = false;
        }
    }
}

registry.category("actions").add("gamification_dashboard", GamificationDashboard);
