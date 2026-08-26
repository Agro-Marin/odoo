from odoo.tests import standalone


@standalone("cow_views_inherit", "website_standalone")
def test_01_cow_views_inherit_on_module_update(env):

    View = env["ir.ui.view"]
    View.with_context(_force_unlink=True, active_test=False).search(
        [("website_id", "=", 1)]
    ).unlink()
    child_view = env.ref("portal.footer_language_selector")
    parent_view = env.ref("portal.portal_back_in_edit_mode")
    parent_view.with_context(
        _force_unlink=True, active_test=False
    )._get_specific_views().unlink()
    child_view.with_context(
        _force_unlink=True, active_test=False
    )._get_specific_views().unlink()
    child_view.write(
        {
            "inherit_id": parent_view.id,
            "arch": child_view.arch_db.replace(
                "o_footer_copyright_name", "text-center"
            ),
        }
    )
    child_view.with_context(website_id=1).write({"name": "COW Website 1"})
    child_cow_view = child_view._get_specific_views()

    assert len(child_cow_view.inherit_id) == 1, (
        "Should only be the XML view and its COW counterpart."
    )
    assert child_cow_view.inherit_id == parent_view, "Ensure test is setup as expected."

    portal_module = env["ir.module.module"].search([("name", "=", "portal")])
    portal_module.button_immediate_upgrade()
    env.transaction.reset()

    expected_parent_view = env.ref("portal.frontend_layout")
    assert child_view.inherit_id == expected_parent_view, "Generic view security check."
    assert child_cow_view.inherit_id == expected_parent_view, (
        "COW view should also have received the `inherit_id` update."
    )


@standalone("cow_views_inherit", "website_standalone")
def test_02_cow_views_inherit_on_module_update(env):

    View = env["ir.ui.view"]
    View.with_context(_force_unlink=True, active_test=False).search(
        [("website_id", "=", 1)]
    ).unlink()
    view_D = env.ref("portal.my_account_link")
    view_A = env.ref("portal.message_thread")
    view_D.write(
        {
            "inherit_id": view_A.id,
            "arch_db": view_D.arch_db.replace("o_logout_divider", "discussion"),
        }
    )
    view_B = env.ref("portal.user_dropdown")
    view_D.with_context(website_id=1).write({"name": "D Website 1"})
    view_B.with_context(website_id=1).write({"name": "B Website 1"})
    view_Dcow = view_D._get_specific_views()

    view_Bcow = view_B._get_specific_views()
    assert view_Dcow.inherit_id == view_A, "Ensure test is setup as expected."
    assert len(view_Bcow) == len(view_Dcow) == 1, (
        "Ensure test is setup as expected (2)."
    )
    assert view_B != view_Bcow, (
        "Security check to ensure `_get_specific_views` return what it should."
    )

    portal_module = env["ir.module.module"].search([("name", "=", "portal")])
    portal_module.button_immediate_upgrade()
    env.transaction.reset()

    assert view_D.inherit_id == view_B, "Generic view security check."
    assert view_Dcow.inherit_id == view_Bcow, (
        "COW view should also have received the `inherit_id` update."
    )
