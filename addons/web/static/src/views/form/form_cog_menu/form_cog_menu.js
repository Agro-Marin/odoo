// @ts-check
/** @odoo-module native */

import { useService } from "@web/core/utils/hooks";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
export class FormCogMenu extends CogMenu {
    static template = "web.FormCogMenu";

    setup() {
        super.setup();
        this.ui = useService("ui");
    }
}
