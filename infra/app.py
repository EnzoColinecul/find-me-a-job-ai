#!/usr/bin/env python3
"""CDK entrypoint — two isolated stages in account 418862088910 (ap-southeast-2).

Deploys are made assuming arn:aws:iam::418862088910:role/find-me-a-job-ai_role:
    cdk deploy 'Fmaj-Test/*' --profile fmaj-deploy
"""
import aws_cdk as cdk

from fmaj.config import PROD, TEST
from fmaj.stage import FmajStage

app = cdk.App()

env = cdk.Environment(account="418862088910", region="ap-southeast-2")

FmajStage(app, "Fmaj-Test", config=TEST, env=env)
FmajStage(app, "Fmaj-Prod", config=PROD, env=env)

app.synth()
