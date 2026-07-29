"""Cognito user pool with Google federated IdP (per stage).

Google OAuth client IDs/secrets come from GCP IaC (infra/gcp) and are stored in
Secrets Manager as fmaj/{stage}/google-oauth before deploying this stack.
"""
import aws_cdk as cdk
from aws_cdk import aws_cognito as cognito
from constructs import Construct

from fmaj.config import StageConfig


class AuthStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, config: StageConfig, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"fmaj-{config.stage}",
            self_sign_up_enabled=False,  # Google IdP only
            removal_policy=cdk.RemovalPolicy.DESTROY
            if config.stage == "test"
            else cdk.RemovalPolicy.RETAIN,
        )

        self.domain = self.user_pool.add_domain(
            "HostedDomain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"fmaj-{config.stage}"),
        )

        # TODO(Notion: "Cognito + Google login"): add Google IdP
        #   cognito.UserPoolIdentityProviderGoogle(... client id/secret from
        #   Secrets Manager fmaj/{stage}/google-oauth, scopes: openid email profile)
        # TODO: app client (PKCE, no secret) with callback URLs per stage

        self.client = self.user_pool.add_client(
            "WebClient",
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                callback_urls=[config.cors_origins + "/auth/callback"],
            ),
        )
