"""Bedrock Data Automation: five custom blueprints, four AWS-managed ones, and a project with document splitting."""

from __future__ import annotations

import json
from pathlib import Path

from aws_cdk import Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from constructs import Construct

BLUEPRINT_DIR = Path(__file__).resolve().parents[3] / "blueprints"
# Blueprint name suffixes are matched by lambdas/workflow/bda_output.py:classify()
BLUEPRINTS = {
    "cms1500": "cms1500.json",
    "medical-record": "medical_record.json",
    "lab-report": "lab_report.json",
    "primary-eob": "primary_payer_eob.json",
    "discharge-summary": "discharge_summary.json",
}
# AWS-managed blueprints, referenced by ARN (not created by this stack). Names are matched in bda_output.py:classify().
BUILT_IN_BLUEPRINTS = (
    "bedrock-data-automation-public-us-medical-insurance-card",
    "bedrock-data-automation-public-prescription-label",
    "bedrock-data-automation-public-us-driver-license",
    "bedrock-data-automation-public-invoice",
)
PROFILE_REGIONS = ("us-east-1", "us-east-2", "us-west-1", "us-west-2")


class DocumentAutomation(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, prefix: str, key: kms.IKey, profile: str) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        self.blueprints: dict[str, bedrock.CfnBlueprint] = {}
        for suffix, file_name in BLUEPRINTS.items():
            self.blueprints[suffix] = bedrock.CfnBlueprint(
                self,
                f"Blueprint-{suffix}",
                blueprint_name=f"{prefix}-{suffix}",
                type="DOCUMENT",
                schema=json.loads((BLUEPRINT_DIR / file_name).read_text()),
                kms_key_id=key.key_arn,
            )
        self.built_in_blueprint_arns = [
            f"arn:{stack.partition}:bedrock:{stack.region}:aws:blueprint/{name}" for name in BUILT_IN_BLUEPRINTS
        ]
        P = bedrock.CfnDataAutomationProject
        self.project = P(
            self,
            "Project",
            project_name=f"{prefix}-claims",
            project_description="CMS-1500 claim packets: split, classify, extract claim form and supporting evidence",
            kms_key_id=key.key_arn,
            standard_output_configuration=P.StandardOutputConfigurationProperty(
                document=P.DocumentStandardOutputConfigurationProperty(
                    extraction=P.DocumentStandardExtractionProperty(
                        granularity=P.DocumentExtractionGranularityProperty(types=["PAGE", "ELEMENT"]),
                        bounding_box=P.DocumentBoundingBoxProperty(state="ENABLED"),
                    ),
                    generative_field=P.DocumentStandardGenerativeFieldProperty(state="DISABLED"),
                    output_format=P.DocumentOutputFormatProperty(
                        text_format=P.DocumentOutputTextFormatProperty(types=["MARKDOWN"]),
                        additional_file_format=P.DocumentOutputAdditionalFileFormatProperty(state="DISABLED"),
                    ),
                )
            ),
            custom_output_configuration=P.CustomOutputConfigurationProperty(
                blueprints=[
                    P.BlueprintItemProperty(blueprint_arn=bp.attr_blueprint_arn, blueprint_stage="LIVE")
                    for bp in self.blueprints.values()
                ]
                + [
                    P.BlueprintItemProperty(blueprint_arn=arn, blueprint_stage="LIVE")
                    for arn in self.built_in_blueprint_arns
                ]
            ),
            override_configuration=P.OverrideConfigurationProperty(
                document=P.DocumentOverrideConfigurationProperty(
                    splitter=P.SplitterConfigurationProperty(state="ENABLED")
                )
            ),
        )
        self.profile_arn = (
            f"arn:{stack.partition}:bedrock:{stack.region}:{stack.account}:data-automation-profile/{profile}"
        )
        self._profile = profile

    def grant_invoke(self, grantee: iam.IGrantable) -> None:
        stack = Stack.of(self)
        iam.Grant.add_to_principal(
            grantee=grantee,
            actions=["bedrock:InvokeDataAutomationAsync", "bedrock:GetDataAutomationStatus"],
            resource_arns=[
                self.project.attr_project_arn,
                *[bp.attr_blueprint_arn for bp in self.blueprints.values()],
                *self.built_in_blueprint_arns,
                *[
                    f"arn:{stack.partition}:bedrock:{r}:{stack.account}:data-automation-profile/{self._profile}"
                    for r in PROFILE_REGIONS
                ],
                f"arn:{stack.partition}:bedrock:{stack.region}:{stack.account}:data-automation-invocation/*",
            ],
        )
        # Jobs are tagged with the claim id at creation.
        iam.Grant.add_to_principal(
            grantee=grantee,
            actions=["bedrock:TagResource"],
            resource_arns=[
                f"arn:{stack.partition}:bedrock:{stack.region}:{stack.account}:data-automation-invocation/*"
            ],
        )
