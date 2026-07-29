"""Stage construct: groups all stacks for one environment (test or prod)."""
import aws_cdk as cdk
from constructs import Construct

from fmaj.config import StageConfig
from fmaj.stacks.auth_stack import AuthStack
from fmaj.stacks.data_stack import DataStack
from fmaj.stacks.api_stack import ApiStack
from fmaj.stacks.pipeline_stack import PipelineStack


class FmajStage(cdk.Stage):
    def __init__(self, scope: Construct, construct_id: str, *, config: StageConfig, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        data = DataStack(self, "Data", config=config)
        auth = AuthStack(self, "Auth", config=config)
        pipeline = PipelineStack(self, "Pipeline", config=config, data=data)
        ApiStack(self, "Api", config=config, data=data, auth=auth, pipeline=pipeline)

        cdk.Tags.of(self).add("project", "fmaj")
        cdk.Tags.of(self).add("stage", config.stage)
