import { registry } from "@web/core/registry";

/**
 * The Team Members list renders each salesperson's avatar.
 *
 * The kanban of the same action has always shown the avatar; the list showed a
 * bare name, so the two view modes of one screen disagreed. This tour drives
 * the real action and the real view, which is the only way to assert a view
 * arch: a HOOT test supplies its own arch and would pass either way.
 */
registry.category("web_tour.tours").add("crm_team_member_list_avatar", {
    url: "/odoo/action-sales_team.crm_team_member_action",
    steps: () => [
        {
            content: "switch to the list view",
            trigger: "button.o_switch_view.o_list",
            run: "click",
        },
        {
            content: "the row is there",
            trigger: ".o_list_view .o_data_row td[name='user_id']:contains('Avatar Salesperson')",
        },
        {
            content: "and it carries the salesperson's avatar, not a bare name",
            trigger:
                ".o_list_view .o_data_row td[name='user_id'] .o_field_many2one_avatar .o_m2o_avatar img",
        },
    ],
});
