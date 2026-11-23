"""Step Functions claim workflow, EventBridge triggers and examiner notifications."""

from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from .agents import Agents
from .database import Database
from .functions import FunctionFactory
from .idp import DocumentAutomation

J = sfn.JsonPath


class Workflow(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: dict,
        key: kms.IKey,
        intake: s3.IBucket,
        bda_output: s3.IBucket,
        database: Database,
        idp: DocumentAutomation,
        agents: Agents,
        functions: FunctionFactory,
        app_url: str,
        removal: RemovalPolicy,
    ) -> None:
        super().__init__(scope, construct_id)
        db_env = database.data_api_env()

        self.topic = sns.Topic(
            self, "ReviewTopic", display_name="Claims ready for review", master_key=key, enforce_ssl=True
        )
        if config.get("examiner_notification_email"):
            self.topic.add_subscription(subs.EmailSubscription(config["examiner_notification_email"]))

        def fn(name: str, handler: str, description: str, extra: dict | None = None, **kwargs):
            f = functions.create(
                self, name, handler=handler, description=description, environment={**db_env, **(extra or {})}, **kwargs
            )
            database.grant_data_api(f)
            return f

        start_bda = fn(
            "StartBda",
            "workflow.start_bda.handler",
            "Starts BDA jobs for every document of a claim",
            {
                "INTAKE_BUCKET": intake.bucket_name,
                "BDA_OUTPUT_BUCKET": bda_output.bucket_name,
                "BDA_PROJECT_ARN": idp.project.attr_project_arn,
                "BDA_PROFILE_ARN": idp.profile_arn,
                "KMS_KEY_ARN": key.key_arn,
            },
        )
        idp.grant_invoke(start_bda)
        intake.grant_read(start_bda)
        bda_output.grant_read_write(start_bda)
        key.grant_encrypt_decrypt(start_bda)
        # BDA with a customer managed key: the caller lets BDA create a grant, only via the Bedrock service.
        start_bda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["kms:CreateGrant", "kms:DescribeKey", "kms:GenerateDataKey", "kms:Decrypt"],
                resources=[key.key_arn],
                conditions={
                    "StringEquals": {"kms:ViaService": f"bedrock.{Stack.of(self).region}.amazonaws.com"},
                },
            )
        )

        bda_callback = fn(
            "BdaCallback",
            "workflow.bda_callback.handler",
            "Resumes the workflow when BDA jobs finish",
            {"INTAKE_BUCKET": intake.bucket_name},
        )
        assemble = fn(
            "AssembleCase",
            "workflow.assemble_case.handler",
            "Builds the claim case from BDA output",
            {
                "BDA_OUTPUT_BUCKET": bda_output.bucket_name,
                "CONFIDENCE_THRESHOLD": str(config["extraction_confidence_threshold"]),
            },
            timeout=Duration.minutes(5),
            memory_size=1024,
        )
        bda_output.grant_read_write(assemble)
        invoke = fn(
            "InvokeAgent",
            "workflow.invoke_agent.handler",
            "Invokes the claims reviewer on AgentCore Runtime",
            {
                "BDA_OUTPUT_BUCKET": bda_output.bucket_name,
                "AGENT_RUNTIME_ARN": agents.runtime.agent_runtime_arn,
                "RUNTIME_USER_ID": "claims-workflow",
                "AUTO_APPROVE_MIN_CONFIDENCE": str(config["auto_approve_min_confidence"]),
                "AUTO_APPROVE_MAX_AMOUNT": str(config["auto_approve_max_amount"]),
            },
            timeout=Duration.minutes(15),
            memory_size=512,
        )
        bda_output.grant_read_write(invoke)
        agents.runtime.grant_invoke(invoke)
        request_review = fn(
            "RequestReview",
            "workflow.request_review.handler",
            "Queues a claim for examiner review",
            {"REVIEW_TOPIC_ARN": self.topic.topic_arn, "APP_URL": app_url},
        )
        self.topic.grant_publish(request_review)
        finalize = fn("Finalize", "workflow.finalize.handler", "Records the final claim decision")
        mark_failed = fn("MarkFailed", "workflow.mark_failed.handler", "Marks a claim FAILED")

        # ---------- state machine ----------
        failed = sfn.Fail(self, "ClaimFailed", error="ClaimProcessingFailed")
        on_error = tasks.LambdaInvoke(
            self,
            "MarkClaimFailed",
            lambda_function=mark_failed,
            payload=sfn.TaskInput.from_object({"claim_id": J.string_at("$.claim_id"), "error": J.object_at("$.error")}),
            result_path=J.DISCARD,
        ).next(failed)

        def catch(state):
            state.add_catch(on_error, errors=["States.ALL"], result_path="$.error")
            return state

        def retry(state):
            state.add_retry(
                errors=[
                    "Lambda.ServiceException",
                    "Lambda.AWSLambdaException",
                    "Lambda.SdkClientException",
                    "Lambda.TooManyRequestsException",
                ],
                interval=Duration.seconds(2),
                max_attempts=3,
                backoff_rate=2,
            )
            return state

        parse = sfn.Pass(
            self,
            "ParseClaimId",
            parameters={
                "key.$": "$.detail.object.key",
                "claim_id.$": "States.ArrayGetItem(States.StringSplit($.detail.object.key, '/'), 1)",
            },
        )
        extract = catch(
            retry(
                tasks.LambdaInvoke(
                    self,
                    "ExtractWithBDA",
                    lambda_function=start_bda,
                    integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
                    payload=sfn.TaskInput.from_object(
                        {
                            "task_token": J.task_token,
                            "key": J.string_at("$.key"),
                            "execution_arn": J.string_at("$$.Execution.Id"),
                        }
                    ),
                    task_timeout=sfn.Timeout.duration(Duration.hours(1)),
                    result_path="$.bda",
                )
            )
        )
        assemble_task = catch(
            retry(
                tasks.LambdaInvoke(
                    self,
                    "AssembleClaimCase",
                    lambda_function=assemble,
                    payload=sfn.TaskInput.from_object({"claim_id": J.string_at("$.claim_id")}),
                    payload_response_only=True,
                    result_path="$.case",
                )
            )
        )
        agent_task = tasks.LambdaInvoke(
            self,
            "AgenticReview",
            lambda_function=invoke,
            payload=sfn.TaskInput.from_object(
                {"claim_id": J.string_at("$.claim_id"), "case_key": J.string_at("$.case.case_key")}
            ),
            payload_response_only=True,
            result_path="$.agent",
        )
        retry(agent_task).add_retry(errors=["States.TaskFailed"], interval=Duration.seconds(30), max_attempts=1)
        catch(agent_task)

        finalize_auto = catch(
            retry(
                tasks.LambdaInvoke(
                    self,
                    "AutoFinalize",
                    lambda_function=finalize,
                    payload=sfn.TaskInput.from_object(
                        {
                            "claim_id": J.string_at("$.claim_id"),
                            "decision": J.string_at("$.agent.decision"),
                            "line_decisions": J.object_at("$.agent.line_decisions"),
                            "reason": J.string_at("$.agent.route_reason"),
                            "decided_by": "AUTO",
                            "actor": "workflow",
                        }
                    ),
                    result_path=J.DISCARD,
                )
            )
        )
        review = catch(
            retry(
                tasks.LambdaInvoke(
                    self,
                    "HumanReview",
                    lambda_function=request_review,
                    integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
                    payload=sfn.TaskInput.from_object(
                        {
                            "task_token": J.task_token,
                            "claim_id": J.string_at("$.claim_id"),
                            "decision": J.string_at("$.agent.decision"),
                            "route_reason": J.string_at("$.agent.route_reason"),
                        }
                    ),
                    task_timeout=sfn.Timeout.duration(Duration.days(int(config["review_timeout_days"]))),
                    result_path="$.review",
                )
            )
        )
        finalize_review = catch(
            retry(
                tasks.LambdaInvoke(
                    self,
                    "FinalizeExaminerDecision",
                    lambda_function=finalize,
                    payload=sfn.TaskInput.from_object(
                        {
                            "claim_id": J.string_at("$.claim_id"),
                            "decision": J.string_at("$.review.decision"),
                            "line_decisions": J.object_at("$.review.line_decisions"),
                            "reason": J.string_at("$.review.reason"),
                            "decided_by": "EXAMINER",
                            "actor": J.string_at("$.review.actor"),
                        }
                    ),
                    result_path=J.DISCARD,
                )
            )
        )
        done = sfn.Succeed(self, "ClaimClosed")
        route = (
            sfn.Choice(self, "Route")
            .when(sfn.Condition.string_equals("$.agent.route", "AUTO"), finalize_auto.next(done))
            .otherwise(review.next(finalize_review).next(done))
        )
        definition = parse.next(extract).next(assemble_task).next(agent_task).next(route)

        sfn_logs = logs.LogGroup(
            self, "StateMachineLogs", retention=logs.RetentionDays.ONE_MONTH, encryption_key=key, removal_policy=removal
        )
        self.state_machine = sfn.StateMachine(
            self,
            "ClaimWorkflow",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.days(int(config["review_timeout_days"]) + 1),
            tracing_enabled=True,
            logs=sfn.LogOptions(destination=sfn_logs, level=sfn.LogLevel.ERROR, include_execution_data=False),
            encryption_configuration=sfn.CustomerManagedEncryptionConfiguration(key),
        )
        self.state_machine.grant_task_response(bda_callback)
        # Executions are encrypted with the CMK: everything that starts, runs or resumes them needs data-key access.
        key.grant_encrypt_decrypt(self.state_machine.role)
        key.grant_encrypt_decrypt(bda_callback)
        events_role = iam.Role(self, "StartExecutionRole", assumed_by=iam.ServicePrincipal("events.amazonaws.com"))
        self.state_machine.grant_start_execution(events_role)
        key.grant_encrypt_decrypt(events_role)

        # ---------- triggers ----------
        dlq = sqs.Queue(
            self,
            "EventsDlq",
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=key,
            enforce_ssl=True,
            retention_period=Duration.days(14),
        )
        events.Rule(
            self,
            "ClaimSubmitted",
            description="Start the claim workflow when a provider submits a claim",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created"],
                detail={
                    "bucket": {"name": [intake.bucket_name]},
                    "object": {"key": [{"wildcard": "claims/*/submit.json"}]},
                },
            ),
            targets=[
                targets.SfnStateMachine(self.state_machine, dead_letter_queue=dlq, retry_attempts=3, role=events_role)
            ],
        )
        events.Rule(
            self,
            "BdaJobFinished",
            description="Resume the claim workflow when a BDA job finishes",
            event_pattern=events.EventPattern(
                source=["aws.bedrock"],
                detail_type=[
                    "Bedrock Data Automation Job Succeeded",
                    "Bedrock Data Automation Job Failed With Client Error",
                    "Bedrock Data Automation Job Failed With Service Error",
                ],
                detail={"input_s3_object": {"s3_bucket": [intake.bucket_name]}},
            ),
            targets=[
                targets.LambdaFunction(
                    bda_callback, dead_letter_queue=dlq, retry_attempts=3, max_event_age=Duration.hours(2)
                )
            ],
        )
        self.state_machine_arn = self.state_machine.state_machine_arn
