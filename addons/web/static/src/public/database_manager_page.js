// @ts-check
/** @odoo-module native */

/**
 * @typedef {{ show: () => void, hide: () => void }} ModalHandle
 * @typedef {(el: Element) => ModalHandle} GetModal
 */

const PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789";
const PASSWORD_LENGTH = 12;
const PASSWORD_GROUP = 4;

/**
 * @param {Crypto} [crypto]
 * @returns {string}
 */
export function generateMasterPassword(crypto = globalThis.crypto) {
    const bytes = crypto.getRandomValues(new Uint8Array(PASSWORD_LENGTH));
    let password = "";
    for (let i = 0; i < PASSWORD_LENGTH; i++) {
        if (i && i % PASSWORD_GROUP === 0) {
            password += "-";
        }
        password += PASSWORD_ALPHABET[bytes[i] % PASSWORD_ALPHABET.length];
    }
    return password;
}

/**
 * @param {ParentNode} root
 * @param {string} password
 * @returns {void}
 */
export function showGeneratedMasterPassword(root, password) {
    for (const el of root.querySelectorAll(".generated_master_pwd")) {
        /** @type {HTMLElement} */ (el).innerText = password;
    }
    for (const el of root.querySelectorAll(".generated_master_pwd_input")) {
        /** @type {HTMLInputElement} */ (el).value = password;
        el.setAttribute("autocomplete", "new-password");
    }
}

/**
 * @param {Window} [view]
 * @returns {() => void}
 */
export function followColorScheme(view = window) {
    const query = view.matchMedia("(prefers-color-scheme: dark)");
    /** @param {MediaQueryListEvent} ev */
    const apply = (ev) =>
        view.document.documentElement.setAttribute(
            "data-bs-theme",
            ev.matches ? "dark" : "light",
        );
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
}

/**
 * @param {Element} toggleEl
 * @returns {void}
 */
export function togglePasswordReveal(toggleEl) {
    const fieldEl = /** @type {HTMLInputElement | null} */ (
        toggleEl.closest(".input-group")?.querySelector(".form-control")
    );
    if (!fieldEl) {
        return;
    }
    const reveal = fieldEl.type === "password";
    fieldEl.type = reveal ? "text" : "password";
    toggleEl.setAttribute("aria-pressed", String(reveal));
    toggleEl.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
    const iconEl = toggleEl.querySelector(".fa-eye, .fa-eye-slash");
    iconEl?.classList.toggle("fa-eye", !reveal);
    iconEl?.classList.toggle("fa-eye-slash", reveal);
}

/**
 * @param {Element} modalEl
 * @returns {void}
 */
export function refreshDeleteConfirmation(modalEl) {
    const confirmEl = /** @type {HTMLInputElement | null} */ (
        modalEl.querySelector("#dbname_delete_confirm")
    );
    const nameEl = /** @type {HTMLInputElement | null} */ (
        modalEl.querySelector("#dbname_delete")
    );
    if (!confirmEl) {
        return;
    }
    confirmEl.setCustomValidity(
        !confirmEl.value
            ? "Please type the database name to confirm deletion."
            : nameEl && confirmEl.value === nameEl.value
              ? ""
              : "Database name does not match.",
    );
}

/**
 * @param {Element} rootEl
 * @param {GetModal} getModal
 * @returns {(ev: Event) => void}
 */
function makeClickHandler(rootEl, getModal) {
    return (ev) => {
        const targetEl = /** @type {Element} */ (ev.target);
        const toggleEl = targetEl.closest?.(".o_little_eye");
        if (toggleEl) {
            togglePasswordReveal(toggleEl);
            return;
        }
        const actionEl = targetEl.closest?.(".o_database_action");
        if (!actionEl) {
            return;
        }
        ev.preventDefault();
        const selector = actionEl.getAttribute("data-bs-target");
        const modalEl = selector && rootEl.querySelector(selector);
        if (!modalEl) {
            return;
        }
        const db = actionEl.getAttribute("data-db");
        const nameEl = /** @type {HTMLInputElement | null} */ (
            modalEl.querySelector("input[name=name]")
        );
        if (nameEl && db) {
            nameEl.value = db;
        }
        const confirmEl = /** @type {HTMLInputElement | null} */ (
            modalEl.querySelector("#dbname_delete_confirm")
        );
        if (confirmEl) {
            confirmEl.value = "";
            refreshDeleteConfirmation(modalEl);
        }
        getModal(modalEl).show();
    };
}

const BACKUP_DELAY_NOTICE =
    "The backup is on its way; if your database has a lot of data, you may want to go grab a coffee...";

/**
 * @param {Element} rootEl
 * @param {{ getModal: GetModal, view?: Window }} deps
 * @returns {() => void}
 */
export function setupDatabaseManager(rootEl, { getModal, view = window }) {
    /** @type {Array<() => void>} */
    const cleanups = [followColorScheme(view)];
    /**
     * @param {EventTarget} el
     * @param {string} type
     * @param {EventListener} handler
     */
    const listen = (el, type, handler) => {
        el.addEventListener(type, handler);
        cleanups.push(() => el.removeEventListener(type, handler));
    };

    listen(rootEl, "click", makeClickHandler(rootEl, getModal));

    listen(rootEl, "input", (ev) => {
        const el = /** @type {Element} */ (ev.target);
        if (el.id === "dbname_delete_confirm") {
            const modalEl = el.closest(".modal");
            if (modalEl) {
                refreshDeleteConfirmation(modalEl);
            }
        }
    });

    listen(rootEl, "change", (ev) => {
        const el = /** @type {HTMLInputElement} */ (ev.target);
        if (el.id !== "backup_format") {
            return;
        }
        rootEl
            .querySelector("#filestore_div")
            ?.classList.toggle("d-none", el.value !== "zip");
    });

    listen(rootEl, "submit", (ev) => {
        const formEl = /** @type {Element} */ (ev.target).closest("form");
        const modalEl = formEl?.closest(".modal");
        if (!modalEl || !formEl?.checkValidity?.()) {
            return;
        }
        getModal(modalEl).hide();
        if (
            modalEl.classList.contains("o_database_backup") &&
            !rootEl.querySelector(".alert-backup-long")
        ) {
            const listEl = rootEl.querySelector(".list-group");
            if (listEl) {
                const alertEl = view.document.createElement("div");
                alertEl.className = "alert alert-info alert-backup-long";
                alertEl.textContent = BACKUP_DELAY_NOTICE;
                listEl.before(alertEl);
            }
        }
    });

    showGeneratedMasterPassword(rootEl, generateMasterPassword());

    return () => {
        for (const cleanup of cleanups) {
            cleanup();
        }
    };
}
