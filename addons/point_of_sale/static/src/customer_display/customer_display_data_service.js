/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { getOnNotified } from "@point_of_sale/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { session } from "@web/session";
const log = makeLogger("pos.customer_display.data");

export const CustomerDisplayDataService = {
    dependencies: ["bus_service", "notification"],
    async start(env, { bus_service, notification }) {
        const data = reactive({});
        log.lifecycle("start", () => ({
            source: session.proxy_ip ? "iot_poll" : "bus+broadcast",
            device: session.device_uuid,
        }));
        if (session.proxy_ip) {
            let consecutiveFailures = 0;
            let warned = false;
            setInterval(async () => {
                const endPoll = log.perf("[iot] poll customer_facing_display");
                try {
                    const response = await fetch(
                        `http://localhost:8069/hw_proxy/customer_facing_display`,
                        {
                            method: "POST",
                            headers: {
                                Accept: "application/json",
                                "Content-Type": "application/json",
                            },
                            body: JSON.stringify({
                                params: {
                                    action: "get",
                                },
                            }),
                        },
                    );
                    const payload = await response.json();
                    Object.assign(data, payload.result?.data || payload.result);
                    consecutiveFailures = 0;
                    warned = false;
                    endPoll({ lines: data.lines?.length });
                } catch (error) {
                    consecutiveFailures++;
                    endPoll({ failed: true, consecutiveFailures });
                    if (consecutiveFailures >= 5 && !warned) {
                        warned = true;
                        notification.add(
                            _t(
                                "Make sure there is an IoT Box subscription associated with your Odoo database, then restart the IoT Box.",
                            ),
                            {
                                title: _t("IoT Customer Display Error"),
                                type: "danger",
                            },
                        );
                        console.error(
                            "Error fetching data for the IoT customer display: %s",
                            error,
                        );
                    }
                }
            }, 1000);
        } else {
            new BroadcastChannel("UPDATE_CUSTOMER_DISPLAY").onmessage = (event) => {
                log.pipeline("[broadcast] update", () => ({
                    lines: event.data?.lines?.length,
                    finalized: event.data?.finalized,
                }));
                Object.assign(data, event.data);
            };
            getOnNotified(bus_service, session.access_token)(
                `UPDATE_CUSTOMER_DISPLAY-${session.device_uuid}`,
                (payload) => {
                    log.pipeline("[bus] update", () => ({
                        lines: payload?.lines?.length,
                        finalized: payload?.finalized,
                    }));
                    Object.assign(data, payload);
                },
            );
        }
        return data;
    },
};

registry.category("services").add("customer_display_data", CustomerDisplayDataService);
