/** @odoo-module native */
import { useComponent } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { getFieldDomain } from "@web/model/relational_model";
import { useCommand } from "@web/ui/commands";

/**
 * @param {import("@odoo/owl").Component} component
 * @param {string} type
 * @returns {number[]}
 */
function getCurrentAssignedIds(component, type) {
    const value = component.props.record.data[component.props.name];
    if (type === "many2one" && value) {
        return [value.id];
    }
    if (type === "many2many") {
        return value.currentIds;
    }
    return [];
}
/**
 * @param {import("@odoo/owl").Component} component
 * @param {string} type
 * @param {[number, string]} record
 */
function updateAssignment(component, type, record) {
    if (type === "many2one") {
        component.props.record.update({
            [component.props.name]: { id: record[0], display_name: record[1] },
        });
    } else if (type === "many2many") {
        component.props.record.data[component.props.name].linkTo(record[0], {
            display_name: record[1],
        });
    }
}
/**
 * @param {import("@odoo/owl").Component} component
 * @param {string} type
 * @param {[number, string]} record
 */
function clearAssignment(component, type, record) {
    if (type === "many2one") {
        component.props.record.update({ [component.props.name]: false });
    } else if (type === "many2many") {
        component.props.record.data[component.props.name].unlinkFrom(record[0]);
    }
}
/**
 * @param {{component: any, type: string, orm: any, keepLast: KeepLast}} ctx
 * @param {{searchValue: string}} options
 * @returns {Promise<Object[]>}
 */
async function provideAssignableUsers({ component, type, orm, keepLast }, options) {
    let domain = getFieldDomain(
        component.props.record,
        component.props.name,
        component.props.domain,
    );
    if (type === "many2many") {
        const selectedUserIds = getCurrentAssignedIds(component, type);
        if (selectedUserIds.length) {
            domain = Domain.and([domain, [["id", "not in", selectedUserIds]]]).toList();
        }
    }
    let searchResult;
    try {
        searchResult = await keepLast.add(
            orm.call(component.relation, "name_search", [], {
                name: options.searchValue.trim(),
                domain,
                operator: "ilike",
                limit: 80,
                context: component.props.context,
            }),
        );
    } catch (error) {
        if (error instanceof SupersededError) {
            return [];
        }
        throw error;
    }
    return searchResult.map((record) => ({
        name: record[1],
        action: async () => updateAssignment(component, type, record),
    }));
}
/**
 * @param {import("@odoo/owl").Component} component
 * @param {string} type
 * @param {Object} options
 * @param {() => number[]} getCurrentIds
 * @param {(record: [number, string]) => void} remove
 */
function useUnassignCommands(component, type, options, getCurrentIds, remove) {
    const unassignFromMe = {
        ...options,
        isAvailable: () =>
            options.isAvailable() && getCurrentIds().includes(user.userId),
    };
    if (component.props.record.id === component.props.record.model.root.id) {
        useCommand(_t("Unassign from me"), () => remove([user.userId, user.name]), {
            ...unassignFromMe,
            hotkey: "alt+shift+i",
        });
        return;
    }
    if (type === "many2one") {
        useCommand(_t("Unassign"), () => remove([user.userId, user.name]), {
            ...options,
            isAvailable: () => options.isAvailable() && getCurrentIds().length > 0,
            hotkey: "alt+shift+u",
        });
        return;
    }
    useCommand(_t("Unassign from me"), () => remove([user.userId, user.name]), {
        ...unassignFromMe,
        hotkey: "alt+shift+u",
    });
}
export function useAssignUserCommand() {
    const component = useComponent();
    const orm = useService("orm");
    const type = component.props.record.fields[component.props.name].type;
    if (component.relation !== "res.users") {
        return;
    }
    const keepLast = new KeepLast({ rejectSuperseded: true });
    const getCurrentIds = () => getCurrentAssignedIds(component, type);
    /** @param {[number, string]} record */
    const add = async (record) => updateAssignment(component, type, record);
    /** @param {[number, string]} record */
    const remove = async (record) => clearAssignment(component, type, record);
    const options = {
        category: "smart_action",
        global: true,
        identifier: component.props.string,
    };
    if (component.props.record.id !== component.props.record.model.root.id) {
        options.isAvailable = () =>
            component.props.record.model.multiEdit && component.props.record.selected;
    } else {
        options.isAvailable = () => true;
    }
    useCommand(
        _t("Assign to ..."),
        () => ({
            configByNameSpace: {
                default: {
                    emptyMessage: _t("No users found"),
                },
            },
            placeholder: _t("Select a user..."),
            providers: [
                {
                    provide: (env, providerOptions) =>
                        provideAssignableUsers(
                            { component, type, orm, keepLast },
                            providerOptions,
                        ),
                },
            ],
        }),
        { ...options, hotkey: "alt+i" },
    );
    useCommand(_t("Assign to me"), () => add([user.userId, user.name]), {
        ...options,
        isAvailable: () =>
            options.isAvailable() && !getCurrentIds().includes(user.userId),
        hotkey: "alt+shift+i",
    });
    useUnassignCommands(component, type, options, getCurrentIds, remove);
}
