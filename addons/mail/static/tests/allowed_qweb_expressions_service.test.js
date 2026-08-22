// @ts-check

import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { onRpc } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("the allowlist is fetched once per model and shared by every caller", async () => {
    onRpc("res.partner", "mail_allowed_qweb_expressions", () => {
        expect.step("res.partner");
        return ["object.name"];
    });
    onRpc("res.users", "mail_allowed_qweb_expressions", () => {
        expect.step("res.users");
        return ["object.login"];
    });

    const env = await start();
    const getAllowed = env.services["allowed_qweb_expressions"];

    const [a, b] = await Promise.all([
        getAllowed("res.partner"),
        getAllowed("res.partner"),
    ]);
    expect(a).toEqual(["object.name"]);
    expect(b).toEqual(["object.name"]);
    // a second read of the same model must not reach the server again
    expect(await getAllowed("res.partner")).toEqual(["object.name"]);
    expect.verifySteps(["res.partner"]);

    // a different model is a different entry
    expect(await getAllowed("res.users")).toEqual(["object.login"]);
    expect.verifySteps(["res.users"]);
});

test("a failed fetch is not cached, so the next caller retries", async () => {
    let calls = 0;
    onRpc("res.partner", "mail_allowed_qweb_expressions", () => {
        calls++;
        if (calls === 1) {
            throw new Error("boom");
        }
        return ["object.name"];
    });

    const env = await start();
    const getAllowed = env.services["allowed_qweb_expressions"];

    await expect(getAllowed("res.partner")).rejects.toThrow();
    expect(await getAllowed("res.partner")).toEqual(["object.name"]);
    expect(calls).toBe(2);
});
