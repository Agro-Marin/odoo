/** @odoo-module native */
import { scrollTo } from "@html_builder/utils/scrolling";
import { _t } from "@web/core/translation";
import { post } from "@web/core/network";
import { registry } from "@web/core/registry";
import { renderToElement } from "@web/core/utils/render";
import { Interaction } from "@web/public/interaction";

export class WebsiteEventTrackProposalForm extends Interaction {
    static selector = ".o_website_event_track_proposal_form";

    dynamicContent = {
        ".o_wetrack_add_contact_information_checkbox": {
            "t-on-click": this.onAdvancedContactToggle,
        },
        "input[name='partner_name']": { "t-on-input": this.onPartnerNameInput },
        ".o_wetrack_proposal_submit_button": {
            "t-on-click.prevent.stop": this.onProposalFormSubmit,
        },
        ".o_wetrack_contact_information": {
            "t-att-class": () => ({
                "d-none": !this.useAdvancedContact,
                o_wetrack_no_contact_mean_error: !this.hasContactMean,
            }),
        },
        ".o_wetrack_contact_mean": {
            "t-att-class": () => ({ "is-invalid": !this.hasContactMean }),
        },
        ".o_wetrack_contact_name_input": {
            "t-att-required": () => this.useAdvancedContact,
        },
        ".o_wetrack_proposal_error_section": {
            "t-att-class": () => ({ "d-none": !this.formErrors.length }),
        },
    };

    setup() {
        this.useAdvancedContact = false;
        this.hasContactMean = true;
        this.formErrors = [];
    }

    /**
     * @returns {Boolean}
     */
    isFormValid() {
        this.formErrors = [];

        this.el
            .querySelectorAll(".form-control:not(.o_wetrack_select_tags)")
            .forEach((formControl) => {
                const isValid = formControl.checkValidity();
                formControl.classList.toggle("o_wetrack_input_error", !isValid);
                formControl.classList.toggle("is-invalid", !isValid);
                if (!isValid) {
                    this.formErrors.push("invalidFormInputs");
                }
            });

        if (this.useAdvancedContact) {
            const phoneInput = this.el.querySelector(".o_wetrack_contact_phone_input");
            const emailInput = this.el.querySelector(".o_wetrack_contact_email_input");

            this.hasContactMean = phoneInput.value || emailInput.value;

            if (!this.hasContactMean) {
                this.formErrors.push("noContactMean");
            }
        }

        this.updateErrorDisplay();
        return this.formErrors.length === 0;
    }

    updateErrorDisplay() {
        const errorMessages = [];

        if (this.formErrors.includes("invalidFormInputs")) {
            errorMessages.push(_t("Please fill out the form correctly."));
        }

        if (this.formErrors.includes("noContactMean")) {
            errorMessages.push(
                _t(
                    "Please enter either a contact email address or a contact phone number.",
                ),
            );
        }

        if (this.formErrors.includes("forbidden")) {
            errorMessages.push(_t("You cannot access this page."));
        }

        const errorElement = this.el.querySelector(".o_wetrack_proposal_error_message");
        errorElement.textContent = errorMessages.join(" ");
    }

    /**
     * @param {Event} ev
     */
    onAdvancedContactToggle() {
        this.useAdvancedContact = !this.useAdvancedContact;
        const contactEmailInput = this.el.querySelector(
            ".o_wetrack_contact_email_input",
        );

        if (!this.useAdvancedContact) {
            contactEmailInput.value = "";
        }
    }

    /**
     * @param {Event} ev
     */
    onPartnerNameInput(ev) {
        const partnerNameText = ev.currentTarget.value;
        const contactNameInput = this.el.querySelector(".o_wetrack_contact_name_input");
        if (partnerNameText.startsWith(contactNameInput.value)) {
            contactNameInput.value = partnerNameText;
        }
    }

    /**
     * @param {Event} ev
     */
    async onProposalFormSubmit() {
        const submitButton = this.el.querySelector(".o_wetrack_proposal_submit_button");
        submitButton.classList.add("disabled");
        submitButton.setAttribute("disabled", "disabled");

        if (this.isFormValid()) {
            const formData = new FormData(this.el);
            const eventId = encodeURIComponent(this.el.dataset.eventId);

            const jsonResponse = await this.waitFor(
                post(`/event/${eventId}/track_proposal/post`, formData),
            );
            this.bindDeferred(() => {
                if (jsonResponse.success) {
                    const parentEl = this.el.parentNode;
                    this.services["public.interactions"].stopInteractions(this.el);
                    this.el.replaceWith(
                        renderToElement("event_track_proposal_success"),
                    );
                    scrollTo(parentEl, { extraOffset: 20, duration: 50 });
                    return;
                } else if (jsonResponse.error) {
                    this.updateErrorDisplay([jsonResponse.error]);
                }
            })();
        }

        submitButton.classList.remove("disabled");
        submitButton.removeAttribute("disabled");
    }
}

registry
    .category("public.interactions")
    .add(
        "website_event_track.website_event_track_proposal_form",
        WebsiteEventTrackProposalForm,
    );
