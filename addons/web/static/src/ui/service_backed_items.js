// @ts-check
/** @odoo-module native */

/**
 * @param {import("@odoo/owl").Component} component
 * @param {object} [fromProps]
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
