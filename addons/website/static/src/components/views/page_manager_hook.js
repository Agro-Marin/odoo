/** @odoo-module native */
import { onWillStart, useEnv, useState } from "@odoo/owl";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { AddPageDialog } from "@website/components/dialog/add_page_dialog";

export function usePageManager({ resModel, createAction }) {
    const env = useEnv();
    const website = useService("website");
    const dialog = useService("dialog");
    const actionService = useService("action");
    const websiteSelection = odoo.debug ? [{ id: 0, name: _t("All Websites") }] : [];
    const state = useState({
        activeWebsite: undefined,
    });

    onWillStart(async () => {
        websiteSelection.push(...website.websites);
        state.activeWebsite = await env.searchModel.getCurrentWebsite();
    });

    async function createWebsiteContent() {
        if (resModel === "website.page") {
            return dialog.add(AddPageDialog, {
                websiteId: state.activeWebsite.id,
            });
        }
        if (createAction) {
            if (/^\//.test(createAction)) {
                const url = await rpc(createAction);
                website.goToWebsite({ path: url, edition: true });
                return;
            }
            actionService.doAction(createAction, {
                onClose: (infos) => {
                    if (infos) {
                        website.goToWebsite({ path: infos.path });
                    }
                },
                props: {
                    onSave: (record, params) => {
                        if (record.resId && params.computePath) {
                            const path = params.computePath();
                            actionService.doAction({
                                type: "ir.actions.act_window_close",
                                infos: { path },
                            });
                        }
                    },
                },
            });
        }
    }

    return {
        get websites() {
            const activeId = state.activeWebsite.id;
            return websiteSelection.map((website) => {
                const isActive = website.id === activeId;
                return { ...website, isActive };
            });
        },
        createWebsiteContent,
    };
}
