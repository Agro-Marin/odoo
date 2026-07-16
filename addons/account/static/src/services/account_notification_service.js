/** @odoo-module native */
import { registry } from "@web/core/registry";

export const accountNotificationService = {
    dependencies: ["bus_service", "notification", "action"],

    start(env, { bus_service, notification, action }) {
        bus_service.subscribe(
            "account_notification",
            ({ message, sticky, title, type, action_button }) => {
                // action_button is optional: senders that only need a plain toast omit it.
                const buttons = action_button
                    ? [
                          {
                              name: action_button.name,
                              primary: false,
                              onClick: () => {
                                  action.doAction({
                                      // action_name is already translated server-side; do not
                                      // re-wrap it in _t() (a runtime value never in the client catalog).
                                      name: action_button.action_name,
                                      type: "ir.actions.act_window",
                                      res_model: action_button.model,
                                      domain: [["id", "in", action_button.res_ids]],
                                      views: [
                                          [false, "list"],
                                          [false, "form"],
                                      ],
                                      target: "current",
                                  });
                              },
                          },
                      ]
                    : [];
                notification.add(message, { sticky, title, type, buttons });
            },
        );
    },
};

registry.category("services").add("accountNotification", accountNotificationService);
