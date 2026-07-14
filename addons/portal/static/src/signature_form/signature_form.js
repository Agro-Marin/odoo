/** @odoo-module native */
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { addLoadingEffect } from '@web/core/utils/dom/ui';
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { redirect } from "@web/core/utils/urls";
import { NameAndSignature } from "@web/components/signature/name_and_signature";

/**
 * This Component is a signature request form. It uses
 * @see NameAndSignature for the input fields, adds a submit
 * button, and handles the RPC to save the result.
 */
export class SignatureForm extends Component {
    static template = "portal.SignatureForm"
    static components = { NameAndSignature }
    static props = ["*"];

    setup() {
        this.rootRef = useRef("root");

        this.state = useState({
            error: false,
            success: false,
        });
        this.signature = useState({
            name: this.props.defaultName,
            getSignatureImage: () => "",
            resetSignature: () => {},
        });
        this.nameAndSignatureProps = {
            signature: this.signature,
            fontColor: this.props.fontColor || "black",
        };
        if (this.props.signatureRatio) {
            this.nameAndSignatureProps.displaySignatureRatio = this.props.signatureRatio;
        }
        if (this.props.signatureType) {
            this.nameAndSignatureProps.signatureType = this.props.signatureType;
        }
        if (this.props.mode) {
            this.nameAndSignatureProps.mode = this.props.mode;
        }

        // Correctly set up the signature area if it is inside a modal
        this.onModalShown = () => {
            this.signature.resetSignature();
            this.toggleSignatureFormVisibility();
        };
        onMounted(() => {
            this.modalEl = this.rootRef.el.closest('.modal');
            this.modalEl?.addEventListener('shown.bs.modal', this.onModalShown);
        });
        // The modal can outlive this component (it lives outside the mount
        // point); without removing the listener, a later modal open would run
        // toggleSignatureFormVisibility() against a torn-down rootRef.
        onWillUnmount(() => {
            this.modalEl?.removeEventListener('shown.bs.modal', this.onModalShown);
        });
    }

    toggleSignatureFormVisibility() {
        this.rootRef.el?.classList.toggle('d-none', document.querySelector('.editor_enable'));
    }

    get sendLabel() {
        return this.props.sendLabel || _t("Accept & Sign");
    }

     /**
     * Handles click on the submit button.
     *
     * This will get the current name and signature and validate them.
     * If they are valid, they are sent to the server, and the reponse is
     * handled. If they are invalid, it will display the errors to the user.
     *
     * @returns {Promise}
     */
    async onClickSubmit() {
        // Scope the lookup to this component's root: a document-wide query would
        // grab the first form's button when several signature forms coexist.
        const button = this.rootRef.el.querySelector('.o_portal_sign_submit');
        const icon = button.removeChild(button.firstChild);
        const restoreBtnLoading = addLoadingEffect(button);

        const name = this.signature.name;
        const signature = this.signature.getSignatureImage().split(",")[1];
        let data;
        try {
            data = await rpc(this.props.callUrl, { name, signature });
        } catch (error) {
            // Restore the button so the user can retry instead of being left
            // with a permanently spinning, disabled control.
            restoreBtnLoading();
            button.prepend(icon);
            throw error;
        }
        // Restore the button for every in-page outcome (validation error or
        // success). On the force_refresh path the page navigates away, so it
        // is moot there but harmless.
        restoreBtnLoading();
        button.prepend(icon);
        if (data.force_refresh) {
            if (data.redirect_url) {
                redirect(data.redirect_url);
            } else {
                window.location.reload();
            }
            // do not resolve if we reload the page
            return new Promise(() => {});
        }
        this.state.error = data.error || false;
        // Keys must match the template (portal.SignatureForm): it reads
        // ``redirect_url`` / ``redirect_message``. Emitting camelCase here left
        // the post-sign success link permanently hidden.
        this.state.success = !data.error && {
            message: data.message,
            redirect_url: data.redirect_url,
            redirect_message: data.redirect_message,
        };
    }
}

registry.category("public_components").add("portal.signature_form", SignatureForm);
