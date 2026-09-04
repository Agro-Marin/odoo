Cloud Storage S3
================

Store Odoo attachments in Amazon S3 using the built-in cloud storage provider framework.

Configuration
-------------

Go to **Settings → Technical → Cloud Storage** and select *Amazon S3*.
Fill in the S3 bucket name, AWS region, access key ID, and secret access key.

Click **Test Connection** to validate the credentials and configure CORS on the bucket.

Required IAM permissions
------------------------

The IAM user needs the following S3 permissions on the configured bucket::

    s3:PutObject
    s3:GetObject
    s3:DeleteObject
    s3:PutBucketCors
