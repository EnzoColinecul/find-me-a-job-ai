"""Smoke test: both stages synthesize without errors."""
import aws_cdk as cdk

from fmaj.config import PROD, TEST
from fmaj.stage import FmajStage


def test_stages_synth() -> None:
    # skip Docker bundling of Lambda assets in tests
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    env = cdk.Environment(account="418862088910", region="ap-southeast-2")
    FmajStage(app, "Fmaj-Test", config=TEST, env=env)
    FmajStage(app, "Fmaj-Prod", config=PROD, env=env)
    assembly = app.synth()
    stacks = {s.stack_name: s for s in assembly.stacks_recursively}
    assert "Fmaj-Test-Pipeline" in stacks and "Fmaj-Prod-Pipeline" in stacks
    pipeline = stacks["Fmaj-Test-Pipeline"].template["Resources"]
    types = [r["Type"] for r in pipeline.values()]
    assert "AWS::StepFunctions::StateMachine" in types
    assert types.count("AWS::Lambda::Function") >= 4  # discover/investigate/aggregate/fail
