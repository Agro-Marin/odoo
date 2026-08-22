// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv, onRpc } from "@web/../tests/web_test_helpers";
import { demoDataService } from "@web/views/settings/widgets/demo_data_service";
import { userInviteService } from "@web/views/settings/widgets/user_invite_service";

describe.current.tags("headless");

describe("demo_data service", () => {
    test("a failed probe is not cached", async () => {
        await makeMockEnv();
        let calls = 0;
        let failNext = true;
        onRpc("/base_setup/demo_active", () => {
            calls++;
            if (failNext) {
                failNext = false;
                throw new Error("boom");
            }
            return true;
        });

        const service = await demoDataService.start();
        await expect(service.isDemoDataActive()).rejects.toThrow();
        expect(calls).toBe(1);

        expect(await service.isDemoDataActive()).toBe(true);
        expect(calls).toBe(2);
    });

    test("a successful probe is cached", async () => {
        await makeMockEnv();
        let calls = 0;
        onRpc("/base_setup/demo_active", () => {
            calls++;
            return true;
        });

        const service = await demoDataService.start();
        expect(await service.isDemoDataActive()).toBe(true);
        expect(await service.isDemoDataActive()).toBe(true);
        expect(calls).toBe(1);
    });
});

describe("user_invite service", () => {
    test("a failed fetch is not cached", async () => {
        await makeMockEnv();
        let calls = 0;
        let failNext = true;
        onRpc("/base_setup/data", () => {
            calls++;
            if (failNext) {
                failNext = false;
                throw new Error("boom");
            }
            return { resends: 1 };
        });

        const service = await userInviteService.start();
        await expect(service.fetchData()).rejects.toThrow();
        expect(calls).toBe(1);

        expect(await service.fetchData()).toEqual({ resends: 1 });
        expect(calls).toBe(2);
    });

    test("a successful fetch is cached until reload is asked for", async () => {
        await makeMockEnv();
        let calls = 0;
        onRpc("/base_setup/data", () => {
            calls++;
            return { resends: calls };
        });

        const service = await userInviteService.start();
        expect(await service.fetchData()).toEqual({ resends: 1 });
        expect(await service.fetchData()).toEqual({ resends: 1 });
        expect(calls).toBe(1);

        expect(await service.fetchData(true)).toEqual({ resends: 2 });
        expect(calls).toBe(2);
    });
});
