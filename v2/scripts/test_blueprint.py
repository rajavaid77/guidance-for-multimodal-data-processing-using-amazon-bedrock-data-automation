#!/usr/bin/env python3
"""Run the deployed BDA project on one document and print the custom output with confidences.

Uploads to the intake bucket under blueprint-tests/ (outside claims/, so no workflow is triggered).
Usage: python test_blueprint.py path/to/document.pdf [--stack agentic-claims-v2] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import boto3


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("document")
    p.add_argument("--stack", default="agentic-claims-v2")
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--json", help="write the full custom output(s) to this file")
    args = p.parse_args()

    session = boto3.Session(region_name=args.region)
    cfn, s3 = session.client("cloudformation"), session.client("s3")
    bda = session.client("bedrock-data-automation-runtime")
    outputs = {
        o["OutputKey"]: o["OutputValue"] for o in cfn.describe_stacks(StackName=args.stack)["Stacks"][0]["Outputs"]
    }
    resources = [
        {
            "ResourceType": r["ResourceType"],
            "PhysicalResourceId": r["PhysicalResourceId"],
            "LogicalResourceId": r["LogicalResourceId"],
        }
        for page in cfn.get_paginator("list_stack_resources").paginate(StackName=args.stack)
        for r in page["StackResourceSummaries"]
    ]
    project_arn = next(
        r["PhysicalResourceId"] for r in resources if r["ResourceType"] == "AWS::Bedrock::DataAutomationProject"
    )
    key_arn = next(r["PhysicalResourceId"] for r in resources if r["ResourceType"] == "AWS::KMS::Key")
    account = session.client("sts").get_caller_identity()["Account"]
    bucket = outputs["IntakeBucket"]
    out_bucket = next(
        r["PhysicalResourceId"]
        for r in resources
        if r["LogicalResourceId"].startswith("StorageBdaOutput") and r["ResourceType"] == "AWS::S3::Bucket"
    )

    run = uuid.uuid4().hex[:8]
    key = f"blueprint-tests/{run}/{Path(args.document).name}"
    s3.upload_file(args.document, bucket, key, ExtraArgs={"ContentType": "application/pdf"})
    inv = bda.invoke_data_automation_async(
        inputConfiguration={"s3Uri": f"s3://{bucket}/{key}"},
        outputConfiguration={"s3Uri": f"s3://{out_bucket}/blueprint-tests/{run}"},
        dataAutomationConfiguration={
            "dataAutomationProjectArn": project_arn,
            "stage": "LIVE",
        },
        dataAutomationProfileArn=f"arn:aws:bedrock:{args.region}:{account}:data-automation-profile/us.data-automation-v1",
        encryptionConfiguration={"kmsKeyId": key_arn},
    )["invocationArn"]
    while True:
        status = bda.get_data_automation_status(invocationArn=inv)
        if status["status"] not in ("Created", "InProgress"):
            break
        time.sleep(5)
    if status["status"] != "Success":
        raise SystemExit(f"BDA job {status['status']}: {status.get('errorMessage')}")

    meta_uri = urlparse(status["outputConfiguration"]["s3Uri"])
    meta = json.loads(s3.get_object(Bucket=meta_uri.netloc, Key=meta_uri.path.lstrip("/"))["Body"].read())
    results = []
    for seg in meta["output_metadata"][0]["segment_metadata"]:
        if not seg.get("custom_output_path"):
            print("segment without custom output (no blueprint matched)")
            continue
        u = urlparse(seg["custom_output_path"])
        out = json.loads(s3.get_object(Bucket=u.netloc, Key=u.path.lstrip("/"))["Body"].read())
        results.append(out)
        mb = out.get("matched_blueprint", {})
        print(
            f"\n== {mb.get('name')} ({mb.get('confidence', 0):.2f}) pages {out.get('split_document', {}).get('page_indices')}"
        )
        inf, ex = (
            out.get("inference_result", {}),
            (out.get("explainability_info") or [{}])[0],
        )
        for name in sorted(inf):
            if isinstance(inf[name], list):
                print(f"  {name}:")
                for i, item in enumerate(inf[name]):
                    conf = ex.get(name, [{}] * (i + 1))[i] if isinstance(ex.get(name), list) else {}
                    cells = ", ".join(
                        f"{k}={v!r}({(conf.get(k) or {}).get('confidence', 0):.2f})"
                        for k, v in item.items()
                        if v not in ("", None)
                    )
                    print(f"    [{i + 1}] {cells}")
            elif inf[name] not in ("", None):
                print(f"  {name} = {inf[name]!r} ({(ex.get(name) or {}).get('confidence', 0):.2f})")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
