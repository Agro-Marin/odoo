// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown/dropdown_group - Groups multiple dropdowns so only one can be open at a time */

import { Component, onWillDestroy, useChildSubEnv, xml } from "@odoo/owl";

const GROUPS = new Map();

function getGroup(id) {
    if (!GROUPS.has(id)) {
        GROUPS.set(id, {
            group: new Set(),
            count: 0,
        });
    }
    GROUPS.get(id).count++;
    return GROUPS.get(id).group;
}

function removeGroup(id) {
    const groupData = GROUPS.get(id);
    if (!groupData) {
        // Defensive: nothing to release (e.g. already deleted), avoids a TypeError.
        return;
    }
    groupData.count--;
    if (groupData.count <= 0) {
        GROUPS.delete(id);
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
        if (this.props.group) {
            // Capture at setup time: props.group may change before onWillDestroy
            // fires, which would otherwise release the wrong group.
            const groupId = this.props.group;
            const group = getGroup(groupId);
            onWillDestroy(() => removeGroup(groupId));
            useChildSubEnv(/** @type {any} */ ({ [DROPDOWN_GROUP]: group }));
        } else {
            useChildSubEnv(/** @type {any} */ ({ [DROPDOWN_GROUP]: new Set() }));
        }
    }
}
