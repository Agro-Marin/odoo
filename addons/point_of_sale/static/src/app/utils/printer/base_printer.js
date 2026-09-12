/** @odoo-module native */
import { htmlToCanvas } from "@point_of_sale/app/services/render_service";
import { makeLogger } from "@web/core/debug/debug_logger";
import { ConnectionLostError } from "@web/core/network";
import { _t } from "@web/core/translation";
const log = makeLogger("pos.printer.device");
export class BasePrinter {
    constructor() {
        this.setup(...arguments);
    }

    setup() {
        this.receiptQueue = [];
    }

    /**
     * @param {String} receipt:
     * @returns {{ successful: boolean; message?: { title: string; body?: string }}}
     */
    async printReceipt(receipt) {
        log.pipeline("printReceipt", () => ({
            printer: this.constructor.name,
            queued: this.receiptQueue.length,
            locked: Boolean(this._jobLock),
            receipt: Boolean(receipt),
        }));
        const run = () => this._printReceiptImpl(receipt);
        const result = (this._jobLock ?? Promise.resolve()).then(run, run);
        this._jobLock = result.catch(() => {});
        return result;
    }

    async _printReceiptImpl(receipt) {
        if (receipt) {
            this.receiptQueue.push(receipt);
        }
        let image, printResult;
        let printed = 0;
        const endJob = log.perf(`printReceipt ${this.constructor.name}`);
        while (this.receiptQueue.length > 0) {
            receipt = this.receiptQueue.shift();
            const endProcess = log.perf("processCanvas");
            image = this.processCanvas(
                await htmlToCanvas(receipt, { addClass: "pos-receipt-print" }),
            );
            endProcess({ bytes: image?.length });
            try {
                const endSend = log.perf("sendPrintingJob");
                printResult = await this.sendPrintingJob(image);
                endSend({
                    result: printResult?.result,
                    errorCode: printResult?.errorCode,
                    status: printResult?.status,
                });
            } catch (error) {
                this.receiptQueue.length = 0;
                endJob({
                    printed,
                    error: error instanceof ConnectionLostError ? "offline" : "action",
                });
                if (error instanceof ConnectionLostError) {
                    return this.getOfflineError();
                }
                return this.getActionError();
            }
            if (!printResult || printResult.result === false) {
                this.receiptQueue.length = 0;
                endJob({ printed, resultError: printResult?.errorCode });
                return this.getResultsError(printResult);
            }
            printed++;
        }
        endJob({
            printed,
            warningCode: this.getResultWarningCode(printResult),
        });
        return {
            successful: true,
            warningCode: this.getResultWarningCode(printResult),
        };
    }

    async sendPrintingJob() {
        throw new Error("Not implemented");
    }

    openCashbox() {
        throw new Error("Not implemented");
    }

    /**
     * @param {DOMElement} canvas
     */
    processCanvas(canvas) {
        return canvas.toDataURL("image/jpeg").replace("data:image/jpeg;base64,", "");
    }

    getActionError() {
        return {
            successful: false,
            canRetry: true,
            message: {
                title: _t("Connection to IoT Box failed"),
                body: _t(
                    "Please ensure the IoT box is turned on and connected to the network before retrying.",
                ),
            },
        };
    }

    getOfflineError() {
        return {
            successful: false,
            canRetry: true,
            message: {
                title: _t("No Internet Connection"),
                body: _t(
                    "Please ensure you are connected to the internet before retrying.",
                ),
            },
        };
    }

    getResultsError(_printResult) {
        return {
            successful: false,
            canRetry: true,
            message: {
                title: _t("Connection to the printer failed"),
                body: _t(
                    "Your IoT box cannot find the printer, please ensure it is connected and turned on before retrying.",
                ),
            },
        };
    }

    getResultWarningCode(_printResult, options = {}) {
        return undefined;
    }
}
