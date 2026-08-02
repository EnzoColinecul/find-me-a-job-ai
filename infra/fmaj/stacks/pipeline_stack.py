"""Step Functions search pipeline: Discover -> Map(agent) -> Aggregate (per stage).

Lambdas bundle the ../agent package (Docker required for `cdk deploy` — bundling
runs `pip install` inside the Lambda build image).
"""
import aws_cdk as cdk
from aws_cdk import (
    BundlingOptions,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_secretsmanager as sm,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct

from fmaj.config import StageConfig
from fmaj.stacks.data_stack import DataStack

AGENT_PATH = "../agent"
MAP_CONCURRENCY = 5


class PipelineStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: StageConfig,
        data: DataStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)
        self.config = config

        code = lambda_.Code.from_asset(
            AGENT_PATH,
            bundling=BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                command=[
                    "bash", "-c",
                    "pip install --no-cache-dir /asset-input -t /asset-output",
                ],
            ),
        )

        common_env = {
            "FMAJ_STAGE": config.stage,
            "FMAJ_AWS_REGION": self.region,
            "FMAJ_TABLE_NAME": data.table.table_name,
            "FMAJ_LLM_PROVIDER": config.llm_provider,
            "FMAJ_GCP_SA_SECRET": f"fmaj/{config.stage}/gcp-sa-key",
        }

        def make_fn(name: str, handler: str, timeout_s: int, memory: int) -> lambda_.Function:
            return lambda_.Function(
                self,
                name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                code=code,
                handler=handler,
                timeout=cdk.Duration.seconds(timeout_s),
                memory_size=memory,
                environment=common_env,
                log_retention=logs.RetentionDays.ONE_WEEK
                if config.stage == "test"
                else logs.RetentionDays.ONE_MONTH,
            )

        discover_fn = make_fn("DiscoverFn", "fmaj_agent.handlers.discover_handler", 120, 512)
        investigate_fn = make_fn(
            "InvestigateFn", "fmaj_agent.handlers.investigate_handler", 150, 1024
        )
        aggregate_fn = make_fn("AggregateFn", "fmaj_agent.handlers.aggregate_handler", 30, 256)
        fail_fn = make_fn("FailFn", "fmaj_agent.handlers.fail_handler", 30, 256)

        # data + secrets grants
        for fn in (discover_fn, investigate_fn, aggregate_fn, fail_fn):
            data.table.grant_read_write_data(fn)
        secret_names = {
            discover_fn: ["places-key"],
            investigate_fn: ["adzuna", "web-search-key", "gcp-sa-key"],
        }
        for fn, names in secret_names.items():
            for name in names:
                sm.Secret.from_secret_name_v2(
                    self, f"{fn.node.id}-{name}", f"fmaj/{config.stage}/{name}"
                ).grant_read(fn)

        # ── state machine ────────────────────────────────
        discover_step = tasks.LambdaInvoke(
            self, "Discover", lambda_function=discover_fn, payload_response_only=True
        )
        investigate_step = tasks.LambdaInvoke(
            self, "InvestigateCompany", lambda_function=investigate_fn,
            payload_response_only=True,
            retry_on_service_exceptions=True,
        )
        investigate_step.add_retry(errors=["States.TaskFailed"], max_attempts=1,
                                   interval=cdk.Duration.seconds(5))

        map_step = sfn.Map(
            self, "InvestigateAll",
            items_path="$.companies",
            max_concurrency=MAP_CONCURRENCY,
            item_selector={
                "search_id.$": "$.search_id",
                "company.$": "$$.Map.Item.Value",
            },
            result_path="$.results",
        ).item_processor(investigate_step)

        aggregate_step = tasks.LambdaInvoke(
            self, "Aggregate", lambda_function=aggregate_fn, payload_response_only=True
        )

        fail_step = tasks.LambdaInvoke(
            self, "MarkFailed", lambda_function=fail_fn, payload_response_only=True
        ).next(sfn.Fail(self, "SearchFailed"))

        discover_step.add_catch(fail_step, result_path="$.error")
        map_step.add_catch(fail_step, result_path="$.error")

        definition = discover_step.next(map_step).next(aggregate_step)

        self.state_machine = sfn.StateMachine(
            self,
            "SearchPipeline",
            state_machine_name=f"fmaj-{config.stage}-search",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=cdk.Duration.minutes(15),
        )

        cdk.CfnOutput(self, "StateMachineArn", value=self.state_machine.state_machine_arn)
