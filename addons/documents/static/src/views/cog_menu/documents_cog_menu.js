/** @odoo-module native */
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { registry } from "@web/core/registry";
import { documentsCogMenuItemArchive } from "./documents_cog_menu_item_archive.js";
import { documentCogMenuPinAction } from "./documents_cog_menu_pin_actions.js";
import { documentsCogMenuItemDetails } from "./documents_cog_menu_item_details.js";
import { documentsCogMenuItemDownload } from "./documents_cog_menu_item_download.js";
import { documentsCogMenuItemShare } from "./documents_cog_menu_item_share.js";
import { documentsCogMenuItemRename } from "./documents_cog_menu_item_rename.js";
import { documentsCogMenuItemShortcut } from "./documents_cog_menu_item_shortcut.js";
import {
    documentsCogMenuItemStarAdd,
    documentsCogMenuItemStarRemove,
} from "./documents_cog_menu_item_star.js";
import { documentsCogMenuItemAutomations } from "./documents_cog_menu_item_automations.js";

export const documentsCogMenuRegistry = registry.category("documents_cog_menu");

for (const item of [
    documentsCogMenuItemDownload,
    documentsCogMenuItemRename,
    documentsCogMenuItemShare,
    documentsCogMenuItemShortcut,
    documentsCogMenuItemStarAdd,
    documentsCogMenuItemStarRemove,
    documentsCogMenuItemDetails,
    documentsCogMenuItemArchive,
    documentCogMenuPinAction,
    documentsCogMenuItemAutomations,
]) {
    documentsCogMenuRegistry.add(item.Component.name, item);
}

export class DocumentsCogMenu extends CogMenu {
    async _registryItems() {
        const items = documentsCogMenuRegistry.getEntries();
        const displayed = await Promise.all(
            items.map(([, item]) => item.isDisplayed(this.env))
        );
        return items
            .filter((_item, index) => displayed[index])
            .map(([key, item]) => ({
                Component: item.Component,
                groupNumber: item.groupNumber,
                key,
            }));
    }
}
