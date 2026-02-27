import json
import os
import boto3
import urllib.request

# Initialize AWS clients
s3 = boto3.client("s3")
sns = boto3.client("sns")
secrets_manager = boto3.client("secretsmanager")

# Fetch GITHUB_TOKEN from Secrets Manager
def get_github_token():
    try:
        response = secrets_manager.get_secret_value(SecretId="CBT_GITHUB_TOKEN")
        return response["SecretString"]
    except Exception as e:
        raise Exception(f"Failed to fetch GITHUB_TOKEN from Secrets Manager: {str(e)}")

# Environment variables (fallback to empty string if not set)
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "")

# Tag-based repo/project routing (using environment variables)
ROUTING = {
    "broadband": {
        "owner": GITHUB_OWNER,
        "repo": os.environ.get("BROADBAND_REPO_NAME", ""),
        "project_id": os.environ.get("BROADBAND_PROJECT_ID", "")
    },
    "video": {
        "owner": GITHUB_OWNER,
        "repo": os.environ.get("VIDEO_REPO_NAME", ""),
        "project_id": os.environ.get("VIDEO_PROJECT_ID", "")
    }
}

# ---------------- Lambda Entry Point ----------------
def lambda_handler(event, context):
    # Fetch GITHUB_TOKEN from Secrets Manager
    try:
        GITHUB_TOKEN = get_github_token()
    except Exception as e:
        print(f"Error: {str(e)}")
        return {"status": "failed", "error": str(e)}

    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    if not key.startswith("Input/") or not key.endswith(".json"):
        print(f"Skipping file: {key}")
        return {"status": "skipped"}

    try:
        body = fetch_s3_json(bucket, key)
        validate(body)
    except Exception as e:
        print(f"Validation failed: {e}")
        send_sns(f"Invalid JSON file: {key}\nError: {str(e)}")
        move_s3_file(bucket, key, "Invalid/")
        return {"status": "invalid", "error": str(e)}

    tag = body["tag"].lower().strip()
    if tag not in ROUTING:
        error_msg = f"Unsupported tag: {tag}"
        send_sns(f"Invalid tag in JSON file: {key}\nError: {error_msg}")
        move_s3_file(bucket, key, "Invalid/")
        return {"status": "invalid", "error": error_msg}

    target = ROUTING[tag]
    owner = target["owner"]
    repo = target["repo"]
    project_id = target["project_id"]

    title = body["title"]
    issue_body = build_issue_body(body)
    labels = [body["author"], tag]
    milestone_title = body["target_quarter"]

    try:
        issue_number, node_id = process_github_issue(owner, repo, title, issue_body, labels, milestone_title, GITHUB_TOKEN)
        add_issue_to_project(node_id, project_id, GITHUB_TOKEN)
        move_s3_file(bucket, key, "Processed/")
    except Exception as e:
        print(f"Error processing GitHub issue: {e}")
        send_sns(f"Error processing file: {key}\nError: {str(e)}")
        move_s3_file(bucket, key, "Invalid/")
        return {"status": "failed", "error": str(e)}

    return {"status": "success", "repo": f"{owner}/{repo}", "issue_number": issue_number}

# ---------------- S3 Helpers ----------------
def fetch_s3_json(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    return json.loads(content)

def move_s3_file(bucket, key, dest_folder):
    new_key = f"{dest_folder}{key.split('/')[-1]}"
    s3.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': key}, Key=new_key)
    s3.delete_object(Bucket=bucket, Key=key)
    print(f"Moved {key} -> {new_key}")

# ---------------- Validation ----------------
def validate(data):
    required = ["title", "intent_goal", "value", "target_quarter", "author", "tag"]
    for field in required:
        if field not in data or not data[field]:
            raise Exception(f"Missing or empty field: {field}")

# ---------------- Issue Body ----------------
def build_issue_body(data):
    return f"""
## 🎯 **Goal**
{data['intent_goal']}

## 💎 **Value**
{data['value']}
""".strip()

# ---------------- GitHub REST Helper ----------------
def github_request(url, method="GET", payload=None, token=None):
    data = None
    if payload:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

# ---------------- Issue Processing ----------------
def process_github_issue(owner, repo, title, body, labels, milestone_title, token):
    issue_number = find_existing_issue_by_title(owner, repo, title, token)
    if issue_number:
        node_id = update_issue(owner, repo, issue_number, body, labels, milestone_title, token)
    else:
        node_id, issue_number = create_issue(owner, repo, title, body, labels, milestone_title, token)
    return issue_number, node_id

def find_existing_issue_by_title(owner, repo, title, token):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=all&per_page=100"
    issues = github_request(url, token=token)
    for issue in issues:
        if issue.get("title") == title:
            return issue["number"]
    return None

def get_or_create_milestone(owner, repo, title, token):
    url = f"https://api.github.com/repos/{owner}/{repo}/milestones?state=all"
    milestones = github_request(url, token=token)
    for m in milestones:
        if m["title"] == title:
            return m["number"]
    payload = {"title": title}
    result = github_request(f"https://api.github.com/repos/{owner}/{repo}/milestones", method="POST", payload=payload, token=token)
    return result["number"]

def create_issue(owner, repo, title, body, labels, milestone_title, token):
    milestone_number = get_or_create_milestone(owner, repo, milestone_title, token)
    payload = {"title": title, "body": body, "labels": labels, "milestone": milestone_number}
    result = github_request(f"https://api.github.com/repos/{owner}/{repo}/issues", method="POST", payload=payload, token=token)
    return result["node_id"], result["number"]

def update_issue(owner, repo, issue_number, body, labels, milestone_title, token):
    milestone_number = get_or_create_milestone(owner, repo, milestone_title, token)
    payload = {"body": body, "labels": labels, "milestone": milestone_number}
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    result = github_request(url, method="PATCH", payload=payload, token=token)
    return result["node_id"]

# ---------------- GitHub GraphQL ----------------
def add_issue_to_project(issue_node_id, project_id, token):
    query = """
    mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: {
        projectId: $projectId,
        contentId: $contentId
      }) {
        item {
          id
        }
      }
    }
    """
    payload = {"query": query, "variables": {"projectId": project_id, "contentId": issue_node_id}}
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps(payload).encode("utf-8"),
        method="POST"
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if "errors" in result:
        raise Exception(f"GraphQL error: {result['errors']}")

# ---------------- SNS ----------------
def send_sns(message):
    sns.publish(TopicArn=SNS_TOPIC_ARN, Message=message)

