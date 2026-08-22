// Side-effect import: applies the website-livechat mock-server patch (attaches
// visitor discuss channels to the livechat session-data route).
import "@website/../tests/mock_server/website_livechat_mock_server";

import {
    defineLivechatModels,
    livechatModels,
} from "@im_livechat/../tests/livechat_test_helpers";
import { defineParams } from "@web/../tests/web_test_helpers";
import { websiteModels } from "@website/../tests/helpers";

import { DiscussChannel } from "./mock_server/mock_models/discuss_channel.js";
import { WebsiteVisitor } from "./mock_server/mock_models/website_visitor.js";

export function defineWebsiteLivechatModels() {
    defineParams({ suite: "website_livechat" }, "replace");
    return defineLivechatModels(websiteLivechatModels);
}

export const websiteLivechatModels = {
    ...websiteModels,
    ...livechatModels,
    WebsiteVisitor,
    DiscussChannel,
};
