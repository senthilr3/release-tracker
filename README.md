# release-tracker


1. Lambda Entry Point (lambda_handler)
Trigger

Invoked when a new file is uploaded to an S3 bucket.
Workflow


Extract S3 Event Data

Gets the bucket name and file key from the S3 event.
Skips files not in the Input/ folder or not ending with .json.


Fetch and Validate JSON

Calls fetch_s3_json() to read the file from S3.
Calls validate() to ensure all required fields are present.


Route by Tag

Uses the ROUTING dictionary to map the JSON’s tag to a GitHub repo and project.
If the tag is invalid, sends an SNS notification and moves the file to Invalid/.


Process GitHub Issue

Calls process_github_issue() to create/update a GitHub issue.
Calls add_issue_to_project() to add the issue to a GitHub Project board.
On success, moves the file to Processed/.
On failure, sends an SNS alert and moves the file to Invalid/.


2. S3 Helpers
fetch_s3_json(bucket, key)

Purpose: Downloads and parses a JSON file from S3.
Input: S3 bucket name and file key.
Output: Parsed JSON object.
move_s3_file(bucket, key, dest_folder)

Purpose: Moves a file from one S3 folder to another (e.g., Input/ → Processed/ or Invalid/).
How: Copies the file to the destination and deletes the original.

3. Validation (validate(data))

Purpose: Ensures the JSON file contains all required fields.
Required Fields: title, intent_goal, value, target_quarter, author, tag.
Action: Raises an exception if any field is missing or empty.

4. Issue Body Construction (build_issue_body(data))

Purpose: Formats the JSON data into a Markdown string for the GitHub issue body.
Output: A string with sections for Goal and Value.

5. GitHub REST API Helpers (github_request)

Purpose: Generic function to interact with GitHub’s REST API.
Features:

Adds Authorization and Accept headers.
Supports GET, POST, and PATCH methods.
Handles JSON payloads and responses.


6. Issue Processing
process_github_issue(...)

Purpose: Orchestrates issue creation/updating.
Steps:

Checks if an issue with the same title already exists (find_existing_issue_by_title).
If it exists, updates it (update_issue).
If not, creates a new issue (create_issue).

find_existing_issue_by_title(owner, repo, title)

Purpose: Searches for an existing GitHub issue by title.
Output: Issue number if found, otherwise None.
get_or_create_milestone(owner, repo, title)

Purpose: Fetches or creates a GitHub milestone (e.g., "Q1 2026").
Output: Milestone number.
create_issue(...)

Purpose: Creates a new GitHub issue with the provided title, body, labels, and milestone.
Output: Issue node_id and number.
update_issue(...)

Purpose: Updates an existing GitHub issue.
Output: Updated issue node_id.

7. GitHub GraphQL (add_issue_to_project)

Purpose: Adds the issue to a GitHub Project board using GraphQL.
Input: Issue node_id and project project_id.
Action: Sends a GraphQL mutation to link the issue to the project.
Error Handling: Raises an exception if the GraphQL request fails.

8. SNS Notification (send_sns(message))

Purpose: Sends alerts to an SNS topic for errors or invalid files.
Input: Error message or notification.

Key Features

Tag-Based Routing: Directs JSON files to the correct GitHub repo/project based on the tag field.
Idempotency: Avoids duplicate issues by checking for existing titles.
Automatic Milestone Management: Creates milestones if they don’t exist.
Error Handling: Moves invalid files to Invalid/, sends SNS alerts, and logs errors.
S3 File Management: Organizes files into Processed/ or Invalid/ folders.
**
Call Flow Summary**

S3 Event → Lambda triggered.
Validation → Skips or processes the file.
GitHub Issue → Creates/updates issue and adds it to a project.
S3 Cleanup → Moves the file to Processed/ or Invalid/.
SNS Alerts → Notifies admins of errors.


