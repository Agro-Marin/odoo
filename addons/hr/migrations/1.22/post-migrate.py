def migrate(cr, version):
    """An information change request is never reviewed by the person asking.

    Until 1.22 the request enforced that itself, by dropping its requester from
    the reviewers. The engine now enforces it for every category that does not
    allow self-approval, and approval 19.0.2.1.0 marks every category that
    already existed as allowing it, to keep behaviour on upgrade. This one's
    behaviour was never to allow it, so it is put back.
    """
    cr.execute(
        """
        UPDATE approval_category
           SET allow_self_approval = FALSE
         WHERE id IN (
                SELECT res_id FROM ir_model_data
                 WHERE module = 'hr'
                   AND name = 'approval_category_employee_change_request'
               )
        """
    )
