"""Cognito user pool for people (providers and examiners). Self sign-up is off; admins create users."""

from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_cognito as cognito
from constructs import Construct


class UserAuth(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, prefix: str, removal: RemovalPolicy) -> None:
        super().__init__(scope, construct_id)
        self.user_pool = cognito.UserPool(
            self,
            "Users",
            user_pool_name=f"{prefix}-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
                fullname=cognito.StandardAttribute(required=False, mutable=True),
            ),
            # Set by administrators only; the app client below cannot write it.
            custom_attributes={"provider_id": cognito.StringAttribute(min_len=3, max_len=50, mutable=True)},
            password_policy=cognito.PasswordPolicy(
                min_length=12, require_digits=True, require_lowercase=True, require_uppercase=True, require_symbols=True
            ),
            mfa=cognito.Mfa.REQUIRED,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            feature_plan=cognito.FeaturePlan.PLUS,
            standard_threat_protection_mode=cognito.StandardThreatProtectionMode.FULL_FUNCTION,
            deletion_protection=removal == RemovalPolicy.RETAIN,
            removal_policy=removal,
        )
        for name, description in (
            ("providers", "Medical provider staff who submit claims for their organization"),
            ("examiners", "Claims examiners who review agent recommendations"),
        ):
            cognito.CfnUserPoolGroup(
                self,
                f"Group-{name}",
                user_pool_id=self.user_pool.user_pool_id,
                group_name=name,
                description=description,
            )

        read = cognito.ClientAttributes().with_standard_attributes(email=True, fullname=True, email_verified=True)
        read = read.with_custom_attributes("provider_id")
        # Cognito requires required attributes (email) to be writable; custom:provider_id stays admin-only.
        write = cognito.ClientAttributes().with_standard_attributes(fullname=True, email=True)
        self.web_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=f"{prefix}-web",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            prevent_user_existence_errors=True,
            read_attributes=read,
            write_attributes=write,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.hours(12),
            enable_token_revocation=True,
        )
