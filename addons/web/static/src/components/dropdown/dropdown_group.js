// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown/dropdown_group */

import { Component, useChildSubEnv, useEffect, xml } from "@odoo/owl";

/** @type {Map<any, { group: Set<any>, count: number }>} */
const GROUPS = new Map();

/** @param {any} id */
function getGroup(id) {
    if (!GROUPS.has(id)) {
        GROUPS.set(id, {
            group: new Set(),
            count: 0,
        });
    }
    const groupData = /** @type {{ group: Set<any>, count: number }} */ (
        GROUPS.get(id)
    );
    groupData.count++;
    return groupData.group;
}

/** @param {any} id */
function removeGroup(id) {
    const groupData = GROUPS.get(id);
    if (!groupData) {
        return;
    }
    groupData.count--;
    if (groupData.count <= 0) {
        GROUPS.delete(id);
    }
}

/**
 * The dropdown states one DropdownGroup contributes, behind a handle that
 * outlives the set itself. `useChildSubEnv` runs once, so the value the
 * children read can never be swapped; the `group` prop can change, so the set
 * behind it has to be. Holding our own members apart from the shared set is
 * what lets a move take exactly this group's dropdowns with it and leave the
 * other contributors to the same id alone.
 */
class DropdownGroupMembership {
    constructor() {
        /** @type {Set<any>} */
        this.members = new Set();
        /** @type {Set<any>} */
        this.shared = new Set();
    }

    /** @param {Set<any>} shared */
    moveTo(shared) {
        if (shared === this.shared) {
            return;
        }
        for (const member of this.members) {
            this.shared.delete(member);
        }
        this.shared = shared;
        for (const member of this.members) {
            this.shared.add(member);
        }
    }

    /** @param {any} member */
    add(member) {
        this.members.add(member);
        this.shared.add(member);
    }

    /** @param {any} member */
    delete(member) {
        this.members.delete(member);
        this.shared.delete(member);
    }

    /** @returns {boolean} */
    get isOpen() {
        for (const dropdown of this.shared) {
            if (dropdown.isOpen) {
                return true;
            }
        }
        return false;
    }
}

export const DROPDOWN_GROUP = Symbol("dropdownGroup");
export class DropdownGroup extends Component {
    static template = xml`<t t-slot="default"/>`;
    static props = {
        group: { type: String, optional: true },
        slots: Object,
    };

    setup() {
        const membership = new DropdownGroupMembership();
        useChildSubEnv(/** @type {any} */ ({ [DROPDOWN_GROUP]: membership }));
        // An effect rather than setup: it is the only place that both sees a
        // new `group` and gets to release what the old one claimed. Children
        // mount -- and register -- first, which is what moveTo carries over.
        useEffect(
            (groupId) => {
                membership.moveTo(groupId ? getGroup(groupId) : new Set());
                return () => {
                    if (groupId) {
                        removeGroup(groupId);
                    }
                };
            },
            () => [this.props.group],
        );
    }
}
