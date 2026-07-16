/** @odoo-module native */

/**
 * Build the rotting extension applied to a kanban controller's per-instance
 * ``progressBarState``.
 *
 * Returns a FRESH object on every call — this is required, not cosmetic:
 * ``patch()`` mutates its extension argument in place (it re-parents it onto the
 * super-skeleton), so an extension object is single-use. The controller patches
 * ``this.progressBarState`` in ``setup()``, which runs once per controller
 * instantiation; reusing a shared module-level object throws "extension object
 * already used in a patch" on the second kanban render (breaking every rotting
 * kanban). A fresh object per instance also gives each controller its own
 * ``rotIsFiltered`` state instead of silently sharing one dict across kanbans.
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
                return group.list.records.filter((record) => record.data.is_rotting)
                    .length;
            }
            return super.getGroupCount(group);
        },
    };
}
