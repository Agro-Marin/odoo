import { makeKwArgs, models } from "@web/../tests/web_test_helpers";

export class IrWebSocket extends models.ServerModel {
    _name = "ir.websocket";

    /**
     * @param {number} inactivityPeriod
     */
    _update_presence(inactivityPeriod) {}

    /**
     * @returns {string[]}
     */
    _build_bus_channel_list(channels = []) {
        /** @type {import("mock_models").ResPartner} */
        const ResPartner = this.env["res.partner"];

        channels = [...channels];
        channels.push("broadcast");
        // DIVERGENCE FROM ir_websocket.py: the real server also appends the
        // user's group records (`env.user.all_group_ids`) so group-targeted
        // notifications reach the tab. The web mock's `res.users` models no
        // group membership (no `group_ids`/`all_group_ids` field is seeded),
        // so group channels cannot be reproduced here — group-targeted
        // broadcasts are out of scope for these HOOT suites. The authenticated
        // partner channel below IS mirrored.
        const authenticatedUserId = this.env.cookie.get("authenticated_user_sid");
        const [authenticatedPartner] = authenticatedUserId
            ? ResPartner.search_read(
                  [["user_ids", "in", [authenticatedUserId]]],
                  makeKwArgs({ context: { active_test: false } }),
              )
            : [];
        if (authenticatedPartner) {
            channels.push(authenticatedPartner);
        }
        return channels;
    }
}
