/** @odoo-module native */
import { handleCheckIdentity } from "@portal/interactions/portal_security";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class RevokeTrustedDevice extends Interaction {
    // Selects on the template's own hook class, not on the icon set's: this
    // read `.fa.fa-trash.text-danger` until the FontAwesome 4 -> 7 upgrade
    // renamed those classes in the template and left the button inert.
    static selector = ".o_totp_portal_revoke_device";
    dynamicContent = {
        _root: { "t-on-click.prevent": this.onClick },
    };

    async onClick() {
        await this.waitFor(
            handleCheckIdentity(
                this.waitFor(
                    this.services.orm.call("auth_totp.device", "remove", [
                        parseInt(this.el.id),
                    ]),
                ),
                this.services.orm,
                this.services.dialog,
            ),
        );
        location.reload();
    }
}

registry
    .category("public.interactions")
    .add("auth_portal.revoke_trusted_device", RevokeTrustedDevice);
