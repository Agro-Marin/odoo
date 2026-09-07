-- neutralization of Google calendar
-- The OAuth tokens live in credential.credential (encrypted), not on
-- res_users_settings: retire the linked credentials and unlink them so a
-- copy restored from production cannot keep syncing calendars.
UPDATE credential_credential
   SET active = false
 WHERE id IN (
       SELECT google_calendar_credential_id
         FROM res_users_settings
        WHERE google_calendar_credential_id IS NOT NULL
 );

UPDATE res_users_settings
   SET google_calendar_credential_id = NULL,
       google_synchronization_stopped = true;
