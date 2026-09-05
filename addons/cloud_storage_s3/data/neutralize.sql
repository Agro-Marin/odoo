-- On a neutralized (non-production) database, drop the S3 settings, turn off
-- the environment switch and retire the IAM keys, so a copy restored from
-- production arrives safe: S3 is off by default and is only re-enabled by hand
-- in Settings when a developer deliberately wants to test against S3.
DELETE FROM ir_config_parameter
WHERE key IN (
    'cloud_storage_s3_enabled',
    'cloud_storage_s3_bucket_name',
    'cloud_storage_s3_region'
);
UPDATE credential_credential
SET active = false
WHERE category_id IN (
    SELECT id FROM credential_category WHERE code = 'cloud_storage_s3'
);
