import { expect, test } from "@odoo/hoot";
import { click, edit, queryFirst } from "@odoo/hoot-dom";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { GenerateDialog, parseNumberInput } from "@stock/widgets/generate_serial";
import {
    makeDialogMockEnv,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { localization } from "@web/core/l10n/localization";

function makeMove({ tracking = "serial" } = {}) {
    const applied = [];
    const move = {
        context: {},
        data: {
            has_tracking: tracking,
            product_qty: 2,
            product_uom_qty: 2,
            quantity: 0,
            product_id: { id: 1, display_name: "Product" },
            location_id: { id: 2 },
            location_dest_id: { id: 3 },
            product_uom_id: { id: 4, display_name: "Units" },
            move_line_ids: {
                currentIds: [51, 52],
                applyCommands: (commands) => applied.push(commands),
            },
        },
    };
    return { move, applied };
}

async function mountDialog(move, mode = "generate") {
    onRpc("has_group", () => false);
    const env = await makeDialogMockEnv();
    await mountWithCleanup(GenerateDialog, {
        env,
        props: { mode, move, close: () => expect.step("close") },
    });
}

test("empty serial submit is rejected before any delete command is built", async () => {
    const { move, applied } = makeMove();
    onRpc("action_generate_lot_line_vals", () => {
        expect.step("generate-rpc");
        return [];
    });
    await mountDialog(move);
    await click(".modal-footer button.btn-primary");
    await animationFrame();
    expect.verifySteps([]);
    expect(applied.length).toBe(0);
    expect(".alert").toHaveCount(1);
});

test("non-positive serial count is rejected", async () => {
    const { move, applied } = makeMove();
    onRpc("action_generate_lot_line_vals", () => {
        expect.step("generate-rpc");
        return [];
    });
    await mountDialog(move);
    await click("#generate_next_serial");
    await edit("SN0001");
    await click("#generate_next_serial_count");
    await edit("0");
    await click(".modal-footer button.btn-primary");
    await animationFrame();
    expect.verifySteps([]);
    expect(applied.length).toBe(0);
    expect(".alert").toHaveCount(1);
});

test("double-click on Generate emits a single command batch", async () => {
    const { move, applied } = makeMove();
    const rpcDone = new Deferred();
    onRpc("action_generate_lot_line_vals", async () => {
        expect.step("generate-rpc");
        await rpcDone;
        return [{ lot_name: "SN0001" }, { lot_name: "SN0002" }];
    });
    await mountDialog(move);
    await click("#generate_next_serial");
    await edit("SN0001");
    const generateButton = queryFirst(".modal-footer button.btn-primary");
    await click(generateButton);
    await animationFrame();
    expect(generateButton).toHaveAttribute("disabled");
    await click(generateButton);
    await animationFrame();
    rpcDone.resolve();
    await animationFrame();
    expect.verifySteps(["generate-rpc", "close"]);
    expect(applied.length).toBe(1);
    const commands = applied[0];
    expect(commands.length).toBe(4);
    expect(commands.slice(0, 2).map((c) => c[0] === 2 && c[1])).toEqual([51, 52]);
});

test("a fractional serial count is refused in words, not thrown", async () => {
    const { move, applied } = makeMove({ tracking: "serial" });
    onRpc("action_generate_lot_line_vals", () => {
        expect.step("generate-rpc");
        return [{ lot_name: "SN0001" }];
    });
    await mountDialog(move);
    patchWithCleanup(localization, { decimalPoint: ",", thousandsSep: " " });
    await click("#generate_next_serial");
    await edit("SN0001");
    await click("#generate_next_serial_count");
    await edit("2,5");
    await click(".modal-footer button.btn-primary");
    await animationFrame();
    expect.verifySteps([]);
    expect(applied.length).toBe(0);
    expect(".alert").toHaveText(/whole number/);
});

test("a fractional quantity per lot is read in the user's locale", async () => {
    const { move } = makeMove({ tracking: "lot" });
    onRpc("action_generate_lot_line_vals", ({ args }) => {
        expect.step(`count=${args[3]} qty=${args[0].default_quantity}`);
        return [{ lot_name: "LOT0001" }];
    });
    await mountDialog(move);
    patchWithCleanup(localization, { decimalPoint: ",", thousandsSep: " " });
    await click("#generate_next_serial");
    await edit("LOT0001");
    await click("#generate_next_serial_count");
    await edit("2,5");
    await click("#generate_total_received");
    await edit("7,5");
    await click(".modal-footer button.btn-primary");
    await animationFrame();
    expect.verifySteps(["count=2.5 qty=7.5", "close"]);
});

test("parseNumberInput reads the user's locale and reports refusals", async () => {
    patchWithCleanup(localization, { decimalPoint: ",", thousandsSep: " " });
    expect(parseNumberInput("2,5")).toEqual({ value: 2.5, error: null });
    expect(parseNumberInput("")).toEqual({ value: 0, error: null });
    expect(parseNumberInput("12", { integer: true })).toEqual({
        value: 12,
        error: null,
    });
    expect(parseNumberInput("2,5", { integer: true }).value).toBe(0);
    expect(parseNumberInput("2,5", { integer: true }).error).toMatch(/whole number/);
    expect(parseNumberInput("abc").error).toMatch(/not a number/);
});
