/** @odoo-module native */
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { FormRenderer } from "@web/views/form";

export class ProjectSharingFormRenderer extends FormRenderer {
    static components = {
        ...FormRenderer.components,
        Chatter,
    };
}
