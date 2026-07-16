/** @odoo-module native */
import { LivechatPivotRendererMixin } from "@im_livechat/views/lazy/im_livechat_pivot_renderer_mixin";
import { registry } from "@web/core/registry";
import { pivotView } from "@web/views/pivot/pivot_view";

registry.category("views").add("im_livechat.report_channel_pivot", {
    ...pivotView,
    Renderer: LivechatPivotRendererMixin("im_livechat.report.channel"),
});
