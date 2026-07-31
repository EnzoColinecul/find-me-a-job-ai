"""Cognito user pool with Google federated IdP (per stage).

The Google OAuth client is created manually in the GCP console (Terraform can't create
generic web OAuth clients). Its outputs must exist BEFORE deploying this stack:
  - SSM param  /fmaj/{stage}/google-client-id     (plain string; client id is public)
  - Secret     fmaj/{stage}/google-client-secret  (plaintext client secret)
See docs/google-login-setup.md.
"""
import aws_cdk as cdk
from aws_cdk import aws_cognito as cognito, aws_ssm as ssm
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
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
                fullname=cognito.StandardAttribute(required=False, mutable=True),
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY
            if config.stage == "test"
            else cdk.RemovalPolicy.RETAIN,
        )

        self.domain = self.user_pool.add_domain(
            "HostedDomain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"fmaj-{config.stage}"),
        )

        # client id is not secret -> plain SSM param resolved at deploy
        google_client_id = ssm.StringParameter.value_for_string_parameter(
            self, config.google_client_id_param
        )

        google_idp = cognito.UserPoolIdentityProviderGoogle(
            self,
            "GoogleIdP",
            user_pool=self.user_pool,
            client_id=google_client_id,
            client_secret_value=cdk.SecretValue.secrets_manager(config.google_client_secret_name),
            scopes=["openid", "email", "profile"],
            attribute_mapping=cognito.AttributeMapping(
                email=cognito.ProviderAttribute.GOOGLE_EMAIL,
                fullname=cognito.ProviderAttribute.GOOGLE_NAME,
            ),
        )

        self.client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=f"fmaj-{config.stage}-web",
            generate_secret=False,  # public SPA client -> PKCE
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.GOOGLE,
            ],
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=config.callback_urls,
                logout_urls=config.logout_urls,
            ),
        )
        # hosted UI only shows Google once the IdP exists
        self.client.node.add_dependency(google_idp)

        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=self.client.user_pool_client_id)
        cdk.CfnOutput(self, "CognitoDomain", value=self.domain.base_url())
