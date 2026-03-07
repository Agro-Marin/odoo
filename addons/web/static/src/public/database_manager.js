// @ts-check

/** @module @web/public/database_manager - DOM event handlers for the database manager page (eye toggle, modals, master password) */

// Keep theme in sync if the user changes OS preference while the page is open
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    document.documentElement.setAttribute("data-bs-theme", e.matches ? "dark" : "light");
});

document.addEventListener("DOMContentLoaded", function () {
    // Little eye — use closest() so clicks on the nested <i> icon are also caught
    document.body.addEventListener("mousedown", function (ev) {
        const target = /** @type {HTMLElement} */ (ev.target);
        const eyeToggle = target.closest(".o_little_eye");
        if (eyeToggle) {
            const closestInputGroup = eyeToggle.closest(".input-group");
            if (closestInputGroup) {
                const formControl = /** @type {HTMLInputElement | null} */ (
                    closestInputGroup.querySelector(".form-control")
                );
                if (formControl) {
                    formControl.type =
                        formControl.type === "text" ? "password" : "text";
                }
            }
        }
    });

    // db modal
    document.body.addEventListener("click", function (ev) {
        const target = /** @type {HTMLElement} */ (ev.target);
        if (target.classList.contains("o_database_action")) {
            ev.preventDefault();
            const db = target.getAttribute("data-db");
            const bsTarget = target.getAttribute("data-bs-target");
            const modal = Modal.getOrCreateInstance(document.querySelector(bsTarget));
            const inputName = modal._element.querySelector("input[name=name]");
            if (inputName) {
                inputName.value = db;
            }
            modal.show();
        }
    });

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

    // close modal on submit
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
                        listGroup.parentNode.insertBefore(alert, listGroup);
                    }
                }
            }
        });
    }
    // Generate a cryptographically random master password suggestion.
    // Charset: 32 chars (l/o/0/1 removed to avoid confusion).
    // Uint8Array values are 0-255; 256 / 32 = 8 exactly → zero modulo bias.
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
