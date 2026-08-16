/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
/**
 * @param {Object} params
 * @param {import("@odoo/owl").Component} params.component
 * @param {import("@web/env").OdooEnv} params.env
 * @returns {Object|null}
 */
export function manageMessages({ component, env }) {
    const resId = component.model.root.resId;
    if (!resId) {
        return null;
    }
    const description = _t("Messages");
    return {
        type: "item",
        description,
        callback: () => {
            env.services.action.doAction({
                res_model: "mail.message",
                name: description,
                views: [
                    [false, "list"],
                    [false, "form"],
                ],
                type: "ir.actions.act_window",
                domain: [
                    ["res_id", "=", resId],
                    ["model", "=", component.props.resModel],
                ],
                context: {
                    default_res_model: component.props.resModel,
                    default_res_id: resId,
                },
            });
        },
        sequence: 130,
        section: "record",
    };
}

registry.category("debug").category("form").add("mail.manageMessages", manageMessages);
