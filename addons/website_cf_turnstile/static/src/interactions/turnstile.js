/** @odoo-module native */
import { renderToElement } from "@web/core/utils/render";
import { session } from "@web/session";

export class TurnStile {
    static turnstileURL = "https://challenges.cloudflare.com/turnstile/v0/api.js";

    constructor(action) {
        const cf = new URLSearchParams(window.location.search).get("cf");
        const mode = cf == "show" ? "always" : "interaction-only";
        const turnstileContainer = renderToElement(
            "website_cf_turnstile.turnstile_container",
            {
                action: action,
                appearance: mode,
                beforeInteractiveGlobalCallback: "turnstileBecomeVisible",
                errorGlobalCallback: "throwTurnstileErrorCode",
                executeGlobalCallback: "turnstileSuccess",
                sitekey: session.turnstile_site_key,
                style: "display: none;",
            },
        );

        globalThis.throwTurnstileErrorCode = function (code) {
            const error = new Error("Turnstile Error");
            error.code = code;
            throw error;
        };
        globalThis.turnstileSuccess = function () {
            const form =
                this.wrapper.closest("form") ||
                this.wrapper.parentElement.parentElement;
            const buttons = form.querySelectorAll(".cf_form_disabled");
            for (const button of buttons) {
                button.classList.remove("disabled", "cf_form_disabled");
            }
            form.querySelector("input.turnstile_captcha_valid").value = "done";
        };
        globalThis.turnstileBecomeVisible = function () {
            const turnstileContainer = this.wrapper.parentElement;
            turnstileContainer.style.display = "";
        };
        const script1El = document.createElement("script");

        const turnstileScript = renderToElement(
            "website_cf_turnstile.turnstile_remote_script",
            {
                remoteScriptUrl: !window.turnstile?.render
                    ? TurnStile.turnstileURL
                    : "",
            },
        );

        const inputValidation = document.createElement("input");
        inputValidation.style = "display: none;";
        inputValidation.className = "turnstile_captcha_valid";
        inputValidation.required = true;

        this.turnstileEl = turnstileContainer;
        this.script1El = script1El;
        this.script2El = turnstileScript;
        this.inputValidation = inputValidation;
    }

    /**
     * @param {HTMLElement} el
     */
    static clean(el) {
        const submitButtons = el.querySelectorAll(".cf_form_disabled");
        submitButtons.forEach((button) => {
            button.classList.remove("disabled", "cf_form_disabled");
        });
        const turnstileEls = el.querySelectorAll(".s_turnstile");
        turnstileEls.forEach((element) => element.remove());
    }

    static disableSubmit(submitButton) {
        if (
            !submitButton.classList.contains("disabled") &&
            !submitButton.classList.contains("no_auto_disable")
        ) {
            submitButton.classList.add("disabled", "cf_form_disabled");
        }
    }

    insertScripts(formEl) {
        formEl.appendChild(this.inputValidation);
        formEl.appendChild(this.script1El);
        if (!window.turnstile?.render) {
            formEl.appendChild(this.script2El);
        }
    }

    render() {
        if (
            window.turnstile?.render &&
            this.turnstileEl &&
            !this.turnstileEl.querySelector("iframe")
        ) {
            window.turnstile.render(this.turnstileEl);
            return true;
        }
        return false;
    }
}
