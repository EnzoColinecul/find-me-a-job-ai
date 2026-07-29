"""Smoke test: both stages synthesize without errors."""
import aws_cdk as cdk

from fmaj.config import PROD, TEST
from fmaj.stage import FmajStage


def test_stages_synth() -> None:
    app = cdk.App()
    env = cdk.Environment(account="418862088910", region="ap-southeast-2")
    FmajStage(app, "Fmaj-Test", config=TEST, env=env)
    FmajStage(app, "Fmaj-Prod", config=PROD, env=env)
    assembly = app.synth()
    assert {s.artifact_id for s in assembly.artifacts_recursively if hasattr(s, "template")}
