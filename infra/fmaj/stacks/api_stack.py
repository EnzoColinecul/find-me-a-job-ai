"""FastAPI Lambda + API Gateway (per stage)."""
import aws_cdk as cdk
from constructs import Construct

from fmaj.config import StageConfig
from fmaj.stacks.auth_stack import AuthStack
from fmaj.stacks.data_stack import DataStack
from fmaj.stacks.pipeline_stack import PipelineStack


class ApiStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: StageConfig,
        data: DataStack,
        auth: AuthStack,
        pipeline: PipelineStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # TODO(Notion: "POST /searches endpoint"):
        #   - PythonFunction bundling ../api with Mangum handler `app.main.handler`
        #   - env: FMAJ_STAGE, FMAJ_TABLE_NAME=data.table.table_name,
        #     FMAJ_REPORTS_BUCKET, FMAJ_COGNITO_*, FMAJ_STATE_MACHINE_ARN
        #   - grants: table RW, start execution on pipeline state machine
        #   - HTTP API + Cognito JWT authorizer, throttling
        self.config = config
