/** @odoo-module native */
import { EventBus, reactive } from "@odoo/owl";
import { HWPrinter } from "@point_of_sale/app/utils/printer/hw_printer";
import { deduceUrl } from "@point_of_sale/utils";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { effect } from "@web/core/utils/reactive";

import { logPosMessage } from "../utils/pretty_console_log.js";
const log = makeLogger("pos.hardware_proxy");

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
        log.lifecycle("setConnectionInfo", () => ({
            from: this.connectionInfo.status,
            to: info.status,
            drivers: info.drivers ? Object.keys(info.drivers) : undefined,
        }));
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
        log.lifecycle("connect", () => ({
            host: this.host,
            status: this.connectionInfo.status,
        }));
        if (this.pos.config.iface_print_via_proxy) {
            this.connectToPrinter();
        }
        const endConnect = log.perf("connect");
        try {
            if (await this.message("handshake")) {
                this.setConnectionInfo({ status: "connected" });
                localStorage.hw_proxy_url = this.host;
                this.keepAlive();
                endConnect({ host: this.host, connected: true });
            } else {
                endConnect({ host: this.host, refused: true });
                this.setConnectionInfo({ status: "disconnected" });
                logPosMessage(
                    "HardwareProxy",
                    "connect",
                    "Connection refused by the Proxy",
                );
            }
        } catch {
            endConnect({ host: this.host, unreachable: true });
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
        log.logic("autoConnect", () => ({
            forceIp: options.force_ip,
            stored: localStorage.hw_proxy_url,
            url,
        }));
        if (!url) {
            return new Promise(() => {});
        }

        url = deduceUrl(url);

        const available = await this.checkProxyAvailability(url);
        log.logic("autoConnect: availability", () => ({ url, available }));
        if (available) {
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
                        log.logic("keepAlive: status failed", () => ({
                            host: this.host,
                            status: this.connectionInfo.status,
                        }));
                        if (this.connectionInfo.status !== "connecting") {
                            this.setConnectionInfo({ status: "disconnected" });
                        }
                    },
                )
                .then(always, always);
        };

        if (!this.keptalive) {
            log.lifecycle("keepAlive: started", () => ({ host: this.host }));
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
        log.pipeline("message", () => ({
            name,
            params,
            status: this.connectionInfo.status,
        }));
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
        const endCheck = log.perf("checkProxyAvailability");
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
                endCheck({ url, attempt: i + 1, ok: true });
                return true;
            }
        }
        endCheck({ url, attempts: maxRetries + 1, ok: false });
        this.setConnectionInfo({ status: "disconnected" });
        return false;
    }

    async openCashbox(action = false) {
        const isPrinterConnected =
            ["connected", "init"].includes(this.connectionInfo.status) ||
            this.pos.config.epson_printer_ip;
        log.logic("openCashbox", () => ({
            action,
            cashdrawer: this.pos.config.iface_cashdrawer,
            printer: Boolean(this.printer),
            isPrinterConnected: Boolean(isPrinterConnected),
        }));
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
