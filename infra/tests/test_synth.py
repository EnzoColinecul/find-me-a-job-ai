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

    # Api stack: HTTP API proxying a Mangum Lambda, with the search cap + CORS
    # origins wired through as env vars, and StopExecution granted (start alone
    # would 403 the Stop endpoint).
    api = stacks["Fmaj-Test-Api"].template["Resources"]
    api_types = [r["Type"] for r in api.values()]
    assert "AWS::ApiGatewayV2::Api" in api_types
    # (log_retention adds a helper Lambda, so match ours by its Mangum handler)
    fns = [
        r for r in api.values()
        if r["Type"] == "AWS::Lambda::Function"
        and r["Properties"].get("Handler") == "app.main.handler"
    ]
    assert len(fns) == 1
    env = fns[0]["Properties"]["Environment"]["Variables"]
    assert env["FMAJ_GLOBAL_MONTHLY_SEARCHES"] == str(TEST.monthly_search_cap)
    assert env["FMAJ_CORS_ORIGINS"] == TEST.cors_origins
    actions = [
        stmt["Action"]
        for res in api.values()
        if res["Type"] == "AWS::IAM::Policy"
        for stmt in res["Properties"]["PolicyDocument"]["Statement"]
    ]
    flat = [a for act in actions for a in (act if isinstance(act, list) else [act])]
    assert "states:StopExecution" in flat and "states:StartExecution" in flat
    assert env["FMAJ_LANGFUSE_SECRET"] == "fmaj/test/langfuse"

    # Langfuse: every pipeline Lambda knows where its keys are and may read them,
    # and no key value is ever baked into a template.
    pipeline_fns = [r for r in pipeline.values() if r["Type"] == "AWS::Lambda::Function"
                    and "fmaj_agent.handlers" in str(r["Properties"].get("Handler", ""))]
    assert len(pipeline_fns) == 4
    for fn in pipeline_fns:
        assert fn["Properties"]["Environment"]["Variables"]["FMAJ_LANGFUSE_SECRET"] == (
            "fmaj/test/langfuse")
    templates = str(pipeline) + str(api)
    assert "fmaj/test/langfuse" in templates
    assert "sk-lf-" not in templates and "LANGFUSE_SECRET_KEY" not in templates
