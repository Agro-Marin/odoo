/** @odoo-module native */
import { EventBus, reactive } from "@odoo/owl";
import { HWPrinter } from "@point_of_sale/app/utils/printer/hw_printer";
import { deduceUrl } from "@point_of_sale/utils";
import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { effect } from "@web/core/utils/reactive";

import { logPosMessage } from "../utils/pretty_console_log.js";
export class HardwareProxy extends EventBus {
    static serviceDependencies = [];
    constructor() {
        super();
        this.setup(...arguments);
    }
    setup() {
        this.host = "";
        this.keptalive = false;
        this.connectionInfo = reactive({ status: "init", drivers: {} });
        this.deviceControllers = {};
        effect(
            (info) => {
                if (info.status === "connected" && this.printer) {
                    this.printer.printReceipt();
                }
            },
            [this.connectionInfo],
        );
    }

    setConnectionInfo(info) {
        Object.assign(this.connectionInfo, info);
        if (!info.drivers && this.connectionInfo.status === "disconnected") {
            this.connectionInfo.drivers = {};
        }
    }

    disconnect() {
        if (this.connectionInfo.status !== "disconnected") {
            this.host = null;
            this.keptalive = false;
            this.setConnectionInfo({ status: "disconnected" });
        }
    }

    async connect() {
        if (this.pos.config.iface_print_via_proxy) {
            this.connectToPrinter();
        }
        try {
            if (await this.message("handshake")) {
                this.setConnectionInfo({ status: "connected" });
                localStorage.hw_proxy_url = this.host;
                this.keepAlive();
            } else {
                this.setConnectionInfo({ status: "disconnected" });
                logPosMessage(
                    "HardwareProxy",
                    "connect",
                    "Connection refused by the Proxy",
                );
            }
        } catch {
            this.setConnectionInfo({ status: "disconnected" });
            logPosMessage("HardwareProxy", "connect", "Could not connect to the Proxy");
        }
    }

    connectToPrinter() {
        this.printer = new HWPrinter({ url: this.host });
    }

    /**
     * @param {Object} [options]
     * @param {string} [options.force_ip]
     * @param {string} [options.port]
     * @returns {Promise}
     */
    async autoConnect(options) {
        this.setConnectionInfo({ status: "connecting", drivers: {} });
        let url = options.force_ip || localStorage.hw_proxy_url;
        if (!url) {
            return new Promise(() => {});
        }

        url = deduceUrl(url);

        if (await this.checkProxyAvailability(url)) {
            this.host = url;
            return this.connect(url);
        }
    }

    keepAlive() {
        const status = () => {
            if (!this.keptalive || !this.host) {
                return;
            }
            const always = () => this.keptalive && setTimeout(status, 5000);
            rpc(
                `${this.host}/hw_proxy/status_json`,
                {},
                { silent: true, timeout: 2500 },
            )
                .then(
                    (drivers) =>
                        this.setConnectionInfo({ status: "connected", drivers }),
                    () => {
                        if (this.connectionInfo.status !== "connecting") {
                            this.setConnectionInfo({ status: "disconnected" });
                        }
                    },
                )
                .then(always, always);
        };

        if (!this.keptalive) {
            this.keptalive = true;
            status();
        }
    }

    /**
     * @param {string} name
     * @param {Object} [params]
     * @returns {Promise}
     */
    message(name, params) {
        this.dispatchEvent(new CustomEvent(`send_message:${name}`));
        if (this.connectionInfo.status === "disconnected") {
            return Promise.reject();
        }
        return rpc(`${this.host}/hw_proxy/${name}`, params, { silent: true });
    }

    /**
     * @param {string} url
     * @returns {Promise<void>}
     */
    async checkProxyAvailability(url) {
        this.setConnectionInfo({ status: "connecting" });
        const maxRetries = 3;
        for (let i = 0; i <= maxRetries; i++) {
            const timeoutController = new AbortController();
            setTimeout(() => timeoutController.abort(), 1000);
            const response = await browser
                .fetch(`${url}/hw_proxy/hello`, {
                    signal: timeoutController.signal,
                    targetAddressSpace: odoo.use_lna ? "local" : undefined,
                })
                .catch(() => ({}));
            if (response.ok) {
                return true;
            }
        }
        this.setConnectionInfo({ status: "disconnected" });
        return false;
    }

    async openCashbox(action = false) {
        const isPrinterConnected =
            ["connected", "init"].includes(this.connectionInfo.status) ||
            this.pos.config.epson_printer_ip;
        if (this.pos.config.iface_cashdrawer && this.printer && isPrinterConnected) {
            this.printer.openCashbox();
            if (action) {
                this.pos.logEmployeeMessage(action, "CASH_DRAWER_ACTION");
            }
        }
    }
}

export const hardwareProxyService = {
    dependencies: HardwareProxy.serviceDependencies,
    start(env, deps) {
        return new HardwareProxy(deps);
    },
};

registry.category("services").add("hardware_proxy", hardwareProxyService);
