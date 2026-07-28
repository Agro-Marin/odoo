// @ts-check
/** @odoo-module native */

/** @module @web/public/database_manager - DOM event handlers for the database manager page (eye toggle, modals, master password) */

// @ts-ignore — bootstrap is exposed at runtime by the asset bundle, but its types are not part of this fork's npm tree
import { Modal } from "bootstrap";

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    document.documentElement.setAttribute(
        "data-bs-theme",
        e.matches ? "dark" : "light",
    );
});

document.addEventListener("DOMContentLoaded", function () {
    // "click" and not "mousedown": the toggle is a button, and a keyboard user
    // activating it with Enter or Space never produces a mousedown
    document.body.addEventListener("click", function (ev) {
        const target = /** @type {HTMLElement} */ (ev.target);
        const eyeToggle = target.closest(".o_little_eye");
        if (!eyeToggle) {
            return;
        }
        const formControl = /** @type {HTMLInputElement | null} */ (
            eyeToggle.closest(".input-group")?.querySelector(".form-control")
        );
        if (!formControl) {
            return;
        }
        const isShown = formControl.type === "password";
        formControl.type = isShown ? "text" : "password";
        eyeToggle.setAttribute("aria-pressed", String(isShown));
        eyeToggle.setAttribute(
            "aria-label",
            isShown ? "Hide password" : "Show password",
        );
    });

    document.body.addEventListener("click", function (ev) {
        const target = /** @type {HTMLElement} */ (ev.target);
        const action = target.closest(".o_database_action");
        if (action) {
            ev.preventDefault();
            const db = action.getAttribute("data-db");
            const bsTarget = action.getAttribute("data-bs-target");
            const modalEl = bsTarget && document.querySelector(bsTarget);
            if (!modalEl) {
                return;
            }
            const inputName = /** @type {HTMLInputElement | null} */ (
                modalEl.querySelector("input[name=name]")
            );
            if (inputName && db) {
                inputName.value = db;
            }
            Modal.getOrCreateInstance(modalEl).show();
        }
    });

    const deleteModal = document.querySelector(".o_database_delete");
    if (deleteModal) {
        deleteModal.addEventListener("show.bs.modal", function () {
            const confirmInput = /** @type {HTMLInputElement | null} */ (
                document.getElementById("dbname_delete_confirm")
            );
            if (confirmInput) {
                confirmInput.value = "";
                confirmInput.setCustomValidity(
                    "Please type the database name to confirm deletion.",
                );
            }
        });
        deleteModal.addEventListener("input", function (ev) {
            const target = /** @type {HTMLElement} */ (ev.target);
            if (target.id === "dbname_delete_confirm") {
                const confirmInput = /** @type {HTMLInputElement} */ (target);
                const nameInput = /** @type {HTMLInputElement | null} */ (
                    document.getElementById("dbname_delete")
                );
                if (nameInput && confirmInput.value === nameInput.value) {
                    confirmInput.setCustomValidity("");
                } else {
                    confirmInput.setCustomValidity("Database name does not match.");
                }
            }
        });
    }

    document.getElementById("backup_format")?.addEventListener("change", function (ev) {
        ev.preventDefault();
        const no_filestore_flag = document.getElementById("filestore_div");
        if (no_filestore_flag) {
            if (/** @type {HTMLInputElement} */ (ev.target).value !== "zip") {
                no_filestore_flag.classList.add("d-none");
            } else {
                no_filestore_flag.classList.remove("d-none");
            }
        }
    });

    const modals = document.querySelectorAll(".modal");
    for (const modalEl of modals) {
        modalEl.addEventListener("submit", function (ev) {
            const form = /** @type {Element} */ (ev.target).closest("form");
            if (form && !form.checkValidity?.()) {
                return;
            }
            const modal = Modal.getOrCreateInstance(modalEl);
            modal.hide();
            if (modalEl.classList.contains("o_database_backup")) {
                if (!document.querySelector(".alert-backup-long")) {
                    const listGroup = document.querySelector(".list-group");
                    if (listGroup) {
                        const alert = document.createElement("div");
                        alert.className = "alert alert-info alert-backup-long";
                        alert.textContent =
                            "The backup is on its way; if your database has a lot of data, you may want to go grab a coffee...";
                        listGroup.before(alert);
                    }
                }
            }
        });
    }
    const charset = "abcdefghijkmnpqrstuvwxyz23456789";
    const bytes = crypto.getRandomValues(new Uint8Array(12));
    let password = "";
    for (let i = 0; i < 12; i++) {
        password += charset[bytes[i] % charset.length];
        if (i === 3 || i === 7) {
            password += "-";
        }
    }
    const masterPwds = document.querySelectorAll(".generated_master_pwd");
    for (const pwdElement of masterPwds) {
        /** @type {HTMLElement} */ (pwdElement).innerText = password;
    }
    const masterPwdInputs = document.querySelectorAll(".generated_master_pwd_input");
    for (const pwdInput of masterPwdInputs) {
        /** @type {HTMLInputElement} */ (pwdInput).value = password;
        pwdInput.setAttribute("autocomplete", "new-password");
    }
});
