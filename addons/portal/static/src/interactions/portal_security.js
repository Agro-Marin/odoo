/** @odoo-module native */
import { InputConfirmationDialog } from "@portal/js/components/input_confirmation_dialog/input_confirmation_dialog";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { renderToMarkup } from "@web/core/utils/render";
import { Modal } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";
import { ConfirmationDialog } from "@web/ui/dialog";

export class IdentityCheckCancelled extends Error {
    constructor() {
        super("Identity check cancelled by the user");
        this.name = "IdentityCheckCancelled";
    }
}

export class PortalSecurity extends Interaction {
    static selector = ".o_portal_security_body";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _modal: () => document.querySelector(".modal#portal_deactivate_account_modal"),
    };
    dynamicContent = {
        ".o_portal_new_api_key": {
            "t-on-click.prevent": this.onNewApiKeyClick,
        },
        ".o_portal_remove_api_key": {
            "t-on-click.prevent": this.onRemoveApiKeyClick,
        },
        _modal: {
            "t-on-hide.bs.modal.withTarget": (event, currentTargetEl) => {
                for (const el of currentTargetEl.querySelectorAll(
                    ".alert, .invalid-feedback",
                )) {
                    el.remove();
                }
                for (const el of currentTargetEl.querySelectorAll(".is-invalid")) {
                    el.classList.remove("is-invalid");
                }
            },
        },
        "#portal_revoke_all_sessions_popup": {
            "t-on-click": this.onRevokeAllSessionsClick,
        },
    };

    setup() {
        const modalEl = document.querySelector(
            ".modal.show#portal_deactivate_account_modal",
        );
        if (modalEl) {
            modalEl.classList.remove("d-block");
            Modal.getOrCreateInstance(modalEl).show();
        }
    }

    /**
     * @param {Function} action
     */
    async guardedByIdentity(action) {
        try {
            return await action();
        } catch (error) {
            if (error instanceof IdentityCheckCancelled) {
                return undefined;
            }
            throw error;
        }
    }

    async onNewApiKeyClick() {
        return this.guardedByIdentity(() => this._createApiKey());
    }

    async _createApiKey() {
        await this.waitFor(
            handleCheckIdentity(
                this.waitFor(
                    this.services.orm.call("res.users", "api_key_wizard", [
                        user.userId,
                    ]),
                ),
                this.services.orm,
                this.services.dialog,
            ),
        );

        const { duration } = await this.waitFor(
            this.services.field.loadFields("res.users.apikeys.description", {
                fieldNames: ["duration"],
            }),
        );

        this.services.dialog.add(InputConfirmationDialog, {
            title: _t("New API Key"),
            body: renderToMarkup("portal.keydescription", {
                duration_selection: duration.selection.filter(
                    (option) => option[0] !== "-1",
                ),
            }),
            confirmLabel: _t("Confirm"),
            confirm: async ({ inputEl }) =>
                this.guardedByIdentity(async () => {
                    const formData = Object.fromEntries(
                        new FormData(inputEl.closest("form")),
                    );
                    const wizardId = await this.waitFor(
                        this.services.orm.create("res.users.apikeys.description", [
                            {
                                name: formData["description"],
                                duration: formData["duration"],
                            },
                        ]),
                    );
                    const res = await this.waitFor(
                        handleCheckIdentity(
                            this.waitFor(
                                this.services.orm.call(
                                    "res.users.apikeys.description",
                                    "make_key",
                                    [wizardId],
                                ),
                            ),
                            this.services.orm,
                            this.services.dialog,
                        ),
                    );

                    this.services.dialog.add(
                        ConfirmationDialog,
                        {
                            title: _t("API Key Ready"),
                            body: renderToMarkup("portal.keyshow", {
                                key: res.context.default_key,
                            }),
                            confirmLabel: _t("Close"),
                        },
                        {
                            onClose: () => {
                                window.location.reload();
                            },
                        },
                    );
                }),
        });
    }
    async onRemoveApiKeyClick(ev) {
        const keyId = parseInt(ev.currentTarget.dataset.id, 10);
        return this.guardedByIdentity(async () => {
            await this.waitFor(
                handleCheckIdentity(
                    this.waitFor(
                        this.services.orm.call("res.users.apikeys", "remove", [keyId]),
                    ),
                    this.services.orm,
                    this.services.dialog,
                ),
            );
            window.location.reload();
        });
    }
    async onRevokeAllSessionsClick() {
        return this.guardedByIdentity(async () => {
            await this.waitFor(
                handleCheckIdentity(
                    this.waitFor(
                        this.services.orm.call(
                            "res.users",
                            "action_revoke_all_devices",
                            [user.userId],
                        ),
                    ),
                    this.services.orm,
                    this.services.dialog,
                ),
            );
            window.location.reload();
            return true;
        });
    }
}

registry.category("public.interactions").add("portal.portal_security", PortalSecurity);

/**
 * @param {Promise} wrapped
 * @param {Function} ormService
 * @param {Function} dialogService
 * @returns {Promise}
 */
export async function handleCheckIdentity(wrapped, ormService, dialogService) {
    return wrapped.then(async (r) => {
        if (!(
            r &&
            r.type &&
            r.type === "ir.actions.act_window" &&
            r.res_model === "res.users.identitycheck"
        )) {
            return r;
        }
        const checkId = r.res_id;
        await ormService.write("res.users.identitycheck", [checkId], {
            auth_method: "password",
        });
        return new Promise((resolve, reject) => {
            let settled = false;
            dialogService.add(
                InputConfirmationDialog,
                {
                    title: _t("Security Control"),
                    body: renderToMarkup("portal.identitycheck"),
                    confirmLabel: _t("Confirm Password"),
                    confirm: async ({ inputEl }) => {
                        if (!inputEl.reportValidity()) {
                            inputEl.classList.add("is-invalid");
                            return false;
                        }
                        let result;
                        try {
                            result = await ormService.call(
                                "res.users.identitycheck",
                                "run_check",
                                [checkId],
                                { context: { password: inputEl.value } },
                            );
                        } catch {
                            inputEl.classList.add("is-invalid");
                            inputEl.setCustomValidity(_t("Check failed"));
                            inputEl.reportValidity();
                            return false;
                        }
                        settled = true;
                        resolve(result);
                        return true;
                    },
                    cancel: () => {},
                    onInput: ({ inputEl }) => {
                        inputEl.classList.remove("is-invalid");
                        inputEl.setCustomValidity("");
                    },
                },
                {
                    onClose: () => {
                        if (!settled) {
                            settled = true;
                            reject(new IdentityCheckCancelled());
                        }
                    },
                },
            );
        });
    });
}
