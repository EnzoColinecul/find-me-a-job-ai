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
        #   - grants: table RW, start execution on pipeline state machine, and
        #     states:StopExecution on its executions (POST /searches/{id}/stop —
        #     grant_start_execution alone is NOT enough, Stop will 403)
        #   - HTTP API + Cognito JWT authorizer, throttling
        #
        # TODO(Notion: "Rate limiting, error handling & cost dashboard"):
        #   - env: FMAJ_GLOBAL_MONTHLY_SEARCHES=config.monthly_search_cap
        #     `monthly_search_cap` has existed on StageConfig since Phase 0 (test
        #     10 / prod 30) and reaches nothing — the API-side cap landed with
        #     the hardening card and reads this env var, defaulting to 30. Until
        #     this stack is built, the deployed value is whatever the default is,
        #     NOT the per-stage number written in config.py.
        #   - HTTP API throttling: rate/burst on the default stage
        #   - CloudWatch dashboard + agent-failure-rate alarm. Blocked on this
        #     stack existing: the API metrics it would chart have no resource to
        #     come from yet.
        self.config = config
