/** @odoo-module native */
import { onWillStart, useEnv, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { AddPageDialog } from "@website/components/dialog/add_page_dialog";

const log = makeLogger("website.view.page_manager_hook");

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
        const endCurrent = log.perf("usePageManager getCurrentWebsite");
        state.activeWebsite = await env.searchModel.getCurrentWebsite();
        endCurrent(() => ({ websites: websiteSelection.length }));
    });

    async function createWebsiteContent() {
        log.logic("createWebsiteContent", { resModel, createAction });
        if (resModel === "website.page") {
            return dialog.add(AddPageDialog, {
                websiteId: state.activeWebsite.id,
            });
        }
        if (createAction) {
            if (/^\//.test(createAction)) {
                const endCreate = log.perf("createWebsiteContent rpc route", {
                    createAction,
                });
                const url = await rpc(createAction);
                endCreate({ url });
                website.goToWebsite({ path: url, edition: true });
                return;
            }
            actionService.doAction(createAction, {
                onClose: (infos) => {
                    if (infos) {
                        log.logic("createWebsiteContent closed: go to website", () => ({
                            path: infos.path,
                        }));
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
