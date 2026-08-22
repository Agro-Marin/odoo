// @ts-check
/** @odoo-module native */

import { Component, useChildSubEnv, useEffect, xml } from "@odoo/owl";

/** @type {Map<any, { group: Set<any>, count: number }>} */
const GROUPS = new Map();

/**
 * @param {any} id
 * @returns {Set<any>}
 */
function acquireGroup(id) {
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

/**
 * @param {any} id
 */
function releaseGroup(id) {
    const groupData = GROUPS.get(id);
    if (!groupData) {
        return;
    }
    groupData.count--;
    if (groupData.count <= 0) {
        GROUPS.delete(id);
    }
}

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
        useEffect(
            (groupId) => {
                membership.moveTo(groupId ? acquireGroup(groupId) : new Set());
                return () => {
                    if (groupId) {
                        releaseGroup(groupId);
                    }
                };
            },
            () => [this.props.group],
        );
    }
}
