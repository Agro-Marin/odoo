from . import models


def _forbid_self_approval(env):
    """On a database that upgraded into this bridge the activation category
    already existed, and approval 19.0.2.1.0 marked it allowing self-approval to
    keep behaviour. An administrator does not approve an activation they asked
    for; restore that."""
    category = env.ref(
        "approval_base_install_request.approval_category_module_activation",
        raise_if_not_found=False,
    )
    if category:
        category.allow_self_approval = False
