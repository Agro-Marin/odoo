"""Stop managing the records that ``loyalty.program.create`` now builds itself.

``gift_card_program_rule`` and ``gift_card_program_reward`` used to be declared in
``data/loyalty_data.xml``. They were an exact copy of what
``_program_type_default_values()['gift_card']`` contributes, and ``create`` now
applies that for any program created with an explicit ``program_type`` -- so
declaring them again would give the gift card program a second rule and a second
reward, which ``pos_loyalty`` refuses to open a session with.

On an existing database the two records already exist and are in use. Dropping
their ``ir_model_data`` rows un-manages them: ``_process_end`` no longer sees a
vanished external id and so does not delete them, and nothing here creates or
destroys a record. A database installed after this change gets the same rule and
reward from the defaults instead.

The config parameter is renamed in the same pass. Its external id said
``config_online_sync_proxy_mode`` and it has never had anything to do with an
online sync proxy; renaming the row rather than the record keeps the parameter,
which is unique on ``key`` and could not simply be re-created.
"""


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'loyalty'
           AND name IN ('gift_card_program_rule', 'gift_card_program_reward')
        """
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET name = 'config_compute_all_discount_product_ids'
         WHERE module = 'loyalty'
           AND name = 'config_online_sync_proxy_mode'
        """
    )
