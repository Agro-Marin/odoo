/** @odoo-module native */
import { BarcodeParser } from "@barcodes/js/barcode_parser";
import { GS1BarcodeError } from "@barcodes_gs1_nomenclature/js/barcode_parser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { Mutex } from "@web/core/utils/concurrency";
import { session } from "@web/session";
import { AlertDialog } from "@web/ui/dialog/confirmation_dialog";

import { logPosMessage } from "../utils/pretty_console_log.js";

export class BarcodeReader {
    static serviceDependencies = [
        "dialog",
        "hardware_proxy",
        "notification",
        "action",
        "orm",
    ];
    constructor(parser, { dialog, hardware_proxy, notification, action, orm }) {
        this.parser = parser;
        this.dialog = dialog;
        this.action = action;
        this.orm = orm;
        this.hardwareProxy = hardware_proxy;
        this.notification = notification;
        this.setup();
    }

    setup() {
        this.mutex = new Mutex();
        this.cbMaps = new Set();
        // FIXME POSREF: When LoginScreen becomes a normal screen, we can remove this exclusive callback handling.
        this.exclusiveCbMap = null;
        this.remoteScanning = false;
        this.remoteActive = 0;
    }

    register(cbMap, exclusive) {
        if (exclusive) {
            this.exclusiveCbMap = cbMap;
        } else {
            this.cbMaps.add(cbMap);
        }
        return () => {
            if (exclusive) {
                this.exclusiveCbMap = null;
            } else {
                this.cbMaps.delete(cbMap);
            }
        };
    }

    scan(code) {
        return this.mutex.exec(() => this._scan(code));
    }
    async _scan(code) {
        if (!code) {
            return;
        }

        const cbMaps = this.exclusiveCbMap ? [this.exclusiveCbMap] : [...this.cbMaps];

        let parseBarcode;
        try {
            parseBarcode = this.parser.parse_barcode(code);
            if (
                Array.isArray(parseBarcode) &&
                !parseBarcode.some((element) => element.type === "product")
            ) {
                throw new GS1BarcodeError("The GS1 barcode must contain a product.");
            }
        } catch (error) {
            if (error instanceof GS1BarcodeError) {
                if (this.fallbackParser) {
                    parseBarcode = this.fallbackParser.parse_barcode(code);
                } else {
                    this.showGS1IncompatibleBarcodeWarning();
                    return;
                }
            } else {
                throw error;
            }
        }
        if (Array.isArray(parseBarcode)) {
            // Await GS1 handlers like the scalar path below: fire-and-forget
            // released the scan mutex while handlers still ran, letting the
            // next scan interleave with them (and their errors were unhandled
            // rejections).
            await Promise.all(cbMaps.map((cb) => cb.gs1?.(parseBarcode)));
        } else {
            const cbs = cbMaps.map((cbMap) => cbMap[parseBarcode.type]).filter(Boolean);
            if (cbs.length === 0) {
                this.showNotFoundNotification(parseBarcode);
            }
            for (const cb of cbs) {
                await cb(parseBarcode);
            }
        }
    }
    showNotFoundNotification(code) {
        this.notification.add(
            _t(
                "The Point of Sale could not find any product, customer, employee or action associated with the scanned barcode.",
            ),
            {
                type: "warning",
                title: _t(`Unknown Barcode`) + " " + this.codeRepr(code),
            },
        );
    }

    codeRepr(parsedBarcode) {
        if (parsedBarcode.code.length > 32) {
            return parsedBarcode.code.substring(0, 29) + "...";
        } else {
            return parsedBarcode.code;
        }
    }

    showGS1IncompatibleBarcodeWarning() {
        this.notification.add(
            _t(
                "This barcode is not compatible with the GS1 standard. Consider configuring a fallback barcode parser from the PoS settings.",
            ),
            {
                type: "warning",
                title: _t("Unsupported Barcode Format"),
            },
        );
    }

    // the barcode scanner will listen on the hw_proxy/scanner interface for
    // scan events until disconnectFromProxy is called
    connectToProxy() {
        this.remoteScanning = true;
        if (this.remoteActive >= 1) {
            return;
        }
        this.remoteActive = 1;
        this.waitForBarcode();
    }

    async waitForBarcode() {
        while (this.remoteScanning) {
            let barcode;
            try {
                barcode = await this.hardwareProxy.message("scanner");
            } catch {
                // The proxy rejects synchronously while disconnected. Back off
                // instead of re-arming immediately, otherwise this recursion
                // becomes an unbounded busy loop pinning the event loop, then
                // re-check remoteScanning before retrying.
                await new Promise((resolve) => setTimeout(resolve, 1000));
                continue;
            }
            if (!this.remoteScanning) {
                break;
            }
            if (barcode) {
                // Await so overlapping scans can't interleave the next poll; a
                // scan error must not tear down the listen loop.
                await this.scan(barcode).catch(() => {});
            }
        }
        this.remoteActive = 0;
    }

    // the barcode scanner will stop listening on the hw_proxy/scanner remote interface
    disconnectFromProxy() {
        this.remoteScanning = false;
    }
}

export const barcodeReaderService = {
    dependencies: [...BarcodeReader.serviceDependencies, "dialog", "barcode", "orm"],
    async start(env, deps) {
        const { dialog, barcode, orm } = deps;
        let barcodeReader = null;

        try {
            if (session.nomenclature_id) {
                const nomenclature = await BarcodeParser.fetchNomenclature(
                    orm,
                    session.nomenclature_id,
                );
                const parser = new BarcodeParser({ nomenclature });
                barcodeReader = new BarcodeReader(parser, deps);
            }

            if (session.fallback_nomenclature_id && barcodeReader) {
                const fallbackNomenclature = await BarcodeParser.fetchNomenclature(
                    orm,
                    session.fallback_nomenclature_id,
                );
                barcodeReader.fallbackParser = new BarcodeParser({
                    nomenclature: fallbackNomenclature,
                });
            }
        } catch (error) {
            logPosMessage(
                "BarcodeReaderService",
                "start",
                "Failed to start barcode reader",
                false,
                [error],
            );
        }

        barcode.bus.addEventListener("barcode_scanned", (ev) => {
            if (barcodeReader) {
                barcodeReader.scan(ev.detail.barcode);
            } else if (session.nomenclature_id) {
                // A nomenclature IS configured — the boot-time fetch failed
                // (transient network). Diagnosing this as "not configured"
                // sent users to the settings for nothing; tell them to retry.
                dialog.add(AlertDialog, {
                    title: _t("Unable to parse barcode"),
                    body: _t(
                        "The barcode nomenclature could not be loaded when the session started. Check the connection and reload the Point of Sale to scan barcodes.",
                    ),
                });
            } else {
                dialog.add(AlertDialog, {
                    title: _t("Unable to parse barcode"),
                    body: _t(
                        "No barcode nomenclature has been configured. This can be changed in the configuration settings.",
                    ),
                });
            }
        });

        return barcodeReader;
    },
};

registry.category("services").add("barcode_reader", barcodeReaderService);
