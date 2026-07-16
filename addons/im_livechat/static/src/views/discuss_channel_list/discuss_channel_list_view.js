/** @odoo-module native */
import { registry } from "@web/core/registry";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

import { LivechatViewControllerMixin } from "../livechat_view_controller_mixin.js";

class DiscussChannelListController extends LivechatViewControllerMixin(
    ListController,
) {}

const discussChannelListView = {
    ...listView,
    Controller: DiscussChannelListController,
};

registry
    .category("views")
    .add("im_livechat.discuss_channel_list", discussChannelListView);
