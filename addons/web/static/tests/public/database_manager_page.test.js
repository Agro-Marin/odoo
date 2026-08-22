// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import {
    generateMasterPassword,
    refreshDeleteConfirmation,
    setupDatabaseManager,
    showGeneratedMasterPassword,
    togglePasswordReveal,
} from "@web/public/database_manager_page";

describe.current.tags("headless");

/**
 * @param {string} html
 * @returns {HTMLElement}
 */
function page(html) {
    const fixture = /** @type {HTMLElement} */ (getFixture());
    fixture.innerHTML = html;
    return fixture;
}

function fakeModals() {
    /** @type {string[]} */
    const calls = [];
    return {
        calls,
        /** @param {Element} el */
        getModal: (el) => ({
            show: () => calls.push(`show:${el.className}`),
            hide: () => calls.push(`hide:${el.className}`),
        }),
    };
}

describe("generateMasterPassword", () => {
    test("is grouped, and drawn only from unambiguous characters", () => {
        for (let i = 0; i < 50; i++) {
            expect(generateMasterPassword()).toMatch(
                /^[abcdefghijkmnpqrstuvwxyz23456789]{4}-[abcdefghijkmnpqrstuvwxyz23456789]{4}-[abcdefghijkmnpqrstuvwxyz23456789]{4}$/,
            );
        }
    });

    test("never emits the character pairs that read alike", () => {
        const seen = new Set(
            Array.from({ length: 200 }, () => generateMasterPassword()).join(""),
        );
        for (const ambiguous of ["l", "1", "o", "0"]) {
            expect(seen.has(ambiguous)).toBe(false);
        }
    });

    test("differs from one call to the next", () => {
        const all = new Set(
            Array.from({ length: 100 }, () => generateMasterPassword()),
        );
        expect(all.size).toBe(100);
    });

    test("maps bytes without modulo bias", () => {
        /** @type {Record<string, number>} */
        const hits = {};
        for (let byte = 0; byte < 256; byte++) {
            const crypto = /** @type {any} */ ({
                getRandomValues: (/** @type {Uint8Array} */ a) => a.fill(byte),
            });
            const char = generateMasterPassword(crypto)[0];
            hits[char] = (hits[char] || 0) + 1;
        }
        expect(Object.keys(hits)).toHaveLength(32);
        expect(new Set(Object.values(hits))).toEqual(new Set([8]));
    });
});

describe("showGeneratedMasterPassword", () => {
    test("shows the same secret everywhere the page offers it", () => {
        const root = page(`
            <strong class="generated_master_pwd"></strong>
            <strong class="generated_master_pwd"></strong>
            <input class="generated_master_pwd_input"/>`);
        showGeneratedMasterPassword(root, "abcd-efgh-ijkl");
        for (const el of root.querySelectorAll(".generated_master_pwd")) {
            expect(/** @type {HTMLElement} */ (el).innerText).toBe("abcd-efgh-ijkl");
        }
        const input = /** @type {HTMLInputElement} */ (
            queryOne(".generated_master_pwd_input")
        );
        expect(input.value).toBe("abcd-efgh-ijkl");
        expect(input).toHaveAttribute("autocomplete", "new-password");
    });
});

describe("togglePasswordReveal", () => {
    const GROUP = `
        <div class="input-group">
            <input type="password" class="form-control"/>
            <button class="o_little_eye" aria-pressed="false" aria-label="Show password">
                <i class="fa-regular fa-eye"></i>
            </button>
        </div>`;

    test("keeps the same aria contract as the ShowPassword interaction", () => {
        page(GROUP);
        const toggle = queryOne(".o_little_eye");
        const field = /** @type {HTMLInputElement} */ (queryOne(".form-control"));

        togglePasswordReveal(toggle);
        expect(field.type).toBe("text");
        expect(toggle).toHaveAttribute("aria-pressed", "true");
        expect(toggle).toHaveAttribute("aria-label", "Hide password");
        expect(queryOne(".o_little_eye i")).toHaveClass("fa-eye-slash");

        togglePasswordReveal(toggle);
        expect(field.type).toBe("password");
        expect(toggle).toHaveAttribute("aria-pressed", "false");
        expect(toggle).toHaveAttribute("aria-label", "Show password");
        expect(queryOne(".o_little_eye i")).toHaveClass("fa-eye");
    });

    test("does nothing when the group holds no field", () => {
        page(`<div class="input-group"><button class="o_little_eye"></button></div>`);
        expect(() => togglePasswordReveal(queryOne(".o_little_eye"))).not.toThrow();
    });
});

describe("refreshDeleteConfirmation", () => {
    const MODAL = `
        <div class="modal o_database_delete">
            <input id="dbname_delete" value="alpha_db"/>
            <input id="dbname_delete_confirm" value=""/>
        </div>`;

    /** @returns {HTMLInputElement} */
    const confirmEl = () => /** @type {any} */ (queryOne("#dbname_delete_confirm"));

    test("refuses an empty confirmation", () => {
        page(MODAL);
        refreshDeleteConfirmation(queryOne(".modal"));
        expect(confirmEl().validationMessage).toBe(
            "Please type the database name to confirm deletion.",
        );
    });

    test("refuses a name that does not match, to the character", () => {
        page(MODAL);
        for (const typed of ["beta_db", "alpha_d", "alpha_db ", "ALPHA_DB"]) {
            confirmEl().value = typed;
            refreshDeleteConfirmation(queryOne(".modal"));
            expect(confirmEl().validationMessage).toBe("Database name does not match.");
        }
    });

    test("accepts the exact name", () => {
        page(MODAL);
        confirmEl().value = "alpha_db";
        refreshDeleteConfirmation(queryOne(".modal"));
        expect(confirmEl().validationMessage).toBe("");
    });
});

describe("setupDatabaseManager", () => {
    const MANAGER = `
        <div class="list-group">
            <button class="o_database_action" data-db="alpha_db"
                    data-bs-target=".o_database_delete">Delete</button>
            <button class="o_database_action" data-db="beta_db"
                    data-bs-target=".o_database_delete">Delete</button>
        </div>
        <div class="modal o_database_delete">
            <form>
                <input id="dbname_delete" name="name" value=""/>
                <input id="dbname_delete_confirm" value=""/>
            </form>
        </div>
        <div class="modal o_database_backup">
            <form><input name="name" value="alpha_db"/></form>
        </div>
        <select id="backup_format"><option value="zip">zip</option><option value="dump">dump</option></select>
        <div id="filestore_div"></div>`;

    /**
     * @param {string} [html]
     * @returns {{ root: HTMLElement, modals: ReturnType<typeof fakeModals>, undo: () => void }}
     */
    function start(html = MANAGER) {
        const root = page(html);
        root.addEventListener("submit", (ev) => ev.preventDefault(), true);
        const modals = fakeModals();
        const undo = setupDatabaseManager(root, { getModal: modals.getModal });
        return { root, modals, undo };
    }

    test("a database action prefills its modal and opens it", async () => {
        const { modals } = start();
        await click(".o_database_action[data-db='alpha_db']");
        expect(/** @type {HTMLInputElement} */ (queryOne("#dbname_delete")).value).toBe(
            "alpha_db",
        );
        expect(modals.calls).toEqual(["show:modal o_database_delete"]);
    });

    test("reopening for another database revokes the previous confirmation", async () => {
        start();
        await click(".o_database_action[data-db='alpha_db']");
        const confirmEl = /** @type {HTMLInputElement} */ (
            queryOne("#dbname_delete_confirm")
        );
        confirmEl.value = "alpha_db";
        confirmEl.dispatchEvent(new Event("input", { bubbles: true }));
        expect(confirmEl.validationMessage).toBe("");

        await click(".o_database_action[data-db='beta_db']");
        expect(/** @type {HTMLInputElement} */ (queryOne("#dbname_delete")).value).toBe(
            "beta_db",
        );
        expect(confirmEl.value).toBe("");
        expect(confirmEl.validationMessage).toBe(
            "Please type the database name to confirm deletion.",
        );
    });

    test("typing re-evaluates the confirmation live", async () => {
        start();
        await click(".o_database_action[data-db='alpha_db']");
        const confirmEl = /** @type {HTMLInputElement} */ (
            queryOne("#dbname_delete_confirm")
        );
        for (const [typed, message] of [
            ["alph", "Database name does not match."],
            ["alpha_db", ""],
            ["alpha_d", "Database name does not match."],
            ["", "Please type the database name to confirm deletion."],
        ]) {
            confirmEl.value = typed;
            confirmEl.dispatchEvent(new Event("input", { bubbles: true }));
            expect(confirmEl.validationMessage).toBe(message);
        }
    });

    test("an invalid form neither hides the modal nor announces a backup", () => {
        const { root, modals } = start();
        const formEl = queryOne(".o_database_delete form");
        queryOne("#dbname_delete_confirm").setAttribute("required", "required");
        formEl.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        expect(modals.calls).toEqual([]);
        expect(root.querySelector(".alert-backup-long")).toBe(null);
    });

    test("a valid backup submit hides the modal and warns once, not twice", () => {
        const { root, modals } = start();
        const formEl = queryOne(".o_database_backup form");
        for (let i = 0; i < 3; i++) {
            formEl.dispatchEvent(
                new Event("submit", { bubbles: true, cancelable: true }),
            );
        }
        expect(modals.calls).toEqual([
            "hide:modal o_database_backup",
            "hide:modal o_database_backup",
            "hide:modal o_database_backup",
        ]);
        expect(root.querySelectorAll(".alert-backup-long")).toHaveLength(1);
    });

    test("the filestore option follows the backup format", () => {
        start();
        const selectEl = /** @type {HTMLSelectElement} */ (queryOne("#backup_format"));
        expect("#filestore_div").not.toHaveClass("d-none");
        selectEl.value = "dump";
        selectEl.dispatchEvent(new Event("change", { bubbles: true }));
        expect("#filestore_div").toHaveClass("d-none");
        selectEl.value = "zip";
        selectEl.dispatchEvent(new Event("change", { bubbles: true }));
        expect("#filestore_div").not.toHaveClass("d-none");
    });

    test("a generated master password is offered as soon as the page is wired", () => {
        const { root } = start(
            `<strong class="generated_master_pwd"></strong>
             <input class="generated_master_pwd_input"/>`,
        );
        const shown = /** @type {HTMLElement} */ (
            root.querySelector(".generated_master_pwd")
        ).innerText;
        expect(shown).toMatch(/^\w{4}-\w{4}-\w{4}$/);
        expect(
            /** @type {HTMLInputElement} */ (
                root.querySelector(".generated_master_pwd_input")
            ).value,
        ).toBe(shown);
    });

    test("the undo takes every listener back out", async () => {
        const { modals, undo } = start();
        undo();
        await click(".o_database_action[data-db='alpha_db']");
        expect(modals.calls).toEqual([]);
        expect(/** @type {HTMLInputElement} */ (queryOne("#dbname_delete")).value).toBe(
            "",
        );
    });
});
