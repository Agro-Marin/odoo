/** @odoo-module native */
import { useComponent } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { getFieldDomain } from "@web/model/relational_model";
import { useCommand } from "@web/ui/commands";

export function useAssignUserCommand() {
    const component = useComponent();
    const orm = useService("orm");
    const type = component.props.record.fields[component.props.name].type;
    if (component.relation !== "res.users") {
        return;
    }

    // One search in flight at a time: a newer keystroke aborts the previous rpc
    // AND settles its promise, which abort(false) alone does not do.
    const keepLast = new KeepLast({ rejectSuperseded: true });

    const getCurrentIds = () => {
        if (type === "many2one" && component.props.record.data[component.props.name]) {
            return [component.props.record.data[component.props.name].id];
        } else if (type === "many2many") {
            return component.props.record.data[component.props.name].currentIds;
        }
        return [];
    };

    /** @param {[number, string]} record */
    const add = async (record) => {
        if (type === "many2one") {
            component.props.record.update({
                [component.props.name]: {
                    id: record[0],
                    display_name: record[1],
                },
            });
        } else if (type === "many2many") {
            component.props.record.data[component.props.name].linkTo(record[0], {
                display_name: record[1],
            });
        }
    };

    /** @param {[number, string]} record */
    const remove = async (record) => {
        if (type === "many2one") {
            component.props.record.update({ [component.props.name]: false });
        } else if (type === "many2many") {
            component.props.record.data[component.props.name].unlinkFrom(record[0]);
        }
    };

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{searchValue: string}} options
     * @returns {Promise<Object[]>}
     */
    const provide = async (env, options) => {
        const value = options.searchValue.trim();
        let domain = getFieldDomain(
            component.props.record,
            component.props.name,
            component.props.domain,
        );
        const context = component.props.context;
        if (type === "many2many") {
            const selectedUserIds = getCurrentIds();
            if (selectedUserIds.length) {
                domain = Domain.and([
                    domain,
                    [["id", "not in", selectedUserIds]],
                ]).toList();
            }
        }
        let searchResult;
        try {
            searchResult = await keepLast.add(
                orm.call(component.relation, "name_search", [], {
                    name: value,
                    domain: domain,
                    operator: "ilike",
                    limit: 80,
                    context,
                }),
            );
        } catch (error) {
            // A later keystroke replaced this search. Returning ends this frame;
            // the previous shape aborted the superseded rpc with abort(false),
            // which drops the request WITHOUT settling its promise, so the
            // `await` above never resumed and one suspended frame -- with its
            // domain, context and closure over the component -- was retained per
            // keystroke for the life of the page.
            if (error instanceof SupersededError) {
                return [];
            }
            throw error;
        }
        return searchResult.map((record) => ({
            name: record[1],
            action: add.bind(null, record),
        }));
    };
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
                    provide,
                },
            ],
        }),
        {
            ...options,
            hotkey: "alt+i",
        },
    );

    useCommand(
        _t("Assign to me"),
        () => {
            add([user.userId, user.name]);
        },
        {
            ...options,
            isAvailable: () =>
                options.isAvailable() && !getCurrentIds().includes(user.userId),
            hotkey: "alt+shift+i",
        },
    );
    if (component.props.record.id === component.props.record.model.root.id) {
        useCommand(
            _t("Unassign from me"),
            () => {
                remove([user.userId, user.name]);
            },
            {
                ...options,
                isAvailable: () =>
                    options.isAvailable() && getCurrentIds().includes(user.userId),
                hotkey: "alt+shift+i",
            },
        );
    } else {
        if (type === "many2one") {
            useCommand(
                _t("Unassign"),
                () => {
                    remove([user.userId, user.name]);
                },
                {
                    ...options,
                    isAvailable: () =>
                        options.isAvailable() && getCurrentIds().length > 0,
                    hotkey: "alt+shift+u",
                },
            );
        } else {
            useCommand(
                _t("Unassign from me"),
                () => {
                    remove([user.userId, user.name]);
                },
                {
                    ...options,
                    isAvailable: () =>
                        options.isAvailable() && getCurrentIds().includes(user.userId),
                    hotkey: "alt+shift+u",
                },
            );
        }
    }
}
