import "./mock_server/livechat_mock_server.js";

import { IrWebSocket } from "@im_livechat/../tests/mock_server/mock_models/ir_websocket";
import { mailModels, startServer } from "@mail/../tests/mail_test_helpers";
import { start } from "@mail/../tests/mail_test_helpers";
import { registerMailMockRoutes } from "@mail/../tests/mock_server/mail_mock_server";
import { before } from "@odoo/hoot";
import { RatingRating } from "@rating/../tests/mock_server/models/rating_rating";
import {
    defineModels,
    MockServer,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";
import { session } from "@web/session";
import { MainComponentsContainer } from "@web/ui/main_components_container";

import { DiscussChannel } from "./mock_server/mock_models/discuss_channel.js";
import { DiscussChannelMember } from "./mock_server/mock_models/discuss_channel_member.js";
import { LivechatChannel } from "./mock_server/mock_models/im_livechat_channel.js";
import { Im_LivechatExpertise } from "./mock_server/mock_models/im_livechat_expertise.js";
import { LivechatChannelRule } from "./mock_server/mock_models/livechat_channel_rule.js";
import { ResGroups } from "./mock_server/mock_models/res_groups.js";
import { ResGroupsPrivilege } from "./mock_server/mock_models/res_groups_privilege.js";
import { ResPartner } from "./mock_server/mock_models/res_partner.js";
import { ResUsers } from "./mock_server/mock_models/res_users.js";

export function defineLivechatModels(models = livechatModels) {
    registerMailMockRoutes();
    before(() => {
        serverState.groupLivechatId = GROUP_LIVECHAT_ID;
        serverState.groupLivechatManagerId = GROUP_LIVECHAT_MANAGER_ID;
    });
    return defineModels(models);
}

export const livechatModels = {
    ...mailModels,
    DiscussChannel,
    DiscussChannelMember,
    LivechatChannel,
    LivechatChannelRule,
    Im_LivechatExpertise,
    IrWebSocket,
    RatingRating,
    ResPartner,
    ResUsers,
    ResGroupsPrivilege,
    ResGroups,
};

const GROUP_LIVECHAT_ID = 42;
const GROUP_LIVECHAT_MANAGER_ID = 43;

/**
 * @param {Parameters<typeof start>[0]} [options]
 */
export function startLivechatEmbed(options = {}) {
    return start({ ...options, root: MainComponentsContainer });
}

/**
 * @returns {Promise<number>}
 */
export async function loadDefaultEmbedConfig() {
    const pyEnv = MockServer.env ?? (await startServer());
    const livechatChannelId = pyEnv["im_livechat.channel"].create({
        user_ids: [serverState.userId],
    });
    patchWithCleanup(session, {
        livechatData: {
            can_load_livechat: true,
            serverUrl: window.origin,
            options: {
                header_background_color: "#875A7B",
                button_background_color: "#875A7B",
                title_color: "#FFFFFF",
                button_text_color: "#FFFFFF",
                button_text: "Need help? Chat with us.",
                default_message: "Hello, how may I help you?",
                channel_name: "YourWebsite.com",
                channel_id: livechatChannelId,
                default_username: "Visitor",
                review_link: "https://www.odoo.com",
            },
        },
    });
    return livechatChannelId;
}
