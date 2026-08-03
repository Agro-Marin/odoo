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
     * Archive the address.
     *
     * @param {Event} ev
     */
    async removeAddress(ev) {
        try {
            await this.waitFor(rpc('/my/address/archive', {
                partner_id: ev.currentTarget.dataset.partnerId,
            }));
        } catch (error) {
            // The route raises UserError (archiving the main address) or
            // Forbidden (not the customer's address); surface it instead of
            // failing silently, and don't reload on failure.
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
     * Show/hide the billing address row when the user toggles the "use delivery as billing" input.
     *
     * The URLs of the "create address" buttons are updated to propagate the value of the input.
     *
     * @param {Event} ev
     */
    toggleBillingAddressRow(ev) {
        const useDeliveryAsBilling = ev.target.checked;

        const addDeliveryAddressButton = this.el.querySelector(
            '.o_address_card_add_new[data-address-type="delivery"]'
        );
        if (addDeliveryAddressButton) {  // If `Add address` button for delivery.
            // Update the `use_delivery_as_billing` query param for a new delivery address URL.
            // No encodeURIComponent: `searchParams.set` percent-encodes the value
            // itself, so pre-encoding double-encodes it. Harmless for the two
            // boolean literals this ever carries, but the pattern is a bug waiting
            // for a value that needs escaping.
            const addDeliveryUrl = new URL(addDeliveryAddressButton.href);
            addDeliveryUrl.searchParams.set('use_delivery_as_billing', useDeliveryAsBilling);
            addDeliveryAddressButton.href = addDeliveryUrl.toString();
        }

        // Toggle the billing address row and its "Add billing address" button together.
        // Both are optional, like the delivery button above: the billing block is
        // absent from template variants that only collect a delivery address, and
        // an unguarded `.classList` there threw before the URL update could be seen.
        this.billingContainer?.classList.toggle('d-none', useDeliveryAsBilling);
        this.addBillingAddressBtn?.classList.toggle('d-none', useDeliveryAsBilling);
    }
}

registry
    .category('public.interactions')
    .add('portal.address_card', AddressCard);
