// @ts-check
/** @odoo-module native */

/**
 * A container whose items live on a service: the overlay container reads the
 * overlay service's overlays, the notification container reads the notification
 * service's notifications, and a subclass paired with its own service reads
 * that one. Both accept the record as a prop instead, which is how a container
 * is mounted standalone.
 *
 * The class says which service and which field; this resolves them and says
 * which of the two is missing when it cannot.
 *
 * @param {import("@odoo/owl").Component} component
 * @param {object} [fromProps] the record handed in as a prop, if any
 * @returns {Record<string | number, any>}
 */
export function serviceBackedItems(component, fromProps) {
    if (fromProps) {
        return fromProps;
    }
    const { name, serviceName, itemsKey } = /** @type {any} */ (component.constructor);
    // eslint-disable-next-line no-restricted-syntax
    const service = component.env.services?.[serviceName];
    if (!service) {
        throw new Error(
            `${name}.serviceName is "${serviceName}", but no such service is started in this env. ` +
                `Pass the items as a prop, or start the service. A subclass paired with its own ` +
                `service must declare that service's registry key.`,
        );
    }
    return service[itemsKey];
}
