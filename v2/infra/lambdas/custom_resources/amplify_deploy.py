"""CloudFormation custom resource: deploy the pre-built web app to Amplify Hosting with a generated config.json.

Amplify manual deployments take a zip; API and Cognito ids are only known at deploy time, so this function adds
`config.json` (no secrets, only public identifiers) to the built asset before uploading.
"""

from __future__ import annotations

import io
import json
import time
import urllib.request
import zipfile
from typing import Any

import boto3

s3 = boto3.client("s3")
amplify = boto3.client("amplify")


def _bundle(bucket: str, key: str, config: dict[str, Any]) -> bytes:
    source = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename != "config.json":
                zout.writestr(item, zin.read(item.filename))
        zout.writestr("config.json", json.dumps(config, indent=2))
    return out.getvalue()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    props = event["ResourceProperties"]
    physical_id = f"{props['AppId']}/{props['BranchName']}"
    if event["RequestType"] == "Delete":
        return {"PhysicalResourceId": physical_id}

    archive = _bundle(props["AssetBucket"], props["AssetKey"], json.loads(props["Config"]))
    deployment = amplify.create_deployment(appId=props["AppId"], branchName=props["BranchName"])
    request = urllib.request.Request(
        deployment["zipUploadUrl"], data=archive, method="PUT", headers={"Content-Type": "application/zip"}
    )
    with urllib.request.urlopen(request, timeout=120) as resp:  # noqa: S310 - Amplify-issued pre-signed HTTPS URL
        if resp.status >= 300:
            raise RuntimeError(f"Upload failed with HTTP {resp.status}")
    job_id = deployment["jobId"]
    amplify.start_deployment(appId=props["AppId"], branchName=props["BranchName"], jobId=job_id)

    deadline = time.time() + 600
    while time.time() < deadline:
        status = amplify.get_job(appId=props["AppId"], branchName=props["BranchName"], jobId=job_id)["job"]["summary"][
            "status"
        ]
        if status == "SUCCEED":
            return {"PhysicalResourceId": physical_id, "Data": {"JobId": job_id}}
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Amplify deployment {job_id} {status}")
        time.sleep(10)
    raise TimeoutError(f"Amplify deployment {job_id} did not finish in time")
