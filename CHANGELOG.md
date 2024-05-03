# Changelog

## [0.95.0](https://github.com/reanahub/reana-workflow-controller/compare/0.9.3...0.95.0) (2024-05-03)


### Features

* **k8s:** set custom ingressClassName for interactive sessions ([#581](https://github.com/reanahub/reana-workflow-controller/issues/581)) ([13d1c5d](https://github.com/reanahub/reana-workflow-controller/commit/13d1c5d6e5253998b56f2658d560835a79fe5252))


### Continuous integration

* **actions:** update GitHub actions due to Node 16 deprecation ([#579](https://github.com/reanahub/reana-workflow-controller/issues/579)) ([57a0246](https://github.com/reanahub/reana-workflow-controller/commit/57a0246ceedef2a724c98b3993b79e688e2d1ac2))


### Documentation

* **openapi:** amend response description for file deletion ([#573](https://github.com/reanahub/reana-workflow-controller/issues/573)) ([1d027ff](https://github.com/reanahub/reana-workflow-controller/commit/1d027ffeafc437fc9e0c2a4193a9e2585231ab2a))


### Chores

* **master:** release 0.95.0-alpha.1 ([9ebbf2a](https://github.com/reanahub/reana-workflow-controller/commit/9ebbf2a3b7f0dbebaa23a0fbb26516920fe31759))

## [0.9.3](https://github.com/reanahub/reana-workflow-controller/compare/0.9.2...0.9.3) (2024-03-04)


### Build

* **docker:** non-editable submodules in "latest" mode ([#551](https://github.com/reanahub/reana-workflow-controller/issues/551)) ([af74d0b](https://github.com/reanahub/reana-workflow-controller/commit/af74d0b887d02109ce96c91ef8fdf99e4eb4ff34))
* **python:** bump all required packages as of 2024-03-04 ([#574](https://github.com/reanahub/reana-workflow-controller/issues/574)) ([1373f4c](https://github.com/reanahub/reana-workflow-controller/commit/1373f4c3ea9480cc7ccb05ab12fc62a029e1f792))
* **python:** bump shared REANA packages as of 2024-03-04 ([#574](https://github.com/reanahub/reana-workflow-controller/issues/574)) ([e31d903](https://github.com/reanahub/reana-workflow-controller/commit/e31d9038280a68ff84595caa64f010a4f25fc63a))


### Features

* **manager:** call shutdown endpoint before workflow stop ([#559](https://github.com/reanahub/reana-workflow-controller/issues/559)) ([719fa37](https://github.com/reanahub/reana-workflow-controller/commit/719fa370839dd29ce8071b2d1e203ff37c5ff4f1))
* **manager:** increase termination period of run-batch pods ([#572](https://github.com/reanahub/reana-workflow-controller/issues/572)) ([f05096a](https://github.com/reanahub/reana-workflow-controller/commit/f05096ac7d5c6e7a535772966ccbbb2e07a325ef))
* **manager:** pass custom env variables to job controller ([#571](https://github.com/reanahub/reana-workflow-controller/issues/571)) ([646f071](https://github.com/reanahub/reana-workflow-controller/commit/646f071feb61c7b901cc8979b02bc846a3f0a343))
* **manager:** pass custom env variables to workflow engines ([#571](https://github.com/reanahub/reana-workflow-controller/issues/571)) ([cb9369b](https://github.com/reanahub/reana-workflow-controller/commit/cb9369bb3ca6beb70d0693fef277df1958121169))


### Bug fixes

* **manager:** graceful shutdown of job-controller ([#559](https://github.com/reanahub/reana-workflow-controller/issues/559)) ([817b019](https://github.com/reanahub/reana-workflow-controller/commit/817b019b3745862436e99570c10c6d8ea35533f4))
* **manager:** use valid group name when calling `groupadd` ([#566](https://github.com/reanahub/reana-workflow-controller/issues/566)) ([73a9929](https://github.com/reanahub/reana-workflow-controller/commit/73a9929a742e18a482824c2ca9a7c52f1f46227e)), closes [#561](https://github.com/reanahub/reana-workflow-controller/issues/561)
* **stop:** store engine logs of stopped workflow ([#563](https://github.com/reanahub/reana-workflow-controller/issues/563)) ([199c163](https://github.com/reanahub/reana-workflow-controller/commit/199c16313d97932f80080585a0c617b6b0e3a78d)), closes [#560](https://github.com/reanahub/reana-workflow-controller/issues/560)


### Code refactoring

* **consumer:** do not update status of jobs ([#559](https://github.com/reanahub/reana-workflow-controller/issues/559)) ([5992034](https://github.com/reanahub/reana-workflow-controller/commit/599203403576784f6efabd158df7282431265cdc))
* **docs:** move from reST to Markdown ([#567](https://github.com/reanahub/reana-workflow-controller/issues/567)) ([4fbdb74](https://github.com/reanahub/reana-workflow-controller/commit/4fbdb74a5351155b7e0ac4ac97114a8fa3ec60f5))


### Code style

* **black:** format with black v24 ([#564](https://github.com/reanahub/reana-workflow-controller/issues/564)) ([2329437](https://github.com/reanahub/reana-workflow-controller/commit/23294373b384e19280c00f3116100816e7277e40))


### Continuous integration

* **commitlint:** addition of commit message linter ([#555](https://github.com/reanahub/reana-workflow-controller/issues/555)) ([b9df20a](https://github.com/reanahub/reana-workflow-controller/commit/b9df20a78d36b6fb664fc69127ace5d9cdd73830))
* **commitlint:** allow release commit style ([#575](https://github.com/reanahub/reana-workflow-controller/issues/575)) ([b013d49](https://github.com/reanahub/reana-workflow-controller/commit/b013d49e61b372b9ac4f8a9f1e7ceafae64295f1))
* **commitlint:** check for the presence of concrete PR number ([#562](https://github.com/reanahub/reana-workflow-controller/issues/562)) ([4b8f539](https://github.com/reanahub/reana-workflow-controller/commit/4b8f53909d281dcd2445833544c4107c8ebd1d81))
* **pytest:** move to PostgreSQL 14.10 ([#568](https://github.com/reanahub/reana-workflow-controller/issues/568)) ([9b6bfa0](https://github.com/reanahub/reana-workflow-controller/commit/9b6bfa0b5057d849f8667ee0642765150e2b52d9))
* **release-please:** initial configuration ([#555](https://github.com/reanahub/reana-workflow-controller/issues/555)) ([672083d](https://github.com/reanahub/reana-workflow-controller/commit/672083de4c943a1c32b0a093542919b72102b491))
* **release-please:** update version in Dockerfile/OpenAPI specs ([#558](https://github.com/reanahub/reana-workflow-controller/issues/558)) ([4be8086](https://github.com/reanahub/reana-workflow-controller/commit/4be8086874b1eb7e355a75ef0e79467b0a9db875))
* **shellcheck:** fix exit code propagation ([#562](https://github.com/reanahub/reana-workflow-controller/issues/562)) ([c5d4982](https://github.com/reanahub/reana-workflow-controller/commit/c5d498299f8524f016f4e8c33c9ac0e90b644cb7))


### Documentation

* **authors:** complete list of contributors ([#570](https://github.com/reanahub/reana-workflow-controller/issues/570)) ([08ab9a3](https://github.com/reanahub/reana-workflow-controller/commit/08ab9a3358ee8b027a62e1a528f7e135a676b55a))

## 0.9.2 (2023-12-12)

- Adds automated multi-platform container image building for amd64 and arm64 architectures.
- Adds metadata labels to Dockerfile.
- Changes CVMFS support to allow users to automatically mount any available repository.
- Changes how pagination is performed in order to avoid counting twice the total number of records.
- Changes the workflow deletion endpoint to return a different and more appropriate message when deleting all the runs of a workflow.
- Fixes job status consumer exception while attempting to fetch workflow engine logs for workflows that were not successfully scheduled.
- Fixes runtime uWSGI warning by rebuilding uWSGI with the PCRE support.

## 0.9.1 (2023-09-27)

- Adds the timestamp of when the workflow was stopped (`run_stopped_at`) to the workflow list and the workflow status endpoints.
- Adds PDF files to the list of file types that can be previewed from the web interface.
- Changes the deletion of a workflow to automatically delete an open interactive session attached to its workspace.
- Changes the k8s specification for interactive session pods to include labels for improved subset selection of objects.
- Changes the k8s specification for interactive session ingress resource to include annotations.
- Changes uWSGI configuration to increase buffer size, add vacuum option, etc.
- Fixes job status inconsistency when stopping a workflow by setting the job statuses to `stopped` for any running jobs.
- Fixes job status consumer to correctly rollback the database transaction when an error occurs.
- Fixes uWSGI memory consumption on systems with very high allowed number of open files.
- Fixes uWSGI and `consume-job-queue` command to gracefully stop when being terminated.
- Fixes container image names to be Podman-compatible.

## 0.9.0 (2023-01-19)

- Adds the remote origin of workflows submitted via Launch-on-REANA (`launcher_url`) to the workflow list endpoint.
- Adds support for Kerberos authentication for workflow orchestration.
- Adds the `REANA_WORKSPACE` environment variable to jupyter notebooks and terminals.
- Adds option to sort workflows by most disk and cpu quota usage to the workflow list endpoint.
- Adds support for specifying and listing workspace file retention rules.
- Changes workflow list endpoint to add the possibility to filter by workflow ID.
- Changes the deployment of interactive sessions to use `networking/v1` Kubernetes API.
- Changes default consumer prefetch count to handle 10 messages instead of 200 in order to reduce the probability of 406 PRECONDITION errors on message acknowledgement.
- Changes to Flask v2.
- Changes job status consumer to improve logging for not-alive workflows.
- Changes the deletion of a workflow to also update the user disk quota usage if the workspace is deleted.
- Changes the CWD of jupyter's terminals to the directory of the workflow's workspace.
- Changes the k8s specification of interactive sessions' pods to remove the environment variables used for service discovery.
- Changes GitLab integration to use `reana` as pipeline name instead of `default` when setting status of a commit.
- Changes the deletion of a workflow to always remove the workflow's workspace and to fail if the request is asking not to delete the workspace.
- Changes the `move_files` endpoint to allow moving files while a workflow is running.
- Changes the deployment of interactive sessions to improve security by not automounting the Kubernetes service account token.
- Changes workspace file management commands to use common utility functions present in reana-commons.
- Changes to PostgreSQL 12.13.
- Changes the deployment of job-controller to avoid unnecessarily mounting the database's directory.
- Changes the base image of the component to Ubuntu 20.04 LTS and reduces final Docker image size by removing build-time dependencies.
- Fixes the download of files by changing the default MIME type to `application/octet-stream`.
- Fixes the workflow list endpoint to correctly parse the boolean parameters `include_progress`, `include_workspace_size` and `include_retention_rules`.
- Fixes Kerberos authentication for long-running workflows by renewing the Kerberos ticket periodically.
- Fixes job status consumer by discarding invalid job IDs.

## 0.8.2 (2022-10-06)

- Fixes `delete --include-all-runs` functionality to delete only workflow owner's past runs.

## 0.8.1 (2022-02-07)

- Adds configuration environment variable to set default timeout for user's jobs for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT`).
- Adds configuration environment variable to set maximum custom timeout limit that users can assign to their jobs for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT`).

## 0.8.0 (2021-11-22)

- Adds users quota accounting.
- Adds new job properties `started_at` and `finished_at` to the `/logs` endpoint.
- Adds configuration environment variable to limit the number of messages received in the job status consumer (`prefetch_count`).
- Adds file search capabilities to the workflow workspace endpoint.
- Adds Snakemake workflow engine support.
- Adds support for custom workflow workspace path.
- Changes to PostgreSQL 12.8.
- Changes workflow run manager to query the specific workflow engine during pod deletion.
- Fixes workflow list endpoint query logic to improve optimization.

## 0.7.4 (2021-07-05)

- Changes internal dependencies.

## 0.7.3 (2021-04-28)

- Adds configuration environment variable to set job memory limits for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_MEMORY_LIMIT`).
- Adds configuration environment variable to set maximum custom memory limits that users can assign to their job containers for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT`).
- Adds support for listing files using glob patterns.
- Adds support for glob patterns and directory downloads, packaging files into a zip.

## 0.7.2 (2021-03-17)

- Adds new configuration to toggle Kubernetes user jobs clean up.
- Fixes `job-status-consumer` exception detection for better resilience.

## 0.7.1 (2021-02-03)

- Fixes minor code warnings.
- Changes CI system to include Python flake8 and Dockerfile hadolint checkers.

## 0.7.0 (2020-10-20)

- Adds possibility to restart workflows.
- Adds exposure of workflow engines logs.
- Adds possibility to pass workflow operational options.
- Adds progress report information on workflow list response.
- Adds code mount on dev mode in workflow engines and job controller.
- Adds preview flag to file download endpoint.
- Fixes deletion of workflows in queued state.
- Fixes CVMFS availability for interactive sessions.
- Fixes jobs status update.
- Fixes response on close interactive session action.
- Changes runtime component creation to use centrally configured namespace from REANA-Commons.
- Changes workflow engine pod labelling for better traceability.
- Changes logs endpoint to provide richer information.
- Changes git clone depth when retrieving GitLab projects.
- Changes REANA submodule installation in editable mode for live code updates for developers.
- Changes base image to use Python 3.8.
- Changes code formatting to respect `black` coding style.
- Changes documentation to single-page layout.

## 0.6.1 (2020-05-25)

- Upgrades REANA-Commons package using latest Kubernetes client version.

## 0.6.0 (2019-12-20)

- Modifies the batch workflow run creation, including an instance of
  REANA-Job-Controller running alongside with the workflow engine (sidecar
  pattern). Only DB and workflow worksapce are mounted.
- Refactors volume mounts using `reana-commons` base.
- Provides user secrets to the job controller.
- Extends workflow APIs for GitLab integration.
- Allows stream file uploads.

## 0.5.0 (2019-04-23)

- Adds support to create interactive sessions so the workspace can be explored
  and modified through a Jupyter notebook.
- Creates workflow engine instances on demand for each user and makes CVMFS
  available inside of them.
- Adds new endpoint to compare two workflows. The output is a `git` like
  diff which can be configured to show differences at metadata level,
  workspace level or both.
- Adds new endpoint to delete workflows including the stopped ones.
- Adds new endpoints to delete and move files whithin the workspace.
  The deletion can be also done recursively with a wildcard.
- Adds new endpoint which returns workflow parameters.
- Adds new endpoint to query the disk usage of a given workspace.
- Makes docker image slimmer by using `python:3.6-slim`.
- Centralises log level and log format configuration.

## 0.4.0 (2018-11-06)

- Improves AMQP re-connection handling. Switches from `pika` to `kombu`.
- Improves REST API documentation rendering.
- Changes license to MIT.

## 0.3.2 (2018-09-25)

- Modifies job input identification process for caching purposes, adding compatibility
  with CephFS storage volumes.

## 0.3.1 (2018-09-07)

- Harmonises date and time outputs amongst various REST API endpoints.
- Separates workflow parameters and engine parameters when running Serial
  workflows.
- Pins REANA-Commons and REANA-DB dependencies.

## 0.3.0 (2018-08-10)

- Adds support for
  [Serial workflows](http://reana-workflow-engine-serial.readthedocs.io/en/latest/).
- Tracks progress of workflow runs.
- Adds uwsgi for production deployments.
- Allows downloading of any file from a workflow workspace.

## 0.2.0 (2018-04-19)

- Adds support for Common Workflow Language workflows.
- Adds support for specifying workflow names in REST API requests.
- Adds sequential incrementing of workflow run numbers.
- Adds support for nested inputs and runtime code directory uploads.
- Improves error messages and information.
- Prevents multiple starts of the same workflow.

## 0.1.0 (2018-01-30)

- Initial public release.
