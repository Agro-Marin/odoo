-- deactivate mail template
UPDATE mail_template
   SET mail_server_id = NULL;
-- deactivate fetchmail server
UPDATE fetchmail_server
   SET active = false;

-- reset WEB Push Notification:
-- * delete VAPID/JWT keys
DELETE FROM ir_config_parameter
    WHERE key IN ('mail.web_push_vapid_private_key', 'mail.web_push_vapid_public_key');
-- disconnect third-party services: RTC (SFU, Twilio), translation, GIF
-- (a boolean config parameter is unset when its row is absent)
DELETE FROM ir_config_parameter
    WHERE key IN ('mail.use_sfu_server', 'mail.sfu_server_url', 'mail.sfu_server_key',
                  'mail.use_twilio_rtc_servers', 'mail.twilio_account_sid', 'mail.twilio_account_token',
                  'mail.google_translate_api_key', 'discuss.klipy_api_key');
-- * delete delayed messages (CRON)
TRUNCATE mail_push;
-- * delete Devices for each partners
DELETE FROM mail_push_device;
