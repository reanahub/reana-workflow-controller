<!-- markdownlint-disable MD013 -->

# Changelog

## [0.9.5](https://github.com/reanahub/reana-workflow-controller/compare/0.9.4...0.9.5) (2025-11-07)


### Features

* **dask:** add nthreads option to `dask-worker` command ([#636](https://github.com/reanahub/reana-workflow-controller/issues/636)) ([eaf2b59](https://github.com/reanahub/reana-workflow-controller/commit/eaf2b592679c8be5bb25b0ccb1ef9d71a6f432f9))
* **dask:** create Kerberos sidecars for Dask workflows ([#632](https://github.com/reanahub/reana-workflow-controller/issues/632)) ([0f90c8a](https://github.com/reanahub/reana-workflow-controller/commit/0f90c8aedd79d14528256826893591ca874d0492))
* **dask:** create Rucio sidecars for Dask workflows ([#634](https://github.com/reanahub/reana-workflow-controller/issues/634)) ([89c390e](https://github.com/reanahub/reana-workflow-controller/commit/89c390ea15ef37ea7522ddd8ce6357bc8620a8b8))
* **dask:** create VOMS proxy sidecars for Dask workflows ([#633](https://github.com/reanahub/reana-workflow-controller/issues/633)) ([24cb362](https://github.com/reanahub/reana-workflow-controller/commit/24cb362f0a7e6d49b4af6689c49590cd2cde2ad0))
* **dask:** introduce labels and node selector to Dask resources ([#628](https://github.com/reanahub/reana-workflow-controller/issues/628)) ([3a8e37e](https://github.com/reanahub/reana-workflow-controller/commit/3a8e37e46037f312b0f629a146f13f0f1667d041)), closes [#623](https://github.com/reanahub/reana-workflow-controller/issues/623)
* **dask:** return service logs and fix service status handling ([#651](https://github.com/reanahub/reana-workflow-controller/issues/651)) ([ee87fd7](https://github.com/reanahub/reana-workflow-controller/commit/ee87fd73a863e17869ba3fabadacabb0af82788b)), closes [#627](https://github.com/reanahub/reana-workflow-controller/issues/627)
* **k8s:** support custom namespaces for Dask resources ([#621](https://github.com/reanahub/reana-workflow-controller/issues/621)) ([fbab460](https://github.com/reanahub/reana-workflow-controller/commit/fbab4600076bc5d89745eaa75bfeae8ed33ab976))
* **list:** display interactive sessions ([#662](https://github.com/reanahub/reana-workflow-controller/issues/662)) ([eebd278](https://github.com/reanahub/reana-workflow-controller/commit/eebd2784608feb6adeaaee3ee6ef0099c5ad4b25))
* **manager:** add Kueue scheduling option for user workloads ([#658](https://github.com/reanahub/reana-workflow-controller/issues/658)) ([5ca4f44](https://github.com/reanahub/reana-workflow-controller/commit/5ca4f4408ab3c2031484dd6d38e165fb84343e33))
* **opensearch:** capture logs from Dask cluster pods ([#616](https://github.com/reanahub/reana-workflow-controller/issues/616)) ([51fad95](https://github.com/reanahub/reana-workflow-controller/commit/51fad95d5c7d08712e5e9b1b3f0ae055704891b2)), closes [#610](https://github.com/reanahub/reana-workflow-controller/issues/610)
* **rest:** add services field to workflow endpoints ([#612](https://github.com/reanahub/reana-workflow-controller/issues/612)) ([afd1400](https://github.com/reanahub/reana-workflow-controller/commit/afd1400ddf79f972000830d8034e6d959afb00b3))


### Bug fixes

* **config:** update reana-auth-vomsproxy to 1.3.1 to fix WLCG IAM ([#639](https://github.com/reanahub/reana-workflow-controller/issues/639)) ([12a9742](https://github.com/reanahub/reana-workflow-controller/commit/12a9742178db1ac7a0c3100a61ea23560471c2c7))
* **dask:** check Traefik before creating dashboard ingress ([#629](https://github.com/reanahub/reana-workflow-controller/issues/629)) ([bb7b2ff](https://github.com/reanahub/reana-workflow-controller/commit/bb7b2ff2b23c169b2209c88bf1bc24aaa4021e9e))
* **dask:** use correct REANA host port for Dask service URLs ([#630](https://github.com/reanahub/reana-workflow-controller/issues/630)) ([a02767e](https://github.com/reanahub/reana-workflow-controller/commit/a02767ea9fe781c4f4a58c13f4420498bd760a0d))
* **k8s:** check readiness of Dask service pods ([#626](https://github.com/reanahub/reana-workflow-controller/issues/626)) ([2797300](https://github.com/reanahub/reana-workflow-controller/commit/279730051ecf3ad21d55f57c899cc574d40fe503)), closes [#625](https://github.com/reanahub/reana-workflow-controller/issues/625)
* **k8s:** improve error handling for Dask K8s resources ([#618](https://github.com/reanahub/reana-workflow-controller/issues/618)) ([a71ad83](https://github.com/reanahub/reana-workflow-controller/commit/a71ad83310c6dc880da6d33531a3ccc528c3d7a6)), closes [#617](https://github.com/reanahub/reana-workflow-controller/issues/617)
* **rest:** correct response when fetching workflow logs by steps ([#660](https://github.com/reanahub/reana-workflow-controller/issues/660)) ([9880f76](https://github.com/reanahub/reana-workflow-controller/commit/9880f76ee8dc8dd37867a00b7174f4fa60c3ab47)), closes [#659](https://github.com/reanahub/reana-workflow-controller/issues/659)
* **rest:** detect session status from the pod state ([#611](https://github.com/reanahub/reana-workflow-controller/issues/611)) ([907459b](https://github.com/reanahub/reana-workflow-controller/commit/907459b75ee9aaa9ef028f641e14d1f875b7729a))


### Code refactoring

* **dask:** use central function for Dask K8s component names ([#613](https://github.com/reanahub/reana-workflow-controller/issues/613)) ([f252098](https://github.com/reanahub/reana-workflow-controller/commit/f252098250257ea9d513b9c7c850cfdca97aa39c))


### Continuous integration

* **commitlint:** fix local running of commit linter on macOS ([#656](https://github.com/reanahub/reana-workflow-controller/issues/656)) ([d939f25](https://github.com/reanahub/reana-workflow-controller/commit/d939f2517f995e2dde8ad0737290f517bad19429))
* **jsonlint:** add JSON linting ([#655](https://github.com/reanahub/reana-workflow-controller/issues/655)) ([f095249](https://github.com/reanahub/reana-workflow-controller/commit/f0952492779267cda3511139ef7f0fb081e300b8))
* **markdownlint:** add Markdown linting ([#655](https://github.com/reanahub/reana-workflow-controller/issues/655)) ([d9e6442](https://github.com/reanahub/reana-workflow-controller/commit/d9e64423219f4936796fb6762a3b79d88ae48f6b))
* **prettier:** add Prettier code formatting checks ([#655](https://github.com/reanahub/reana-workflow-controller/issues/655)) ([2c339b7](https://github.com/reanahub/reana-workflow-controller/commit/2c339b7feb6d7d5dea1e658ae7fb63872076082f))
* **shfmt:** add shfmt code formatting checks ([#654](https://github.com/reanahub/reana-workflow-controller/issues/654)) ([992506f](https://github.com/reanahub/reana-workflow-controller/commit/992506fc9386134e996917612e9e1abd2211ea1e)), closes [#652](https://github.com/reanahub/reana-workflow-controller/issues/652)
* **yamllint:** add YAML linting ([#655](https://github.com/reanahub/reana-workflow-controller/issues/655)) ([0e1837d](https://github.com/reanahub/reana-workflow-controller/commit/0e1837dc3b7a42dbc9b71a5a59c5e6fd15569056))

## [0.9.4](https://github.com/reanahub/reana-workflow-controller/compare/0.9.3...0.9.4) (2024-11-29)

### Build

* **docker:** pin setuptools 70 ([#601](https://github.com/reanahub/reana-workflow-controller/issues/601)) ([be6a388](https://github.com/reanahub/reana-workflow-controller/commit/be6a3885f4f2e84ca77c7e09a89e5f2f06185452))
* **python:** bump shared REANA packages as of 2024-11-28 ([#620](https://github.com/reanahub/reana-workflow-controller/issues/620)) ([179fa89](https://github.com/reanahub/reana-workflow-controller/commit/179fa89ccc4a5e77fca9efa403f4ad2003b40db3))

### Features

* **config:** upgrade to Jupyter SciPy 7.2.2 notebook ([#614](https://github.com/reanahub/reana-workflow-controller/issues/614)) ([72f0c4c](https://github.com/reanahub/reana-workflow-controller/commit/72f0c4c69759c8abf1d67c735232e5b6c033d504))
* **helm:** allow cluster administrator to configure ingress host ([#588](https://github.com/reanahub/reana-workflow-controller/issues/588)) ([a7c9c85](https://github.com/reanahub/reana-workflow-controller/commit/a7c9c851277f3ca191c073fdc6c6d5d4149a95e8))
* **sessions:** expose user secrets in interactive sessions ([#591](https://github.com/reanahub/reana-workflow-controller/issues/591)) ([784efee](https://github.com/reanahub/reana-workflow-controller/commit/784efee4be8b4a9785d03d3d05b00f3da2b455c2))

### Bug fixes

* **config:** read secret key from env ([#615](https://github.com/reanahub/reana-workflow-controller/issues/615)) ([7df1279](https://github.com/reanahub/reana-workflow-controller/commit/7df1279f45e0981a06c3af705873c4d1d797404d))
* **manager:** avoid privilege escalation in Kubernetes jobs ([#615](https://github.com/reanahub/reana-workflow-controller/issues/615)) ([24563e5](https://github.com/reanahub/reana-workflow-controller/commit/24563e568044e29d4399f78d8c081d144f116761))
* **manager:** pass RabbitMQ connection details to workflow engine ([#615](https://github.com/reanahub/reana-workflow-controller/issues/615)) ([cf4ee73](https://github.com/reanahub/reana-workflow-controller/commit/cf4ee734788da33f15a80e1fc1f0b3233ea5a007))
* **set_workflow_status:** validate endpoint arguments ([#589](https://github.com/reanahub/reana-workflow-controller/issues/589)) ([5945d7f](https://github.com/reanahub/reana-workflow-controller/commit/5945d7fca095531b3601e551c527457f9413643c))

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

* Adds automated multi-platform container image building for amd64 and arm64 architectures.
* Adds metadata labels to Dockerfile.
* Changes CVMFS support to allow users to automatically mount any available repository.
* Changes how pagination is performed in order to avoid counting twice the total number of records.
* Changes the workflow deletion endpoint to return a different and more appropriate message when deleting all the runs of a workflow.
* Fixes job status consumer exception while attempting to fetch workflow engine logs for workflows that were not successfully scheduled.
* Fixes runtime uWSGI warning by rebuilding uWSGI with the PCRE support.

## 0.9.1 (2023-09-27)

* Adds the timestamp of when the workflow was stopped (`run_stopped_at`) to the workflow list and the workflow status endpoints.
* Adds PDF files to the list of file types that can be previewed from the web interface.
* Changes the deletion of a workflow to automatically delete an open interactive session attached to its workspace.
* Changes the k8s specification for interactive session pods to include labels for improved subset selection of objects.
* Changes the k8s specification for interactive session ingress resource to include annotations.
* Changes uWSGI configuration to increase buffer size, add vacuum option, etc.
* Fixes job status inconsistency when stopping a workflow by setting the job statuses to `stopped` for any running jobs.
* Fixes job status consumer to correctly rollback the database transaction when an error occurs.
* Fixes uWSGI memory consumption on systems with very high allowed number of open files.
* Fixes uWSGI and `consume-job-queue` command to gracefully stop when being terminated.
* Fixes container image names to be Podman-compatible.

## 0.9.0 (2023-01-19)

* Adds the remote origin of workflows submitted via Launch-on-REANA (`launcher_url`) to the workflow list endpoint.
* Adds support for Kerberos authentication for workflow orchestration.
* Adds the `REANA_WORKSPACE` environment variable to jupyter notebooks and terminals.
* Adds option to sort workflows by most disk and cpu quota usage to the workflow list endpoint.
* Adds support for specifying and listing workspace file retention rules.
* Changes workflow list endpoint to add the possibility to filter by workflow ID.
* Changes the deployment of interactive sessions to use `networking/v1` Kubernetes API.
* Changes default consumer prefetch count to handle 10 messages instead of 200 in order to reduce the probability of 406 PRECONDITION errors on message acknowledgement.
* Changes to Flask v2.
* Changes job status consumer to improve logging for not-alive workflows.
* Changes the deletion of a workflow to also update the user disk quota usage if the workspace is deleted.
* Changes the CWD of jupyter's terminals to the directory of the workflow's workspace.
* Changes the k8s specification of interactive sessions' pods to remove the environment variables used for service discovery.
* Changes GitLab integration to use `reana` as pipeline name instead of `default` when setting status of a commit.
* Changes the deletion of a workflow to always remove the workflow's workspace and to fail if the request is asking not to delete the workspace.
* Changes the `move_files` endpoint to allow moving files while a workflow is running.
* Changes the deployment of interactive sessions to improve security by not automounting the Kubernetes service account token.
* Changes workspace file management commands to use common utility functions present in reana-commons.
* Changes to PostgreSQL 12.13.
* Changes the deployment of job-controller to avoid unnecessarily mounting the database's directory.
* Changes the base image of the component to Ubuntu 20.04 LTS and reduces final Docker image size by removing build-time dependencies.
* Fixes the download of files by changing the default MIME type to `application/octet-stream`.
* Fixes the workflow list endpoint to correctly parse the boolean parameters `include_progress`, `include_workspace_size` and `include_retention_rules`.
* Fixes Kerberos authentication for long-running workflows by renewing the Kerberos ticket periodically.
* Fixes job status consumer by discarding invalid job IDs.

## 0.8.2 (2022-10-06)

* Fixes `delete --include-all-runs` functionality to delete only workflow owner's past runs.

## 0.8.1 (2022-02-07)

* Adds configuration environment variable to set default timeout for user's jobs for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT`).
* Adds configuration environment variable to set maximum custom timeout limit that users can assign to their jobs for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT`).

## 0.8.0 (2021-11-22)

* Adds users quota accounting.
* Adds new job properties `started_at` and `finished_at` to the `/logs` endpoint.
* Adds configuration environment variable to limit the number of messages received in the job status consumer (`prefetch_count`).
* Adds file search capabilities to the workflow workspace endpoint.
* Adds Snakemake workflow engine support.
* Adds support for custom workflow workspace path.
* Changes to PostgreSQL 12.8.
* Changes workflow run manager to query the specific workflow engine during pod deletion.
* Fixes workflow list endpoint query logic to improve optimization.

## 0.7.4 (2021-07-05)

* Changes internal dependencies.

## 0.7.3 (2021-04-28)

* Adds configuration environment variable to set job memory limits for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_MEMORY_LIMIT`).
* Adds configuration environment variable to set maximum custom memory limits that users can assign to their job containers for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT`).
* Adds support for listing files using glob patterns.
* Adds support for glob patterns and directory downloads, packaging files into a zip.

## 0.7.2 (2021-03-17)

* Adds new configuration to toggle Kubernetes user jobs clean up.
* Fixes `job-status-consumer` exception detection for better resilience.

## 0.7.1 (2021-02-03)

* Fixes minor code warnings.
* Changes CI system to include Python flake8 and Dockerfile hadolint checkers.

## 0.7.0 (2020-10-20)

* Adds possibility to restart workflows.
* Adds exposure of workflow engines logs.
* Adds possibility to pass workflow operational options.
* Adds progress report information on workflow list response.
* Adds code mount on dev mode in workflow engines and job controller.
* Adds preview flag to file download endpoint.
* Fixes deletion of workflows in queued state.
* Fixes CVMFS availability for interactive sessions.
* Fixes jobs status update.
* Fixes response on close interactive session action.
* Changes runtime component creation to use centrally configured namespace from REANA-Commons.
* Changes workflow engine pod labelling for better traceability.
* Changes logs endpoint to provide richer information.
* Changes git clone depth when retrieving GitLab projects.
* Changes REANA submodule installation in editable mode for live code updates for developers.
* Changes base image to use Python 3.8.
* Changes code formatting to respect `black` coding style.
* Changes documentation to single-page layout.

## 0.6.1 (2020-05-25)

* Upgrades REANA-Commons package using latest Kubernetes client version.

## 0.6.0 (2019-12-20)

* Modifies the batch workflow run creation, including an instance of
  REANA-Job-Controller running alongside with the workflow engine (sidecar
  pattern). Only DB and workflow worksapce are mounted.
* Refactors volume mounts using `reana-commons` base.
* Provides user secrets to the job controller.
* Extends workflow APIs for GitLab integration.
* Allows stream file uploads.

## 0.5.0 (2019-04-23)

* Adds support to create interactive sessions so the workspace can be explored
  and modified through a Jupyter notebook.
* Creates workflow engine instances on demand for each user and makes CVMFS
  available inside of them.
* Adds new endpoint to compare two workflows. The output is a `git` like
  diff which can be configured to show differences at metadata level,
  workspace level or both.
* Adds new endpoint to delete workflows including the stopped ones.
* Adds new endpoints to delete and move files whithin the workspace.
  The deletion can be also done recursively with a wildcard.
* Adds new endpoint which returns workflow parameters.
* Adds new endpoint to query the disk usage of a given workspace.
* Makes docker image slimmer by using `python:3.6-slim`.
* Centralises log level and log format configuration.

## 0.4.0 (2018-11-06)

* Improves AMQP re-connection handling. Switches from `pika` to `kombu`.
* Improves REST API documentation rendering.
* Changes license to MIT.

## 0.3.2 (2018-09-25)

* Modifies job input identification process for caching purposes, adding compatibility
  with CephFS storage volumes.

## 0.3.1 (2018-09-07)

* Harmonises date and time outputs amongst various REST API endpoints.
* Separates workflow parameters and engine parameters when running Serial
  workflows.
* Pins REANA-Commons and REANA-DB dependencies.

## 0.3.0 (2018-08-10)

* Adds support for
  [Serial workflows](http://reana-workflow-engine-serial.readthedocs.io/en/latest/).
* Tracks progress of workflow runs.
* Adds uwsgi for production deployments.
* Allows downloading of any file from a workflow workspace.

## 0.2.0 (2018-04-19)

* Adds support for Common Workflow Language workflows.
* Adds support for specifying workflow names in REST API requests.
* Adds sequential incrementing of workflow run numbers.
* Adds support for nested inputs and runtime code directory uploads.
* Improves error messages and information.
* Prevents multiple starts of the same workflow.

## 0.1.0 (2018-01-30)

* Initial public release.
