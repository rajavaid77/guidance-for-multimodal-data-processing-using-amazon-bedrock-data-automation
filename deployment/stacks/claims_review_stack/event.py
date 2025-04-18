from aws_cdk import (
    aws_rds as rds,
    aws_s3 as s3,
    aws_events as events,
    aws_events_targets as targets,
    aws_lambda as _lambda,
    Duration,
)

from constructs import Construct

class Event(Construct):
    def __init__(self, scope: Construct, construct_id: str,
                 claims_submission_bucket:s3.Bucket,
                 claims_review_bucket:s3.Bucket,
                 database_cluster:rds.DatabaseCluster,
                 database_name:str,
                 **kwargs) -> None:

        super().__init__(scope, construct_id, **kwargs)        

        log_claims_event_function = self.create_log_claims_event_function(cluster=database_cluster,
            database_name=database_name)

        self.create_eventbridge_rule_for_claim_events(
             claims_submission_bucket=claims_submission_bucket, 
             claims_review_bucket=claims_review_bucket,
             log_claims_event_function=log_claims_event_function
        )


    def create_log_claims_event_function(self, 
            cluster:rds.DatabaseCluster,
            database_name:str):
        
        log_claims_event_function = _lambda.Function(
            self, 'log_claims_event',
            runtime=_lambda.Runtime.PYTHON_3_10,
            code=_lambda.Code.from_asset('lambda/claims_review/claims_event'),
            handler='index.lambda_handler',
            timeout=Duration.seconds(300),
            environment={
                "CLAIMS_DB_CLUSTER_ARN": cluster.cluster_arn,
                "CLAIMS_DB_CREDENTIALS_SECRET_ARN": cluster.secret.secret_arn,
                "CLAIMS_DB_DATABASE_NAME": database_name,
            }
        )

        cluster.secret.grant_read(log_claims_event_function)
        cluster.grant_data_api_access(log_claims_event_function)
        return log_claims_event_function
    

    def create_eventbridge_rule_for_claim_events(self, 
                                                 claims_submission_bucket: s3.Bucket,
                                                 claims_review_bucket: s3.Bucket,
                                                 log_claims_event_function: _lambda.Function):
        # Create an EventBridge rule.
            claim_event_form_submitted_rule = events.Rule(self, "claim_event_form_submitted",
                event_pattern=events.EventPattern(
                    source= ["aws.s3"],
                    detail_type=["Object Created", "Object Updated"],
                    detail= {
                        "bucket": {
                            "name": [claims_submission_bucket.bucket_name]
                        }
                    }
                )
            )
            claim_event_form_submitted_rule.add_target(
                targets.LambdaFunction(
                    handler=log_claims_event_function,
                    max_event_age=Duration.hours(2),
                    retry_attempts=2
                )                 
            )
            claim_event_bda_job_started_rule = events.Rule(self, "claim_event_bda_job_started",
                event_pattern=events.EventPattern(
                    source= ["aws.bedrock"],
                    detail_type=["Bedrock Data Automation Job Created"]
                )
            )
            claim_event_bda_job_failed_rule = events.Rule(self, "claim_event_bda_job_failed",
                event_pattern=events.EventPattern(
                    source= ["aws.bedrock"],
                    detail_type=["Bedrock Data Automation Job Failed With Service Error",
                                 "Bedrock Data Automation Job Failed With Client Error"]
                )
            )
            claim_event_bda_job_succeeded_rule = events.Rule(self, "claim_event_bda_job_succeeded",
                event_pattern=events.EventPattern(
                    source= ["aws.bedrock"],
                    detail_type=["Bedrock Data Automation Job Succeeded"]
                )
            )
            claim_event_bda_job_succeeded_rule = events.Rule(self, "claim_event_agent_invoked",
                event_pattern=events.EventPattern(
                    source= ["aws.s3"],
                    detail_type=["Object Created"],
                    detail= {
                        "bucket": {
                            "name": [claims_submission_bucket.bucket_name]
                        }
                    }
                )
            )
            claim_event_bda_job_succeeded_rule = events.Rule(self, "claim_event_report_available",
                event_pattern=events.EventPattern(
                    source= ["aws.s3"],
                    detail_type=["Object Created"],
                    detail= {
                        "bucket": {
                            "name": [claims_review_bucket.bucket_name]
                        },
                        "object": {
                             "key": [{
                                  "suffix": "claim_output.json"
                            }]
                        }                        
                    }
                )
            )
