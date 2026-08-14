"""DynamoDB single-table + S3 reports bucket (per stage)."""
import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb, aws_s3 as s3
from constructs import Construct

from fmaj.config import StageConfig


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, config: StageConfig, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        self.table = ddb.Table(
            self,
            "MainTable",
            table_name=f"fmaj-{config.stage}-main",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PROVISIONED,  # 25/25 free tier
            read_capacity=10,
            write_capacity=10,
            # STEP# items (the live agent trace) set `expires_at`. They are
            # progress, not a record: expiring them keeps the table small and
            # avoids holding Places-derived company names indefinitely.
            # Nothing else sets the attribute, so nothing else expires.
            time_to_live_attribute="expires_at",
            removal_policy=cdk.RemovalPolicy.DESTROY
            if config.stage == "test"
            else cdk.RemovalPolicy.RETAIN,
        )

        self.reports_bucket = s3.Bucket(
            self,
            "ReportsBucket",
            bucket_name=f"fmaj-{config.stage}-reports-418862088910",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                s3.LifecycleRule(expiration=cdk.Duration.days(config.report_expiry_days))
            ],
            removal_policy=cdk.RemovalPolicy.DESTROY
            if config.stage == "test"
            else cdk.RemovalPolicy.RETAIN,
            auto_delete_objects=config.stage == "test",
        )
