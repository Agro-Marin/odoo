import { expect, test } from "@odoo/hoot";
import { click, edit, queryFirst } from "@odoo/hoot-dom";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { GenerateDialog } from "@stock/widgets/generate_serial";
import {
    makeDialogMockEnv,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";

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

async function mountDialog(move) {
    onRpc("has_group", () => false);
    const env = await makeDialogMockEnv();
    await mountWithCleanup(GenerateDialog, {
        env,
        props: {
            mode: "generate",
            move,
            close: () => expect.step("close"),
        },
    });
}

test("empty serial submit is rejected before any delete command is built", async () => {
    const { move, applied } = makeMove();
    onRpc("action_generate_lot_line_vals", () => {
        expect.step("generate-rpc");
        return [];
    });
    await mountDialog(move);
    // First serial number left empty: submitting must not fire the RPC nor
    // touch the existing lines (whose deletion is queued before the creates).
    await click(".modal-footer button.btn-primary");
    await animationFrame();
    expect.verifySteps([]);
    expect(applied.length).toBe(0);
});

test("non-positive serial count is rejected", async () => {
    const { move, applied } = makeMove();
    onRpc("action_generate_lot_line_vals", () => {
        expect.step("generate-rpc");
        return [];
    });
    await mountDialog(move);
    await click("#next_serial_0");
    await edit("SN0001");
    await click("#next_serial_count_0");
    await edit("0");
    await click(".modal-footer button.btn-primary");
    await animationFrame();
    expect.verifySteps([]);
    expect(applied.length).toBe(0);
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
    await click("#next_serial_0");
    await edit("SN0001");
    const generateButton = queryFirst(".modal-footer button.btn-primary");
    await click(generateButton);
    await animationFrame();
    // In flight: the footer button is disabled and a second click is inert.
    expect(generateButton).toHaveAttribute("disabled");
    await click(generateButton);
    await animationFrame();
    rpcDone.resolve();
    await animationFrame();
    expect.verifySteps(["generate-rpc", "close"]);
    expect(applied.length).toBe(1);
    // One batch: the 2 deletes of the existing lines ("keep current lines"
    // unchecked) followed by the 2 creates from the server values.
    const commands = applied[0];
    expect(commands.length).toBe(4);
    expect(commands.slice(0, 2).map((c) => c[0] === 2 && c[1])).toEqual([51, 52]);
});
