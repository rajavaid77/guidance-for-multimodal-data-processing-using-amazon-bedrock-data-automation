"""VPC with isolated subnets only (no NAT, no internet). Aurora lives here; Lambdas reach it via the Data API."""

from __future__ import annotations

from aws_cdk import RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from constructs import Construct


class Network(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        key: kms.IKey,
        removal: RemovalPolicy,
        availability_zones: list[str],
    ) -> None:
        super().__init__(scope, construct_id)
        flow_logs = logs.LogGroup(
            self, "FlowLogs", retention=logs.RetentionDays.ONE_MONTH, encryption_key=key, removal_policy=removal
        )
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            availability_zones=availability_zones,
            nat_gateways=0,
            restrict_default_security_group=True,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24)
            ],
            flow_logs={
                "all": ec2.FlowLogOptions(
                    destination=ec2.FlowLogDestination.to_cloud_watch_logs(flow_logs),
                    traffic_type=ec2.FlowLogTrafficType.ALL,
                )
            },
        )
