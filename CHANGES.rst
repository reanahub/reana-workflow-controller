Changes
=======

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
