import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
for k, v in {
    "DB_CLUSTER_ARN": "arn:aws:rds:us-west-2:111111111111:cluster:x",
    "DB_SECRET_ARN": "arn:aws:secretsmanager:us-west-2:111111111111:secret:x",
    "DB_NAME": "claims",
    "INTAKE_BUCKET": "intake",
    "ALLOWED_ORIGIN": "https://main.example.amplifyapp.com",
}.items():
    os.environ.setdefault(k, v)
