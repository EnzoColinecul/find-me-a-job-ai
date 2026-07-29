"""Step Functions search pipeline: Discover -> Map(agent) -> Aggregate -> PDF (per stage)."""
import aws_cdk as cdk
from constructs import Construct

from fmaj.config import StageConfig
from fmaj.stacks.data_stack import DataStack


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

        # TODO(Notion: "Step Functions pipeline"):
        #   - Discover Lambda (Google Places, field-mask discipline)
        #   - Map state over companies, maxConcurrency 5-10, catch -> mark failed
        #   - Agent Lambda bundling ../agent, Bedrock invoke perms (au. profiles)
        #   - Aggregate Lambda; PDF container Lambda (WeasyPrint) -> reports bucket
        #   - Execution timeout 15 min; CloudWatch dashboard
        self.config = config
        self.data = data
