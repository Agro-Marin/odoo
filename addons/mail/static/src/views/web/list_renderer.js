/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list";
patch(ListRenderer.prototype, {
    /**
     * @param {Object} _
     * @param {import("@web/model/relational_model/dynamic_list").DynamicList} list
     * @returns {Object[]}
     */
    getPropertyFieldColumns(_, list) {
        const columns = super.getPropertyFieldColumns(...arguments);
        for (const column of columns) {
            const { relation, type } = list.fields[column.name];
            if (relation === "res.users") {
                column.widget =
                    type === "many2one"
                        ? "many2one_avatar_user"
                        : "many2many_avatar_user";
            }
        }
        return columns;
    },
});
