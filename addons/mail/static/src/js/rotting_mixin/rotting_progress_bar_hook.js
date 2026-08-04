/** @odoo-module native */

/**
 * Build the rotting extension applied to a kanban controller's per-instance
 * ``progressBarState``.
 *
 * Returns a FRESH object on every call: ``patch()`` mutates its extension argument
 * in place, so reusing a shared one throws "extension object already used in a
 * patch" on the second kanban render. It also gives each controller its own
 * ``rotIsFiltered`` state instead of sharing one dict across kanbans.
 *
 * @returns {object} a single-use patch extension
 */
export function rottingProgressBarPatch() {
    return {
        rotIsFiltered: {},
        async toggleFilterRotten(group) {
            if (!this.rotIsFiltered[group.id]) {
                await this.setFilterRotten(group);
            } else {
                await this.unsetFilterRotten(group);
            }
            group.model.notify();
        },
        async setFilterRotten(group) {
            await group.applyFilter([["is_rotting", "=", true]]);
            this.rotIsFiltered[group.id] = group;
            if (this.activeBars[group.serverValue]) {
                delete this.activeBars[group.serverValue];
            }
        },
        async unsetFilterRotten(group) {
            await group.applyFilter(undefined);
            delete this.rotIsFiltered[group.id];
        },
        /**
         * @override
         */
        async selectBar(groupId, bar) {
            if (this.rotIsFiltered[groupId]) {
                delete this.rotIsFiltered[groupId];
            }
            return super.selectBar(groupId, bar);
        },
        /**
         * @override
         */
        getGroupCount(group) {
            if (this.rotIsFiltered[group.id]) {
                // client-side filter: counts only the loaded page, not the group's
                // server-side total (unlike the super path), so the rotting count can
                // shrink to the loaded subset when the filter is toggled.
                return group.list.records.filter((record) => record.data.is_rotting)
                    .length;
            }
            return super.getGroupCount(group);
        },
    };
}
