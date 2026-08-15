"""FastAPI on Lambda behind an HTTP API (per stage).

The FastAPI app (`api/app`) verifies Cognito JWTs itself (app/auth.py) and applies
CORS via CORSMiddleware, so this stack deliberately does NOT put an API Gateway
JWT authorizer on the routes: a gateway authorizer would also block the public
routes (`/health`, `/config`) and the CORS preflight `OPTIONS`, and would
duplicate a check the app already does. The HTTP API is a thin proxy — a single
catch-all route to the Lambda — and the app decides what needs auth.

The Lambda bundles both `api/` and the shared `agent/` package (the API calls
fmaj_agent.interpret for /roles/interpret), so the build context is the repo root
with everything else excluded. Bundling forces linux/amd64 so compiled wheels
match the function architecture — same reasoning as PipelineStack.
"""
import aws_cdk as cdk
from aws_cdk import (
    BundlingOptions,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_int,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_secretsmanager as sm,
)
from constructs import Construct

from fmaj.config import StageConfig
from fmaj.stacks.auth_stack import AuthStack
from fmaj.stacks.data_stack import DataStack
from fmaj.stacks.pipeline_stack import PipelineStack

# Asset root is the repo (infra/..). Everything the API Lambda doesn't need is
# excluded so the asset hash is stable and the upload stays small. Mirrors the
# .gitignore secret patterns so a stray key never rides along in the bundle.
REPO_ROOT = ".."
ASSET_EXCLUDE = [
    ".git", ".git/**",
    "web", "web/**",
    "infra", "infra/**",
    "docs", "docs/**",
    "design", "design/**",
    "scripts", "scripts/**",
    "**/.venv", "**/.venv/**",
    "**/node_modules", "**/node_modules/**",
    "**/__pycache__", "**/*.pyc",
    "**/.pytest_cache", "**/.ruff_cache",
    "**/cdk.out", "**/cdk.out/**",
    "agent/evals", "agent/evals/**",
    "**/*.csv",
    # secrets (belt-and-suspenders next to .gitignore)
    ".env", ".env.*", "**/.env", "**/.env.*",
    "project-*.json", "client_secret*.json", "*gserviceaccount*.json",
    "*-outputs.json", "*.tfstate", "*.tfvars",
]

BUNDLE_CMD = (
    "set -e && "
    "pip install --no-cache-dir --target /asset-output "
    "-r /asset-input/api/requirements-lambda.txt && "
    "cp -r /asset-input/api/app /asset-output/ && "
    "cp -r /asset-input/agent/src/fmaj_agent /asset-output/ && "
    # Arch check only — importing the app needs boto3 (runtime-provided, absent at
    # build time), so validate the compiled wheel instead, exactly as Pipeline does.
    "PYTHONPATH=/asset-output python -c "
    "'import pydantic_core._pydantic_core; print(\"api bundle arch OK\")'"
)


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
        self.config = config

        code = lambda_.Code.from_asset(
            REPO_ROOT,
            exclude=ASSET_EXCLUDE,
            bundling=BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                platform="linux/amd64",  # match Lambda architecture
                command=["bash", "-c", BUNDLE_CMD],
            ),
        )

        fn = lambda_.Function(
            self,
            "ApiFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,  # must match bundled wheels
            code=code,
            handler="app.main.handler",  # Mangum(app) in api/app/main.py
            timeout=cdk.Duration.seconds(30),
            memory_size=1024,
            environment={
                "FMAJ_STAGE": config.stage,
                "FMAJ_AWS_REGION": self.region,
                "FMAJ_TABLE_NAME": data.table.table_name,
                "FMAJ_REPORTS_BUCKET": data.reports_bucket.bucket_name,
                "FMAJ_COGNITO_USER_POOL_ID": auth.user_pool.user_pool_id,
                "FMAJ_COGNITO_CLIENT_ID": auth.client.user_pool_client_id,
                "FMAJ_STATE_MACHINE_ARN": pipeline.state_machine.state_machine_arn,
                # Per-stage cap reaches the running API only through this env var
                # (settings.global_monthly_searches). Until now it defaulted to 30
                # regardless of config.py — this wires the real number.
                "FMAJ_GLOBAL_MONTHLY_SEARCHES": str(config.monthly_search_cap),
                "FMAJ_CORS_ORIGINS": config.cors_origins,
                # /roles/interpret runs the LLM; Gemini creds materialize from this
                # secret at first use (agent/providers.py), same as the pipeline.
                "FMAJ_LLM_PROVIDER": config.llm_provider,
                "FMAJ_GCP_SA_SECRET": f"fmaj/{config.stage}/gcp-sa-key",
            },
            log_retention=logs.RetentionDays.ONE_WEEK
            if config.stage == "test"
            else logs.RetentionDays.ONE_MONTH,
        )

        # ── grants ────────────────────────────────────────────────
        data.table.grant_read_write_data(fn)
        # PDF reports: build → put → head/get → presign (presign needs no grant,
        # the object read/write does).
        data.reports_bucket.grant_read_write(fn)
        # Kick off a search…
        pipeline.state_machine.grant_start_execution(fn)
        # …and stop one (POST /searches/{id}/stop). grant_start_execution does NOT
        # cover StopExecution, and Stop acts on the *execution* ARN, not the state
        # machine ARN — so grant it explicitly on this machine's executions.
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["states:StopExecution"],
                resources=[
                    self.format_arn(
                        service="states",
                        resource="execution",
                        resource_name=f"{pipeline.state_machine.state_machine_name}:*",
                        arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
                    )
                ],
            )
        )
        # Gemini service-account key for /roles/interpret.
        sm.Secret.from_secret_name_v2(
            self, "GcpSaKey", f"fmaj/{config.stage}/gcp-sa-key"
        ).grant_read(fn)

        # ── HTTP API (thin proxy; app owns auth + CORS) ───────────
        integration = apigwv2_int.HttpLambdaIntegration("ApiIntegration", fn)
        self.http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name=f"fmaj-{config.stage}-api",
            # No cors_preflight here on purpose: FastAPI's CORSMiddleware answers
            # OPTIONS and sets the headers, keyed off FMAJ_CORS_ORIGINS. Setting it
            # in both places would double the Access-Control-Allow-Origin header
            # and browsers reject that.
            default_integration=integration,
        )

        cdk.CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)
