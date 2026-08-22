import { describe, expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

describe("printer_service.js", () => {
    test("print should work whith printer in hardware_proxy", async () => {
        const store = await setupPosEnv();
        const printerService = store.env.services.printer;
        printerService.renderer = {
            toHtml: async () => document.createElement("div"),
            whenMounted: ({ callback, el }) => callback(el),
        };
        const mockPrinter = {
            printReceipt: async () => ({ successful: true }),
        };
        store.env.services.hardware_proxy.printer = mockPrinter;
        const originalConsoleLog = console.log;
        const consoleLogCalls = [];
        console.log = (...args) => {
            consoleLogCalls.push(args);
        };
        try {
            const lenBefore = consoleLogCalls.length;
            await printerService.print(() => {}, {}, {});
            const lenAfter = consoleLogCalls.length;
            expect(lenAfter).toBe(lenBefore);
        } finally {
            console.log = originalConsoleLog;
        }
    });
});
