/** @odoo-module native */
import { registry } from "@web/core/registry";
import { KanbanController, kanbanView } from "@web/views/kanban";

import { LivechatLookingForHelpReloadMixin } from "../livechat_looking_for_help_controller_mixin.js";

class DiscussChannelKanbanLookingForHelpController extends LivechatLookingForHelpReloadMixin(
    KanbanController,
) {}

const discussChannelLookingForHelpKanbanView = {
    ...kanbanView,
    Controller: DiscussChannelKanbanLookingForHelpController,
};

registry
    .category("views")
    .add(
        "im_livechat.discuss_channel_looking_for_help_kanban",
        discussChannelLookingForHelpKanbanView,
    );
