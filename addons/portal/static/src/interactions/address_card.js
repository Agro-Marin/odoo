/** @odoo-module native */
import { rpc, RPCError } from "@web/core/network";
import { registry } from '@web/core/registry';
import { _t } from '@web/core/translation';
import { Interaction } from '@web/public/interaction';

export class AddressCard extends Interaction {
    static selector = '.o_portal_addresses';
    dynamicContent = {
        '.o_remove_address': { 't-on-click.prevent': this.locked(this.removeAddress, true) },
        '#use_delivery_as_billing': { 't-on-change': this.toggleBillingAddressRow },
    };

     setup() {
        this.billingContainer = this.el.querySelector('#billing_container');
        this.addBillingAddressBtn = this.el.querySelector('.o_add_billing_address_btn');
    }

    /**
     * @param {Event} ev
     */
    async removeAddress(ev) {
        try {
            await this.waitFor(rpc('/my/address/archive', {
                partner_id: ev.currentTarget.dataset.partnerId,
            }));
        } catch (error) {
            if (error instanceof RPCError) {
                this.services.notification.add(
                    error.data?.message || _t("The address could not be removed."),
                    { type: 'danger' }
                );
                return;
            }
            throw error;
        }
        location.reload();
    }

    /**
     * @param {Event} ev
     */
    toggleBillingAddressRow(ev) {
        const useDeliveryAsBilling = ev.target.checked;

        const addDeliveryAddressButton = this.el.querySelector(
            '.o_address_card_add_new[data-address-type="delivery"]'
        );
        if (addDeliveryAddressButton) {
            const addDeliveryUrl = new URL(addDeliveryAddressButton.href);
            addDeliveryUrl.searchParams.set('use_delivery_as_billing', useDeliveryAsBilling);
            addDeliveryAddressButton.href = addDeliveryUrl.toString();
        }

        this.billingContainer?.classList.toggle('d-none', useDeliveryAsBilling);
        this.addBillingAddressBtn?.classList.toggle('d-none', useDeliveryAsBilling);
    }
}

registry
    .category('public.interactions')
    .add('portal.address_card', AddressCard);
