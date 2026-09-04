-- On a neutralized (non-production) database, drop the S3 credentials and turn
-- off the environment switch, so a copy restored from production arrives safe:
-- S3 is off by default and is only re-enabled by hand in Settings when a
-- developer deliberately wants to test against S3.
DELETE FROM ir_config_parameter
WHERE key IN (
    'cloud_storage_s3_enabled',
    'cloud_storage_s3_bucket_name',
    'cloud_storage_s3_region',
    'cloud_storage_s3_access_key_id',
    'cloud_storage_s3_secret_access_key'
);
