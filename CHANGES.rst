Changes
=======

Version 0.9.0 (UNRELEASED)
---------------------------

- Adds support for Kubernetes networking/v1 API to interactive sessions.
- Changes workflow list endpoint to add the possibility to filter by workflow id.
- Changes default consumer prefetch count to handle 10 messages instead of 200 in order to reduce the probability of 406 PRECONDITION errors on message acknowledgement.

Version 0.8.1 (2022-02-07)
---------------------------

- Adds configuration environment variable to set default timeout for user's jobs for the Kubernetes compute backend (``REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT``).
- Adds configuration environment variable to set maximum custom timeout limit that users can assign to their jobs for the Kubernetes compute backend (``REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT``).

Version 0.8.0 (2021-11-22)
---------------------------

- Adds users quota accounting.
- Adds new job properties ``started_at`` and ``finished_at`` to the ``/logs`` endpoint.
- Adds configuration environment variable to limit the number of messages received in the job status consumer (``prefetch_count``).
- Adds file search capabilities to the workflow workspace endpoint.
- Adds Snakemake workflow engine support.
- Adds support for custom workflow workspace path.
- Changes to PostgreSQL 12.8
- Changes workflow run manager to query the specific workflow engine during pod deletion.
- Fixes workflow list endpoint query logic to improve optimization.

Version 0.7.4 (2021-07-05)
--------------------------

- Changes internal dependencies.

Version 0.7.3 (2021-04-28)
--------------------------

- Adds configuration environment variable to set job memory limits for the Kubernetes compute backend (``REANA_KUBERNETES_JOBS_MEMORY_LIMIT``).
- Adds configuration environment variable to set maximum custom memory limits that users can assign to their job containers for the Kubernetes compute backend (``REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT``).
- Adds support for listing files using glob patterns.
- Adds support for glob patterns and directory downloads, packaging files into a zip.

Version 0.7.2 (2021-03-17)
--------------------------

- Adds new configuration to toggle Kubernetes user jobs clean up.
- Fixes ``job-status-consumer`` exception detection for better resilience.

Version 0.7.1 (2021-02-03)
--------------------------

- Fixes minor code warnings.
- Changes CI system to include Python flake8 and Dockerfile hadolint checkers.

Version 0.7.0 (2020-10-20)
--------------------------

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
- Changes code formatting to respect ``black`` coding style.
- Changes documentation to single-page layout.

Version 0.6.1 (2020-05-25)
--------------------------

- Upgrades REANA-Commons package using latest Kubernetes client version.

Version 0.6.0 (2019-12-20)
--------------------------

- Modifies the batch workflow run creation, including an instance of
  REANA-Job-Controller running alongside with the workflow engine (sidecar
  pattern). Only DB and workflow worksapce are mounted.
- Refactors volume mounts using `reana-commons` base.
- Provides user secrets to the job controller.
- Extends workflow APIs for GitLab integration.
- Allows stream file uploads.


Version 0.5.0 (2019-04-23)
--------------------------

- Adds support to create interactive sessions so the workspace can be explored
  and modified through a Jupyter notebook.
- Creates workflow engine instances on demand for each user and makes CVMFS
  available inside of them.
- Adds new endpoint to compare two workflows. The output is a ``git`` like
  diff which can be configured to show differences at metadata level,
  workspace level or both.
- Adds new endpoint to delete workflows including the stopped ones.
- Adds new endpoints to delete and move files whithin the workspace.
  The deletion can be also done recursively with a wildcard.
- Adds new endpoint which returns workflow parameters.
- Adds new endpoint to query the disk usage of a given workspace.
- Makes docker image slimmer by using ``python:3.6-slim``.
- Centralises log level and log format configuration.

Version 0.4.0 (2018-11-06)
--------------------------

- Improves AMQP re-connection handling. Switches from ``pika`` to ``kombu``.
- Improves REST API documentation rendering.
- Changes license to MIT.

Version 0.3.2 (2018-09-25)
--------------------------

- Modifies job input identification process for caching purposes, adding compatibility
  with CephFS storage volumes.

Version 0.3.1 (2018-09-07)
--------------------------

- Harmonises date and time outputs amongst various REST API endpoints.
- Separates workflow parameters and engine parameters when running Serial
  workflows.
- Pins REANA-Commons and REANA-DB dependencies.

Version 0.3.0 (2018-08-10)
--------------------------

- Adds support for
  `Serial workflows <http://reana-workflow-engine-serial.readthedocs.io/en/latest/>`_.
- Tracks progress of workflow runs.
- Adds uwsgi for production deployments.
- Allows downloading of any file from a workflow workspace.

Version 0.2.0 (2018-04-19)
--------------------------

- Adds support for Common Workflow Language workflows.
- Adds support for specifying workflow names in REST API requests.
- Adds sequential incrementing of workflow run numbers.
- Adds support for nested inputs and runtime code directory uploads.
- Improves error messages and information.
- Prevents multiple starts of the same workflow.

Version 0.1.0 (2018-01-30)
--------------------------

- Initial public release.

.. admonition:: Please beware

   Please note that REANA is in an early alpha stage of its development. The
   developer preview releases are meant for early adopters and testers. Please
   don't rely on released versions for any production purposes yet.
