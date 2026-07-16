/** @odoo-module native */
import { registry } from "@web/core/registry";
import { BaseHeader } from "@website/interactions/header/base_header";

const BaseHeaderEdit = (I) =>
    class extends I {
        adjustPosition() {}
    };

registry.category("public.interactions.edit").add("website.base_header", {
    Interaction: BaseHeader,
    mixin: BaseHeaderEdit,
    isAbstract: true,
});
