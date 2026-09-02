// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

import { PromoteStudioDialog } from "./promote_studio_dialog.js";

export class PromoteStudioSystrayItem extends Component {
    static template = "web.PromoteStudioSystrayItem";
    static props = {};

    setup() {
        this.dialog = useService("dialog");
    }

    _onClick() {
        this.dialog.add(PromoteStudioDialog, {
            title: _t("Odoo Studio - Add new fields to any view"),
        });
    }
}

export const promoteStudioSystrayItem = {
    Component: PromoteStudioSystrayItem,
    isDisplayed: () => user.isSystem,
};

registry
    .category("systray")
    .add("PromoteStudioSystrayItem", promoteStudioSystrayItem, { sequence: 1 });
