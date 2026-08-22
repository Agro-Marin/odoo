// Side-effect import: registers the livechat mock routes (/im_livechat/get_session, ...).
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

/**
 * Define the livechat models AND bind the mock routes to the calling file.
 *
 * `mail_mock_server.js` -- and `livechat_mock_server.js` through it -- register
 * their routes at module level, which binds them to whichever test file's suite
 * imported the module first; every other file loses them unless
 * `registerMailMockRoutes()` replays them.  `defineMailModels()` does that for
 * mail's own tests; spreading `mailModels` into `defineModels()` registers the
 * *models* but never the *routes*, which is what this did.
 *
 * The result was silent, and the same one `documents` hit: `/mail/message/post`
 * and friends went unmocked, so every flow that posts or fetches rendered
 * nothing and the tests failed as DOM timeouts rather than as missing routes.
 *
 * `models` exists so an addon that EXTENDS the livechat model set still comes
 * through this door.  `crm_livechat` and `website_livechat` used to call
 * `defineModels({ ...livechatModels, ... })` directly, which skipped both the
 * route replay above and the group ids below -- their suites only worked while
 * they happened to be the first of a run.
 */
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

/**
 * Ids of the livechat groups `ResGroups` adds to the mock `res.groups` table.
 *
 * They are handed over through `serverState` because that is what the mock
 * models and the tests read -- but `serverState` is JOB-scoped
 * (`createJobScopedGetter`): every suite derives its own copy, and an
 * assignment made while the bundle evaluates belongs to whichever job is
 * current then.  It therefore reached the first suite of a run and no other:
 * every later suite read `undefined`, `res.groups` gained no livechat record,
 * and the operator-only UI simply did not render.  That surfaced as DOM
 * timeouts in `channel_join_leave` (2) and `looking_for_help` (5) and as a
 * `TypeError` inside the mock `write` in `livechat_channel_info_list` (2) --
 * nine failures that all passed when their file was run alone.  (The same run
 * had two more, in `thread_icon_patch` and `messaging_service_patch`, which
 * failed solo as well and were stale tests, not scope leakage.)
 *
 * `defineModels` has the same constraint and answers it the same way: do the
 * work in `before()`, so it runs once per suite that asked for these models.
 */
const GROUP_LIVECHAT_ID = 42;
const GROUP_LIVECHAT_MANAGER_ID = 43;

/**
 * `start()` for the embed, mounting what the embed actually mounts.
 *
 * `mail_test_helpers.start()` mounts `WebClient`, and `webclient.js` calls
 * `store.initialize()` -- which `mail/core/web/store_service_patch.js` expands
 * into `failures` + `systray_get_activities` + `init_messaging`.  The embed has
 * no WebClient: `embed/external/boot.js` mounts `MainComponentsContainer` and
 * initialises the store only from `livechat_service.persist()`.  An embed test
 * that goes through the backend `start()` is therefore measuring a different
 * application, which is how the `verifySteps` expectations in
 * `embed/unread_messages` and `embed/livechat_service` came to encode a
 * store-fetch order the embed does not produce.
 *
 * @param {Parameters<typeof start>[0]} [options]
 */
export function startLivechatEmbed(options = {}) {
    return start({ ...options, root: MainComponentsContainer });
}

/**
 * Setup the server side of the livechat app.
 *
 * @returns {Promise<number>} the id of the livechat channel.
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
