# Functional Test

This test validates core Braintrust API functionality with create/read coverage, then cleans up all created resources.

## Create And Read Coverage

- `POST /v1/project` creates a project for the test run.
- `GET /v1/project/{project_id}` verifies the project can be read.
- `POST /v1/project_logs/{project_id}/insert` inserts project log events.
- `GET /v1/project_logs/{project_id}/fetch` verifies project log events can be fetched.
- `POST /v1/role` creates a role.
- `GET /v1/role/{role_id}` verifies the role can be read.
- `POST /v1/group` creates a group.
- `GET /v1/group/{group_id}` verifies the group can be read.
- `POST /v1/dataset` creates a dataset metadata object; no dataset events are inserted.
- `GET /v1/dataset/{dataset_id}` verifies the dataset can be read.
- `POST /v1/experiment` creates an experiment.
- `GET /v1/experiment/{experiment_id}` verifies the experiment can be read.
- `POST /v1/prompt` creates a prompt.
- `GET /v1/prompt/{prompt_id}` verifies the prompt can be read.
- `POST /v1/acl` creates a project ACL granting read permission to the test group.
- `GET /v1/acl/{acl_id}` verifies the ACL can be read.
- `POST /v1/project_automation` creates a project automation rule with a webhook action.
- `GET /v1/project_automation/{project_automation_id}` verifies the automation can be read.
- `POST /v1/project_score` creates a project score.
- `GET /v1/project_score/{project_score_id}` verifies the score can be read.
- `POST /v1/project_tag` creates a project tag.
- `GET /v1/project_tag/{project_tag_id}` verifies the tag can be read.
- `POST /v1/function` creates a function.
- `GET /v1/function/{function_id}` verifies the function can be read.
- `POST /v1/view` creates a view scoped to the project.
- `GET /v1/view/{view_id}` verifies the view can be read.
- `POST /v1/api_key` creates an API key.
- `GET /v1/api_key/{api_key_id}` verifies the API key can be read.
- `POST /v1/env_var` creates a project-scoped environment variable.
- `GET /v1/env_var/{env_var_id}` verifies the environment variable can be read.
- `POST /environment` creates an environment.
- `GET /environment/{environment_id}` verifies the environment can be read.

## Cleanup Coverage

- `DELETE /v1/env_var/{env_var_id}` deletes the environment variable.
- `DELETE /environment/{environment_id}` deletes the environment.
- `DELETE /v1/api_key/{api_key_id}` deletes the API key.
- `DELETE /v1/view/{view_id}` deletes the view.
- `DELETE /v1/function/{function_id}` deletes the function.
- `DELETE /v1/project_tag/{project_tag_id}` deletes the project tag.
- `DELETE /v1/project_score/{project_score_id}` deletes the project score.
- `DELETE /v1/project_automation/{project_automation_id}` deletes the automation.
- `DELETE /v1/acl/{acl_id}` deletes the ACL.
- `DELETE /v1/prompt/{prompt_id}` deletes the prompt.
- `DELETE /v1/experiment/{experiment_id}` deletes the experiment.
- `DELETE /v1/dataset/{dataset_id}` deletes the dataset.
- `DELETE /v1/group/{group_id}` deletes the group.
- `DELETE /v1/role/{role_id}` deletes the role.
- `DELETE /v1/project/{project_id}` deletes the project last.
