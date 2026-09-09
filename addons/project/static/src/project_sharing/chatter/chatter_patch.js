/** @odoo-module native */
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { onWillUpdateProps, useSubEnv } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        Object.assign(this.state, {
            isFollower: this.props.isFollower,
        });
        onWillUpdateProps((nextProps) => {
            if (nextProps.isFollower !== this.props.isFollower) {
                this.state.isFollower = nextProps.isFollower;
            }
        });
        this.orm = useService("orm");
        useSubEnv({
            projectSharingId: this.props.projectSharingId,
        });
    },

    async toggleIsFollower() {
        this.state.isFollower = await this.orm.call(
            this.props.threadModel,
            "project_sharing_toggle_is_follower",
            [this.props.threadId],
        );
    },
    onPostCallback() {
        super.onPostCallback();
        this.state.isFollower = true;
    },
});
Chatter.props = [
    ...Chatter.props,
    "projectSharingId",
    "isFollower",
    "displayFollowButton",
];
