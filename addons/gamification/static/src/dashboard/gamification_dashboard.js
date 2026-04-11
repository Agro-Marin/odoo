/** @odoo-module native */
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";

class GamificationDashboard extends Component {
    static template = "gamification.Dashboard";
    static components = { Layout };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

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

        onWillStart(async () => {
            await this.loadData();
        });
    }

    get display() {
        return { controlPanel: {} };
    }

    async loadData() {
        this.state.loading = true;
        const [data, analytics] = await Promise.all([
            this.orm.call("res.users", "get_gamification_dashboard_data", []),
            this.orm.call("gamification.engagement.snapshot", "get_analytics_summary", []),
        ]);
        Object.assign(this.state, data, { analytics, loading: false });
    }

    async refresh() {
        await this.loadData();
        this.notification.add("Dashboard refreshed", { type: "info", sticky: false });
    }

    getRarityClass(rarity) {
        const map = {
            common: "text-muted",
            rare: "text-info",
            epic: "text-warning",
            legendary: "text-success",
        };
        return map[rarity] || "";
    }

    getBadgeLevelClass(level) {
        const map = {
            gold: "text-warning",
            silver: "text-muted",
            bronze: "text-danger",
        };
        return map[level] || "";
    }

    getStreakIcon(streak) {
        if (streak.state === "broken") return "fa-heart-o text-danger";
        if (streak.current_count >= 30) return "fa-fire text-warning";
        if (streak.current_count >= 7) return "fa-fire text-success";
        return "fa-fire text-muted";
    }

    getTrendIcon(trend) {
        const map = {
            up: "fa-arrow-up text-success",
            down: "fa-arrow-down text-danger",
            flat: "fa-minus text-muted",
            new: "fa-plus text-info",
        };
        return map[trend] || "fa-minus text-muted";
    }

    // ── Navigation ─────────────────────────────────────────────────

    async openChallenges() {
        this.actionService.doAction("gamification.challenge_list_action");
    }

    async openBadges() {
        this.actionService.doAction("gamification.badge_list_action");
    }

    async openKudos() {
        this.actionService.doAction("gamification.kudos_list_action");
    }

    async openStreaks() {
        this.actionService.doAction("gamification.streak_list_action");
    }

    async openAnalytics() {
        this.actionService.doAction("gamification.engagement_snapshot_list_action");
    }

    // ── Send Kudos ─────────────────────────────────────────────────

    async toggleKudosForm() {
        if (!this.state.kudosFormOpen && this.state.kudosUsers.length === 0) {
            // Load users and categories for the form
            const [users, categories] = await Promise.all([
                this.orm.searchRead(
                    "res.users",
                    [["active", "=", true], ["share", "=", false], ["id", "!=", this.state.profile.user_id || false]],
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

    onKudosRecipientChange(ev) {
        this.state.kudosRecipientId = parseInt(ev.target.value) || false;
    }

    onKudosCategoryChange(ev) {
        this.state.kudosCategoryId = parseInt(ev.target.value) || false;
    }

    onKudosMessageChange(ev) {
        this.state.kudosMessage = ev.target.value;
    }

    async sendKudos() {
        const { kudosRecipientId, kudosCategoryId, kudosMessage } = this.state;
        if (!kudosRecipientId || !kudosCategoryId || !kudosMessage.trim()) {
            this.notification.add("Please fill in all fields", { type: "warning" });
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
                `Kudos sent to ${result.recipient_name}! (+${result.karma_granted} karma)`,
                { type: "success" },
            );
            // Reset form and refresh feed
            this.state.kudosRecipientId = false;
            this.state.kudosCategoryId = false;
            this.state.kudosMessage = "";
            this.state.kudosFormOpen = false;
            await this.loadData();
        } catch (e) {
            this.notification.add(e.message || "Failed to send kudos", { type: "danger" });
        } finally {
            this.state.kudosSending = false;
        }
    }
}

registry.category("actions").add("gamification_dashboard", GamificationDashboard);
