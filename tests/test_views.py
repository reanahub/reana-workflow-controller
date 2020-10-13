# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA-Workflow-Controller module tests."""

import io
import json
import os
import uuid

import fs
import mock
import pytest
from flask import url_for
from reana_db.models import (
    Job,
    JobCache,
    Workflow,
    RunStatus,
    InteractiveSession,
)
from werkzeug.utils import secure_filename

from reana_workflow_controller.rest.utils import (
    create_workflow_workspace,
    delete_workflow,
)
from reana_workflow_controller.rest.workflows_status import START, STOP
from reana_workflow_controller.workflow_run_manager import WorkflowRunManager

status_dict = {
    START: RunStatus.running,
    STOP: RunStatus.finished,
}


def test_get_workflows(app, session, default_user, cwl_workflow_with_name):
    """Test listing all workflows."""
    with app.test_client() as client:
        workflow_uuid = uuid.uuid4()
        workflow_name = "my_test_workflow"
        workflow = Workflow(
            id_=workflow_uuid,
            name=workflow_name,
            status=RunStatus.finished,
            owner_id=default_user.id_,
            reana_specification=cwl_workflow_with_name["reana_specification"],
            type_=cwl_workflow_with_name["reana_specification"]["type"],
            logs="",
        )
        session.add(workflow)
        session.commit()
        res = client.get(
            url_for("workflows.get_workflows"), query_string={"user": default_user.id_}
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))["items"]
        expected_data = [
            {
                "id": str(workflow.id_),
                "name": workflow.name + ".1",  # Add run_number
                "status": workflow.status.name,
                "user": str(workflow.owner_id),
                "created": response_data[0]["created"],
                "progress": response_data[0]["progress"],
                "size": "-",
            }
        ]

        assert response_data == expected_data


def test_get_workflows_wrong_user(app):
    """Test list of workflows for unknown user."""
    with app.test_client() as client:
        random_user_uuid = uuid.uuid4()
        res = client.get(
            url_for("workflows.get_workflows"), query_string={"user": random_user_uuid}
        )
        assert res.status_code == 404


def test_get_workflows_missing_user(app):
    """Test listing all workflows with missing user."""
    with app.test_client() as client:
        res = client.get(url_for("workflows.get_workflows"), query_string={})
        assert res.status_code == 400


def test_create_workflow_with_name(
    app, session, default_user, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test create workflow and its workspace by specifying a name."""
    with app.test_client() as client:
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        assert res.status_code == 201
        response_data = json.loads(res.get_data(as_text=True))
        # Check workflow fetch by id
        workflow_by_id = Workflow.query.filter(
            Workflow.id_ == response_data.get("workflow_id")
        ).first()
        assert workflow_by_id

        # Check workflow fetch by name and that name of created workflow
        # is the same that was supplied to `api.create_workflow`
        workflow_by_name = Workflow.query.filter(
            Workflow.name == "my_test_workflow"
        ).first()
        assert workflow_by_name

        workflow = workflow_by_id

        # Check that the workflow workspace exists
        absolute_workflow_workspace = os.path.join(
            tmp_shared_volume_path, workflow.workspace_path
        )
        assert os.path.exists(absolute_workflow_workspace)


def test_create_workflow_without_name(
    app, session, default_user, tmp_shared_volume_path, cwl_workflow_without_name
):
    """Test create workflow and its workspace without specifying a name."""
    with app.test_client() as client:
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_without_name),
        )

        assert res.status_code == 201
        response_data = json.loads(res.get_data(as_text=True))

        # Check workflow fetch by id
        workflow_by_id = Workflow.query.filter(
            Workflow.id_ == response_data.get("workflow_id")
        ).first()
        assert workflow_by_id

        # Check workflow fetch by name and that name of created workflow
        # is the same that was supplied to `api.create_workflow`

        import reana_workflow_controller

        default_workflow_name = (
            reana_workflow_controller.config.DEFAULT_NAME_FOR_WORKFLOWS
        )

        workflow_by_name = Workflow.query.filter(
            Workflow.name == default_workflow_name
        ).first()
        assert workflow_by_name

        workflow = workflow_by_id

        # Check that the workflow workspace exists
        absolute_workflow_workspace = os.path.join(
            tmp_shared_volume_path, workflow.workspace_path
        )
        assert os.path.exists(absolute_workflow_workspace)


def test_create_workflow_wrong_user(
    app, session, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test create workflow providing unknown user."""
    with app.test_client() as client:
        random_user_uuid = uuid.uuid4()
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": random_user_uuid},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        assert res.status_code == 404
        response_data = json.loads(res.get_data(as_text=True))
        workflow = Workflow.query.filter(
            Workflow.id_ == response_data.get("workflow_id")
        ).first()
        # workflow exists in DB
        assert not workflow


def test_download_missing_file(app, default_user, cwl_workflow_with_name):
    """Test download missing file."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        assert res.status_code == 201
        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        file_name = "input.csv"
        res = client.get(
            url_for(
                "workspaces.download_file",
                workflow_id_or_name=workflow_uuid,
                file_name=file_name,
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        assert res.status_code == 404
        response_data = json.loads(res.get_data(as_text=True))
        assert response_data == {"message": "input.csv does not exist."}


def test_download_file(
    app, session, default_user, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test download file from workspace."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()
        # create file
        file_name = "output name.csv"
        file_binary_content = b"1,2,3,4\n5,6,7,8"
        # write file in the workflow workspace under `outputs` directory:
        # we use `secure_filename` here because
        # we use it in server side when adding
        # files
        absolute_path_workflow_workspace = os.path.join(
            tmp_shared_volume_path, workflow.workspace_path
        )
        file_path = os.path.join(absolute_path_workflow_workspace, file_name)
        # because outputs directory doesn't exist by default
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb+") as f:
            f.write(file_binary_content)
        res = client.get(
            url_for(
                "workspaces.download_file",
                workflow_id_or_name=workflow_uuid,
                file_name=file_name,
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        assert res.data == file_binary_content


def test_download_file_with_path(
    app, session, default_user, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test download file prepended with path."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()
        # create file
        file_name = "first/1991/output.csv"
        file_binary_content = b"1,2,3,4\n5,6,7,8"
        # write file in the workflow workspace under `outputs` directory:
        # we use `secure_filename` here because
        # we use it in server side when adding
        # files
        absolute_path_workflow_workspace = os.path.join(
            tmp_shared_volume_path, workflow.workspace_path
        )
        file_path = os.path.join(absolute_path_workflow_workspace, file_name)
        # because outputs directory doesn't exist by default
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb+") as f:
            f.write(file_binary_content)
        res = client.get(
            url_for(
                "workspaces.download_file",
                workflow_id_or_name=workflow_uuid,
                file_name=file_name,
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        assert res.data == file_binary_content


def test_get_files(
    app, session, default_user, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test get files list."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()
        # create file
        absolute_path_workflow_workspace = os.path.join(
            tmp_shared_volume_path, workflow.workspace_path
        )
        fs_ = fs.open_fs(absolute_path_workflow_workspace)
        test_files = []
        for i in range(5):
            file_name = "{0}.csv".format(i)
            subdir_name = str(uuid.uuid4())
            subdir = fs.path.join(subdir_name)
            fs_.makedirs(subdir)
            fs_.touch("{0}/{1}".format(subdir, file_name))
            test_files.append(os.path.join(subdir_name, file_name))

        res = client.get(
            url_for("workspaces.get_files", workflow_id_or_name=workflow_uuid),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        for file_ in json.loads(res.data.decode())["items"]:
            assert file_.get("name") in test_files


def test_get_files_unknown_workflow(app, default_user):
    """Test get list of files for non existing workflow."""
    with app.test_client() as client:
        # create workflow
        random_workflow_uuid = str(uuid.uuid4())
        res = client.get(
            url_for("workspaces.get_files", workflow_id_or_name=random_workflow_uuid),
            query_string={"user": default_user.id_},
            content_type="application/json",
        )

        assert res.status_code == 404
        response_data = json.loads(res.get_data(as_text=True))
        expected_data = {
            "message": "REANA_WORKON is set to {0}, but "
            "that workflow does not exist. "
            "Please set your REANA_WORKON environment "
            "variable appropriately.".format(random_workflow_uuid)
        }
        assert response_data == expected_data


def test_get_workflow_status_with_uuid(
    app, session, default_user, cwl_workflow_with_name
):
    """Test get workflow status."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()

        res = client.get(
            url_for("statuses.get_workflow_status", workflow_id_or_name=workflow_uuid),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        json_response = json.loads(res.data.decode())
        assert json_response.get("status") == workflow.status.name
        workflow.status = RunStatus.finished
        session.commit()

        res = client.get(
            url_for("statuses.get_workflow_status", workflow_id_or_name=workflow_uuid),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        json_response = json.loads(res.data.decode())
        assert json_response.get("status") == workflow.status.name


def test_get_workflow_status_with_name(
    app, session, default_user, cwl_workflow_with_name
):
    """Test get workflow status."""
    with app.test_client() as client:
        # create workflow
        workflow_uuid = uuid.uuid4()
        workflow_name = "my_test_workflow"
        workflow = Workflow(
            id_=workflow_uuid,
            name=workflow_name,
            status=RunStatus.finished,
            owner_id=default_user.id_,
            reana_specification=cwl_workflow_with_name["reana_specification"],
            type_=cwl_workflow_with_name["reana_specification"]["type"],
            logs="",
        )
        session.add(workflow)
        session.commit()

        workflow = Workflow.query.filter(Workflow.name == workflow_name).first()

        res = client.get(
            url_for(
                "statuses.get_workflow_status", workflow_id_or_name=workflow_name + ".1"
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        json_response = json.loads(res.data.decode())

        assert json_response.get("status") == workflow.status.name
        workflow.status = RunStatus.finished
        session.commit()

        res = client.get(
            url_for(
                "statuses.get_workflow_status", workflow_id_or_name=workflow_name + ".1"
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        json_response = json.loads(res.data.decode())
        assert json_response.get("status") == workflow.status.name


def test_get_workflow_status_unauthorized(app, default_user, cwl_workflow_with_name):
    """Test get workflow status unauthorized."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_created_uuid = response_data.get("workflow_id")
        random_user_uuid = uuid.uuid4()
        res = client.get(
            url_for(
                "statuses.get_workflow_status",
                workflow_id_or_name=workflow_created_uuid,
            ),
            query_string={"user": random_user_uuid},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        assert res.status_code == 403


def test_get_workflow_status_unknown_workflow(
    app, default_user, cwl_workflow_with_name
):
    """Test get workflow status for unknown workflow."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        random_workflow_uuid = uuid.uuid4()
        res = client.get(
            url_for(
                "statuses.get_workflow_status", workflow_id_or_name=random_workflow_uuid
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        assert res.status_code == 404


def test_set_workflow_status(
    app,
    corev1_api_client_with_user_secrets,
    user_secrets,
    session,
    default_user,
    yadage_workflow_with_name,
):
    """Test set workflow status "Start"."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_created_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_created_uuid).first()
        assert workflow.status == RunStatus.created
        payload = START
        with mock.patch(
            "reana_workflow_controller.workflow_run_manager."
            "current_k8s_batchv1_api_client"
        ) as k8s_api_client:
            # provide user secret store
            with mock.patch(
                "reana_commons.k8s.secrets." "current_k8s_corev1_api_client",
                corev1_api_client_with_user_secrets(user_secrets),
            ):
                # set workflow status to START
                res = client.put(
                    url_for(
                        "statuses.set_workflow_status",
                        workflow_id_or_name=workflow_created_uuid,
                    ),
                    query_string={"user": default_user.id_, "status": "start"},
                )
                json_response = json.loads(res.data.decode())
                assert json_response.get("status") == status_dict[payload].name
                k8s_api_client.create_namespaced_job.assert_called_once()


def test_start_already_started_workflow(
    app,
    session,
    default_user,
    corev1_api_client_with_user_secrets,
    user_secrets,
    yadage_workflow_with_name,
):
    """Test start workflow twice."""
    with app.test_client() as client:
        os.environ["TESTS"] = "True"
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_created_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_created_uuid).first()
        assert workflow.status == RunStatus.created
        payload = START
        with mock.patch(
            "reana_workflow_controller.workflow_run_manager."
            "current_k8s_batchv1_api_client"
        ):
            # provide user secret store
            with mock.patch(
                "reana_commons.k8s.secrets." "current_k8s_corev1_api_client",
                corev1_api_client_with_user_secrets(user_secrets),
            ):
                # set workflow status to START
                res = client.put(
                    url_for(
                        "statuses.set_workflow_status",
                        workflow_id_or_name=workflow_created_uuid,
                    ),
                    query_string={"user": default_user.id_, "status": "start"},
                )
                json_response = json.loads(res.data.decode())
                assert json_response.get("status") == status_dict[payload].name
                res = client.put(
                    url_for(
                        "statuses.set_workflow_status",
                        workflow_id_or_name=workflow_created_uuid,
                    ),
                    query_string={"user": default_user.id_, "status": "start"},
                )
                json_response = json.loads(res.data.decode())
                assert res.status_code == 409
                expected_message = (
                    "Workflow {0} could not be started because"
                    " it is already running."
                ).format(workflow_created_uuid)
                assert json_response.get("message") == expected_message


@pytest.mark.parametrize(
    "current_status, expected_status, expected_http_status_code, "
    "k8s_stop_call_count",
    [
        (RunStatus.created, RunStatus.created, 409, 0),
        (RunStatus.running, RunStatus.stopped, 200, 1),
        (RunStatus.failed, RunStatus.failed, 409, 0),
        (RunStatus.finished, RunStatus.finished, 409, 0),
    ],
)
def test_stop_workflow(
    current_status,
    expected_status,
    expected_http_status_code,
    k8s_stop_call_count,
    app,
    default_user,
    yadage_workflow_with_name,
    sample_serial_workflow_in_db,
    session,
):
    """Test stop workflow."""
    with app.test_client() as client:
        sample_serial_workflow_in_db.status = current_status
        session.add(sample_serial_workflow_in_db)
        session.commit()
        with mock.patch(
            "reana_workflow_controller.workflow_run_manager."
            "current_k8s_batchv1_api_client"
        ) as stop_workflow_mock:
            res = client.put(
                url_for(
                    "statuses.set_workflow_status",
                    workflow_id_or_name=sample_serial_workflow_in_db.name,
                ),
                query_string={"user": default_user.id_, "status": "stop"},
            )
            assert sample_serial_workflow_in_db.status == expected_status
            assert res.status_code == expected_http_status_code
            assert (
                stop_workflow_mock.delete_namespaced_job.call_count
                == k8s_stop_call_count
            )


def test_set_workflow_status_unauthorized(app, default_user, yadage_workflow_with_name):
    """Test set workflow status unauthorized."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_created_uuid = response_data.get("workflow_id")
        random_user_uuid = uuid.uuid4()
        payload = START
        res = client.put(
            url_for(
                "statuses.set_workflow_status",
                workflow_id_or_name=workflow_created_uuid,
            ),
            query_string={"user": random_user_uuid, "status": payload},
            content_type="application/json",
        )
        assert res.status_code == 403


def test_set_workflow_status_unknown_workflow(
    app, default_user, yadage_workflow_with_name
):
    """Test set workflow status for unknown workflow."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        random_workflow_uuid = uuid.uuid4()
        payload = START
        res = client.put(
            url_for(
                "statuses.set_workflow_status", workflow_id_or_name=random_workflow_uuid
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(payload),
        )
        assert res.status_code == 404


def test_upload_file(
    app, session, default_user, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test upload file."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()
        # create file
        file_name = "dataset.csv"
        file_binary_content = b"1,2,3,4\n5,6,7,8"

        res = client.post(
            url_for("workspaces.upload_file", workflow_id_or_name=workflow_uuid),
            query_string={"user": default_user.id_, "file_name": file_name},
            content_type="application/octet-stream",
            input_stream=io.BytesIO(file_binary_content),
        )
        assert res.status_code == 200
        # remove workspace directory from path
        workflow_workspace = workflow.workspace_path

        # we use `secure_filename` here because
        # we use it in server side when adding
        # files
        absolute_file_path = os.path.join(
            tmp_shared_volume_path, workflow_workspace, secure_filename(file_name)
        )

        with open(absolute_file_path, "rb") as f:
            assert f.read() == file_binary_content


def test_upload_file_unknown_workflow(app, default_user):
    """Test upload file to non existing workflow."""
    with app.test_client() as client:
        random_workflow_uuid = uuid.uuid4()
        # create file
        file_name = "dataset.csv"
        file_binary_content = b"1,2,3,4\n5,6,7,8"

        res = client.post(
            url_for("workspaces.upload_file", workflow_id_or_name=random_workflow_uuid),
            query_string={"user": default_user.id_, "file_name": file_name},
            content_type="application/octet-stream",
            input_stream=io.BytesIO(file_binary_content),
        )
        assert res.status_code == 404


def test_delete_file(app, default_user, sample_serial_workflow_in_db):
    """Test delete file."""
    # Move to fixture
    from flask import current_app

    create_workflow_workspace(sample_serial_workflow_in_db.workspace_path)
    abs_path_workspace = os.path.join(
        current_app.config["SHARED_VOLUME_PATH"],
        sample_serial_workflow_in_db.workspace_path,
    )
    file_name = "dataset.csv"
    file_binary_content = b"1,2,3,4\n5,6,7,8"
    abs_path_to_file = os.path.join(abs_path_workspace, file_name)
    with open(abs_path_to_file, "wb+") as f:
        f.write(file_binary_content)
    assert os.path.exists(abs_path_to_file)
    with app.test_client() as client:
        res = client.delete(
            url_for(
                "workspaces.delete_file",
                workflow_id_or_name=sample_serial_workflow_in_db.id_,
                file_name=file_name,
            ),
            query_string={"user": default_user.id_},
        )
        assert res.status_code == 200
        assert not os.path.exists(abs_path_to_file)


def test_get_created_workflow_logs(app, default_user, cwl_workflow_with_name):
    """Test get workflow logs."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow_name = response_data.get("workflow_name")
        res = client.get(
            url_for("statuses.get_workflow_logs", workflow_id_or_name=workflow_uuid),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(None),
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))
        create_workflow_logs = ""
        expected_data = {
            "workflow_id": workflow_uuid,
            "workflow_name": workflow_name,
            "user": str(default_user.id_),
            "logs": '{"workflow_logs": "", "job_logs": {},' ' "engine_specific": null}',
        }
        assert response_data == expected_data


def test_get_unknown_workflow_logs(app, default_user, yadage_workflow_with_name):
    """Test set workflow status for unknown workflow."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        random_workflow_uuid = uuid.uuid4()
        res = client.get(
            url_for(
                "statuses.get_workflow_logs", workflow_id_or_name=random_workflow_uuid
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
        )
        assert res.status_code == 404


def test_get_workflow_logs_unauthorized(app, default_user, yadage_workflow_with_name):
    """Test set workflow status for unknown workflow."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        random_user_uuid = uuid.uuid4()
        res = client.get(
            url_for("statuses.get_workflow_logs", workflow_id_or_name=workflow_uuid),
            query_string={"user": random_user_uuid},
            content_type="application/json",
        )
        assert res.status_code == 403


def test_start_input_parameters(
    app,
    session,
    default_user,
    user_secrets,
    corev1_api_client_with_user_secrets,
    sample_serial_workflow_in_db,
):
    """Test start workflow with inupt parameters."""
    with app.test_client() as client:
        # create workflow
        sample_serial_workflow_in_db.status = RunStatus.created
        workflow_created_uuid = sample_serial_workflow_in_db.id_
        session.add(sample_serial_workflow_in_db)
        session.commit()
        workflow = Workflow.query.filter(Workflow.id_ == workflow_created_uuid).first()
        assert workflow.status == RunStatus.created
        payload = START
        parameters = {"input_parameters": {"first": "test"}, "operational_options": {}}
        with mock.patch(
            "reana_workflow_controller.workflow_run_manager."
            "current_k8s_batchv1_api_client"
        ):
            # provide user secret store
            with mock.patch(
                "reana_commons.k8s.secrets." "current_k8s_corev1_api_client",
                corev1_api_client_with_user_secrets(user_secrets),
            ):
                # set workflow status to START and pass parameters
                res = client.put(
                    url_for(
                        "statuses.set_workflow_status",
                        workflow_id_or_name=workflow_created_uuid,
                    ),
                    query_string={"user": default_user.id_, "status": "start"},
                    content_type="application/json",
                    data=json.dumps(parameters),
                )
                json_response = json.loads(res.data.decode())
                assert json_response.get("status") == status_dict[payload].name
                workflow = Workflow.query.filter(
                    Workflow.id_ == workflow_created_uuid
                ).first()
                assert workflow.input_parameters == parameters["input_parameters"]


def test_start_workflow_db_failure(
    app,
    session,
    default_user,
    user_secrets,
    corev1_api_client_with_user_secrets,
    sample_serial_workflow_in_db,
):
    """Test starting workflow with a DB failure."""
    mock_session_cls = mock.Mock()
    mock_session = mock.Mock()
    mock_session_cls.object_session.return_value = mock_session
    from sqlalchemy.exc import SQLAlchemyError

    mock_session.commit = mock.Mock(
        side_effect=SQLAlchemyError("Could not connect to the server.")
    )
    mock_k8s_run_manager_cls = mock.Mock()
    k8s_workflow_run_manager = mock.Mock()
    mock_k8s_run_manager_cls.return_value = k8s_workflow_run_manager
    with mock.patch.multiple(
        "reana_workflow_controller.rest.utils",
        Session=mock_session_cls,
        KubernetesWorkflowRunManager=mock_k8s_run_manager_cls,
    ):
        with app.test_client() as client:
            res = client.put(
                url_for(
                    "statuses.set_workflow_status",
                    workflow_id_or_name=sample_serial_workflow_in_db.id_,
                ),
                query_string={"user": default_user.id_, "status": "start"},
                content_type="application/json",
                data=json.dumps({}),
            )
            assert res.status_code == 502


def test_start_workflow_kubernetes_failure(
    app,
    session,
    default_user,
    user_secrets,
    corev1_api_client_with_user_secrets,
    sample_serial_workflow_in_db,
):
    """Test starting workflow with a Kubernetes failure when creating jobs."""
    mock_k8s_run_manager_cls = mock.Mock()
    k8s_workflow_run_manager = mock.Mock()
    from kubernetes.client.rest import ApiException

    k8s_workflow_run_manager.start_batch_workflow_run = mock.Mock(
        side_effect=ApiException("Could not connect to Kubernetes.")
    )
    mock_k8s_run_manager_cls.return_value = k8s_workflow_run_manager
    with mock.patch.multiple(
        "reana_workflow_controller.rest.utils",
        KubernetesWorkflowRunManager=mock_k8s_run_manager_cls,
    ):
        with app.test_client() as client:
            res = client.put(
                url_for(
                    "statuses.set_workflow_status",
                    workflow_id_or_name=sample_serial_workflow_in_db.id_,
                ),
                query_string={"user": default_user.id_, "status": "start"},
                content_type="application/json",
                data=json.dumps({}),
            )
            assert res.status_code == 502


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.created,
        RunStatus.failed,
        RunStatus.finished,
        pytest.param(RunStatus.deleted, marks=pytest.mark.xfail),
        pytest.param(RunStatus.running, marks=pytest.mark.xfail),
    ],
)
@pytest.mark.parametrize("hard_delete", [True, False])
def test_delete_workflow(
    app, session, default_user, sample_yadage_workflow_in_db, status, hard_delete
):
    """Test deletion of a workflow in all possible statuses."""
    sample_yadage_workflow_in_db.status = status
    session.add(sample_yadage_workflow_in_db)
    session.commit()
    with app.test_client() as client:
        res = client.put(
            url_for(
                "statuses.set_workflow_status",
                workflow_id_or_name=sample_yadage_workflow_in_db.id_,
            ),
            query_string={"user": default_user.id_, "status": "deleted"},
            content_type="application/json",
            data=json.dumps({"hard_delete": hard_delete}),
        )
        if not hard_delete:
            assert sample_yadage_workflow_in_db.status == RunStatus.deleted
        else:
            assert (
                session.query(Workflow)
                .filter_by(id_=sample_yadage_workflow_in_db.id_)
                .all()
                == []
            )


@pytest.mark.parametrize("hard_delete", [True, False])
def test_delete_all_workflow_runs(
    app, session, default_user, yadage_workflow_with_name, hard_delete
):
    """Test deletion of all runs of a given workflow."""
    # add 5 workflows in the database with the same name
    for i in range(5):
        workflow = Workflow(
            id_=uuid.uuid4(),
            name=yadage_workflow_with_name["name"],
            owner_id=default_user.id_,
            reana_specification=yadage_workflow_with_name["reana_specification"],
            operational_options={},
            type_=yadage_workflow_with_name["reana_specification"]["workflow"]["type"],
            logs="",
        )
        session.add(workflow)
        session.commit()

    first_workflow = (
        session.query(Workflow)
        .filter_by(name=yadage_workflow_with_name["name"])
        .first()
    )
    with app.test_client() as client:
        res = client.put(
            url_for(
                "statuses.set_workflow_status", workflow_id_or_name=first_workflow.id_
            ),
            query_string={"user": default_user.id_, "status": "deleted"},
            content_type="application/json",
            data=json.dumps({"hard_delete": hard_delete, "all_runs": True}),
        )
    if not hard_delete:
        for workflow in (
            session.query(Workflow).filter_by(name=first_workflow.name).all()
        ):
            assert workflow.status == RunStatus.deleted
    else:
        assert session.query(Workflow).filter_by(name=first_workflow.name).all() == []


@pytest.mark.parametrize("hard_delete", [True, False])
@pytest.mark.parametrize("workspace", [True, False])
def test_workspace_deletion(
    app,
    session,
    default_user,
    yadage_workflow_with_name,
    tmp_shared_volume_path,
    workspace,
    hard_delete,
):
    """Test workspace deletion."""
    with app.test_client() as client:
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        assert res.status_code == 201
        response_data = json.loads(res.get_data(as_text=True))

        workflow = Workflow.query.filter(
            Workflow.id_ == response_data.get("workflow_id")
        ).first()
        assert workflow

        absolute_workflow_workspace = os.path.join(
            tmp_shared_volume_path, workflow.workspace_path
        )

        # create a job for the workflow
        workflow_job = Job(id_=uuid.uuid4(), workflow_uuid=workflow.id_)
        job_cache_entry = JobCache(job_id=workflow_job.id_)
        session.add(workflow_job)
        session.commit()
        session.add(job_cache_entry)
        session.commit()

        # check that the workflow workspace exists
        assert os.path.exists(absolute_workflow_workspace)
        with app.test_client() as client:
            res = client.put(
                url_for(
                    "statuses.set_workflow_status", workflow_id_or_name=workflow.id_
                ),
                query_string={"user": default_user.id_, "status": "deleted"},
                content_type="application/json",
                data=json.dumps({"hard_delete": hard_delete, "workspace": workspace}),
            )
        if hard_delete or workspace:
            assert not os.path.exists(absolute_workflow_workspace)

        # check that all cache entries for jobs
        # of the deleted workflow are removed
        cache_entries_after_delete = JobCache.query.filter_by(
            job_id=workflow_job.id_
        ).all()
        assert not cache_entries_after_delete


def test_deletion_of_workspace_of_an_already_deleted_workflow(
    app, session, default_user, yadage_workflow_with_name, tmp_shared_volume_path
):
    """Test workspace deletion of an already deleted workflow."""
    with app.test_client() as client:
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": default_user.id_},
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        assert res.status_code == 201
        response_data = json.loads(res.get_data(as_text=True))

        workflow = Workflow.query.filter(
            Workflow.id_ == response_data.get("workflow_id")
        ).first()
        assert workflow

        absolute_workflow_workspace = os.path.join(
            tmp_shared_volume_path, workflow.workspace_path
        )

        # check that the workflow workspace exists
        assert os.path.exists(absolute_workflow_workspace)
        with app.test_client() as client:
            res = client.put(
                url_for(
                    "statuses.set_workflow_status", workflow_id_or_name=workflow.id_
                ),
                query_string={"user": default_user.id_, "status": "deleted"},
                content_type="application/json",
                data=json.dumps({"hard_delete": False, "workspace": False}),
            )
        assert os.path.exists(absolute_workflow_workspace)

        delete_workflow(workflow, hard_delete=False, workspace=True)
        assert not os.path.exists(absolute_workflow_workspace)


def test_get_workflow_diff(
    app,
    default_user,
    sample_yadage_workflow_in_db,
    sample_serial_workflow_in_db,
    tmp_shared_volume_path,
):
    """Test set workflow status for unknown workflow."""
    with app.test_client() as client:
        res = client.get(
            url_for(
                "workflows.get_workflow_diff",
                workflow_id_or_name_a=sample_serial_workflow_in_db.id_,
                workflow_id_or_name_b=sample_yadage_workflow_in_db.id_,
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))
        assert "reana_specification" in response_data
        assert "workspace_listing" in response_data
        workflow_diff = json.loads(response_data["reana_specification"])["workflow"]
        entire_diff_as_string = "".join(str(e) for e in workflow_diff)
        # the following should be present in the diff
        assert "serial" in "".join(
            str(e) for e in json.loads(response_data["reana_specification"])["workflow"]
        )
        assert "yadage" in "".join(
            str(e) for e in json.loads(response_data["reana_specification"])["workflow"]
        )
        assert (
            json.dumps(
                sample_serial_workflow_in_db.reana_specification["workflow"][
                    "specification"
                ]["steps"][0]["commands"]
            )
            in entire_diff_as_string
        )
        # single line of the entire specification is tested
        # get_workflow_diff() returns extra characters between lines
        assert (
            sample_yadage_workflow_in_db.reana_specification["workflow"][
                "specification"
            ]["first"]
            in entire_diff_as_string
        )
        print("done")


def test_get_workspace_diff(
    app,
    default_user,
    sample_yadage_workflow_in_db,
    sample_serial_workflow_in_db,
    tmp_shared_volume_path,
):
    """Test get workspace differences."""
    # create the workspaces for the two workflows
    workspace_path_a = os.path.join(
        tmp_shared_volume_path, sample_serial_workflow_in_db.workspace_path
    )
    workspace_path_b = os.path.join(
        tmp_shared_volume_path, sample_yadage_workflow_in_db.workspace_path
    )
    # Create files that differ in one line
    csv_line = "1,2,3,4"
    file_name = "test.csv"
    for index, workspace in enumerate([workspace_path_a, workspace_path_b]):
        with open(os.path.join(workspace, file_name), "w",) as f:
            f.write("# File {}".format(index))
            f.write(os.linesep)
            f.write(csv_line)
            f.flush()
    with app.test_client() as client:
        res = client.get(
            url_for(
                "workflows.get_workflow_diff",
                workflow_id_or_name_a=sample_serial_workflow_in_db.id_,
                workflow_id_or_name_b=sample_yadage_workflow_in_db.id_,
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))
        assert "# File" in response_data["workspace_listing"]


def test_create_interactive_session(app, default_user, sample_serial_workflow_in_db):
    """Test create interactive session."""
    wrm = WorkflowRunManager(sample_serial_workflow_in_db)
    expected_data = {"path": wrm._generate_interactive_workflow_path()}
    with app.test_client() as client:
        # create workflow
        with mock.patch.multiple(
            "reana_workflow_controller.k8s",
            current_k8s_corev1_api_client=mock.DEFAULT,
            current_k8s_networking_v1beta1=mock.DEFAULT,
            current_k8s_appsv1_api_client=mock.DEFAULT,
        ) as mocks:
            res = client.post(
                url_for(
                    "workflows_session.open_interactive_session",
                    workflow_id_or_name=sample_serial_workflow_in_db.id_,
                    interactive_session_type="jupyter",
                ),
                query_string={"user": default_user.id_},
            )
            assert res.json == expected_data


def test_create_interactive_session_unknown_type(
    app, default_user, sample_serial_workflow_in_db
):
    """Test create interactive session for unknown interactive type."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for(
                "workflows_session.open_interactive_session",
                workflow_id_or_name=sample_serial_workflow_in_db.id_,
                interactive_session_type="terminl",
            ),
            query_string={"user": default_user.id_},
        )
        assert res.status_code == 404


def test_create_interactive_session_custom_image(
    app, default_user, sample_serial_workflow_in_db
):
    """Create an interactive session with custom image."""
    custom_image = "test/image"
    interactive_session_configuration = {"image": custom_image}
    with app.test_client() as client:
        # create workflow
        with mock.patch.multiple(
            "reana_workflow_controller.k8s",
            current_k8s_corev1_api_client=mock.DEFAULT,
            current_k8s_networking_v1beta1=mock.DEFAULT,
            current_k8s_appsv1_api_client=mock.DEFAULT,
        ) as mocks:
            res = client.post(
                url_for(
                    "workflows_session.open_interactive_session",
                    workflow_id_or_name=sample_serial_workflow_in_db.id_,
                    interactive_session_type="jupyter",
                ),
                query_string={"user": default_user.id_},
                content_type="application/json",
                data=json.dumps(interactive_session_configuration),
            )
            fargs, _ = mocks[
                "current_k8s_appsv1_api_client"
            ].create_namespaced_deployment.call_args
            assert fargs[1].spec.template.spec.containers[0].image == custom_image


def test_close_interactive_session(
    app, session, default_user, sample_serial_workflow_in_db
):
    """Test close an interactive session."""
    expected_data = {"message": "The interactive session has been closed"}
    path = "/5d9b30fd-f225-4615-9107-b1373afec070"
    name = "interactive-jupyter-5d9b30fd-f225-4615-9107-b1373afec070-5lswkp"
    int_session = InteractiveSession(
        name=name, path=path, owner_id=sample_serial_workflow_in_db.owner_id,
    )
    sample_serial_workflow_in_db.sessions.append(int_session)
    session.add(sample_serial_workflow_in_db)
    session.commit()
    with app.test_client() as client:
        with mock.patch(
            "reana_workflow_controller.k8s" ".current_k8s_networking_v1beta1"
        ) as mocks:
            res = client.post(
                url_for(
                    "workflows_session.close_interactive_session",
                    workflow_id_or_name=sample_serial_workflow_in_db.id_,
                ),
                query_string={"user": default_user.id_},
                content_type="application/json",
            )
        assert res.json == expected_data


def test_close_interactive_session_not_opened(
    app, session, default_user, sample_serial_workflow_in_db
):
    """Test close an interactive session when session is not opened."""
    expected_data = {
        "message": "Workflow - {} has no open interactive session.".format(
            sample_serial_workflow_in_db.id_
        )
    }
    with app.test_client() as client:
        sample_serial_workflow_in_db.sessions = []
        session.add(sample_serial_workflow_in_db)
        session.commit()
        res = client.post(
            url_for(
                "workflows_session.close_interactive_session",
                workflow_id_or_name=sample_serial_workflow_in_db.id_,
            ),
            query_string={"user": default_user.id_},
            content_type="application/json",
        )
        assert res.json == expected_data
        assert res._status_code == 404
