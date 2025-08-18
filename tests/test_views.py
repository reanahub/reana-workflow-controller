# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA-Workflow-Controller module tests."""

import io
import json
import os
import uuid
from zipfile import ZipFile

import fs
import mock
import pytest
from flask import url_for
from reana_db.models import (
    InteractiveSession,
    Job,
    JobCache,
    RunStatus,
    Workflow,
    UserWorkflow,
)
from reana_workflow_controller.rest.utils import (
    create_workflow_workspace,
    delete_workflow,
)
from reana_workflow_controller.rest.workflows_status import START, STOP
from reana_workflow_controller.workflow_run_manager import WorkflowRunManager
from werkzeug.utils import secure_filename

status_dict = {
    START: RunStatus.pending,
    STOP: RunStatus.finished,
}


def test_get_workflows(app, session, user0, cwl_workflow_with_name):
    """Test listing all workflows."""
    with app.test_client() as client:
        workflow_uuid = uuid.uuid4()
        workflow_name = "my_test_workflow"
        workflow = Workflow(
            id_=workflow_uuid,
            name=workflow_name,
            status=RunStatus.finished,
            owner_id=user0.id_,
            reana_specification=cwl_workflow_with_name["reana_specification"],
            type_=cwl_workflow_with_name["reana_specification"]["type"],
            logs="",
        )
        session.add(workflow)
        session.commit()
        res = client.get(
            url_for("workflows.get_workflows"),
            query_string={"user": user0.id_, "type": "batch"},
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
                "services": response_data[0]["services"],
                "size": {"raw": -1, "human_readable": ""},
                "launcher_url": None,
                "owner_email": user0.email,
                "shared_with": [],
            }
        ]

        assert response_data == expected_data


def test_get_workflows_wrong_user(app):
    """Test list of workflows for unknown user."""
    with app.test_client() as client:
        random_user_uuid = uuid.uuid4()
        res = client.get(
            url_for("workflows.get_workflows"),
            query_string={"user": random_user_uuid, "type": "batch"},
        )
        assert res.status_code == 404


def test_get_workflows_missing_user(app):
    """Test listing all workflows with missing user."""
    with app.test_client() as client:
        res = client.get(
            url_for("workflows.get_workflows"), query_string={"type": "batch"}
        )
        assert res.status_code == 400


def test_get_workflows_missing_type(app, user0):
    """Test listing all workflows with missing type."""
    with app.test_client() as client:
        res = client.get(
            url_for("workflows.get_workflows"), query_string={"user": user0.id_}
        )
        assert res.status_code == 400


def test_get_workflows_include_progress(app, user0, sample_yadage_workflow_in_db):
    """Test listing all workflows without including progress."""
    workflow = sample_yadage_workflow_in_db
    with app.test_client() as client:
        res = client.get(
            url_for("workflows.get_workflows"),
            query_string={
                "user": user0.id_,
                "type": "batch",
                "verbose": "true",
                "include_progress": "false",
            },
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))["items"][0]
        assert response_data["id"] == str(workflow.id_)
        # full progress is not included even though verbose is set to True
        assert "finished" not in response_data["progress"]


def test_get_workflows_include_retention_rules(
    app, user0, sample_yadage_workflow_in_db
):
    """Test listing all workflows without including retention rules."""
    workflow = sample_yadage_workflow_in_db
    with app.test_client() as client:
        res = client.get(
            url_for("workflows.get_workflows"),
            query_string={
                "user": user0.id_,
                "type": "batch",
                "verbose": "true",
                "include_retention_rules": "false",
            },
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))["items"][0]
        assert response_data["id"] == str(workflow.id_)
        assert "retention_rules" not in response_data


def test_get_workflows_shared(
    app, user1, user2, sample_yadage_workflow_in_db_owned_by_user1
):
    """Test listing shared workflows."""
    workflow = sample_yadage_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # share workflow with user2
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps({"user_email_to_share_with": user2.email}),
        )
        assert res.status_code == 200

        # list shared workflows for user2
        res = client.get(
            url_for("workflows.get_workflows"),
            query_string={"user": user1.id_, "shared": True, "type": "batch"},
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))["items"]
        assert len(response_data) == 1
        assert response_data[0]["id"] == str(workflow.id_)
        assert response_data[0]["shared_with"] == [user2.email]
        assert response_data[0]["owner_email"] == user1.email


def test_get_workflows_shared_by(
    app, user1, user2, sample_yadage_workflow_in_db_owned_by_user1
):
    """Test listing workflows shared by a user."""
    workflow = sample_yadage_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # share workflow with user2
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps({"user_email_to_share_with": user2.email}),
        )
        assert res.status_code == 200

        # list shared workflows for user1
        res = client.get(
            url_for("workflows.get_workflows"),
            query_string={
                "user": user2.id_,
                "shared_by": user1.email,
                "type": "batch",
            },
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))["items"]
        assert len(response_data) == 1
        assert response_data[0]["id"] == str(workflow.id_)
        assert response_data[0]["owner_email"] == user1.email


def test_get_workflows_shared_with(
    app, user1, user2, sample_yadage_workflow_in_db_owned_by_user1
):
    """Test listing workflows shared with a user."""
    workflow = sample_yadage_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # share workflow with user2
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps({"user_email_to_share_with": user2.email}),
        )
        assert res.status_code == 200

        # list shared workflows for user2
        res = client.get(
            url_for("workflows.get_workflows"),
            query_string={
                "user": user1.id_,
                "shared_with": user2.email,
                "type": "batch",
            },
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))["items"]
        assert len(response_data) == 1
        assert response_data[0]["id"] == str(workflow.id_)
        assert response_data[0]["shared_with"] == [user2.email]


def test_get_workflows_shared_by_and_shared_with(
    app, user1, user2, sample_yadage_workflow_in_db_owned_by_user1
):
    """Test listing workflows shared by and shared with a user."""
    workflow = sample_yadage_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # share workflow with user2
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_share_with": user2.email,
            },
        )

        # list shared workflows for user2
        res = client.get(
            url_for("workflows.get_workflows"),
            query_string={
                "user": user2.id_,
                "shared_with": user1.email,
                "shared_by": user1.email,
                "type": "batch",
            },
        )
        assert res.status_code == 400
        response_data = res.get_json()
        assert response_data["message"] == (
            "You cannot filter by shared_by and shared_with at the same time."
        )


def test_create_workflow_with_name(
    app, session, user0, cwl_workflow_with_name, tmp_shared_volume_path
):
    """Test create workflow and its workspace by specifying a name."""
    with app.test_client() as client:
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
        assert os.path.exists(workflow.workspace_path)


def test_create_workflow_without_name(
    app, session, user0, cwl_workflow_without_name, tmp_shared_volume_path
):
    """Test create workflow and its workspace without specifying a name."""
    with app.test_client() as client:
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
        assert os.path.exists(workflow.workspace_path)


def test_create_workflow_wrong_user(
    app, session, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test create workflow providing unknown user."""
    with app.test_client() as client:
        random_user_uuid = uuid.uuid4()
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": random_user_uuid,
                "workspace_root_path": tmp_shared_volume_path,
            },
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


def test_download_missing_file(
    app, user0, cwl_workflow_with_name, tmp_shared_volume_path
):
    """Test download missing file."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        assert res.status_code == 404
        response_data = json.loads(res.get_data(as_text=True))
        assert response_data == {"message": "input.csv does not exist."}


def test_download_file(
    app,
    session,
    user0,
    tmp_shared_volume_path,
    cwl_workflow_with_name,
    sample_serial_workflow_in_db,
):
    """Test download file from workspace."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
        absolute_path_workflow_workspace = workflow.workspace_path
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
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        assert res.data == file_binary_content


def test_download_file_with_path(
    app, session, user0, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test download file prepended with path."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
        file_path = os.path.join(workflow.workspace_path, file_name)
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
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        assert res.data == file_binary_content


def test_download_dir_or_wildcard(
    app, session, user0, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test download directory or file(s) matching a wildcard pattern."""

    def _download(pattern, workflow_uuid):
        return client.get(
            url_for(
                "workspaces.download_file",
                workflow_id_or_name=workflow_uuid,
                file_name=pattern,
            ),
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()
        # create files
        files = {
            "foo/1.txt": b"txt in foo dir",
            "foo/bar/1.csv": b"csv in bar dir",
            "foo/bar/baz/2.csv": b"csv in baz dir",
        }
        for file_name, file_binary_content in files.items():
            file_path = os.path.join(workflow.workspace_path, file_name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb+") as f:
                f.write(file_binary_content)

        # download directory by name
        res = _download("foo", workflow_uuid)
        assert res.headers.get("Content-Type") == "application/zip"
        zipfile = ZipFile(io.BytesIO(res.data))
        assert len(zipfile.filelist) == 3
        for file_name, file_binary_content in files.items():
            assert zipfile.read(file_name) == file_binary_content

        res = _download("foo/bar", workflow_uuid)
        assert res.headers.get("Content-Type") == "application/zip"
        zipfile = ZipFile(io.BytesIO(res.data))
        assert len(zipfile.filelist) == 2
        zipped_file_names = [f.filename for f in zipfile.filelist]
        assert "foo/1.txt" not in zipped_file_names
        assert zipfile.read("foo/bar/1.csv") == files["foo/bar/1.csv"]
        assert zipfile.read("foo/bar/baz/2.csv") == files["foo/bar/baz/2.csv"]

        # download by glob pattern
        res = _download("**/*.csv", workflow_uuid)
        assert res.headers.get("Content-Type") == "application/zip"
        zipfile = ZipFile(io.BytesIO(res.data))
        assert len(zipfile.filelist) == 2
        res = _download("**/1.*", workflow_uuid)
        assert res.headers.get("Content-Type") == "application/zip"
        zipfile = ZipFile(io.BytesIO(res.data))
        assert len(zipfile.filelist) == 2
        res = _download("*/*.txt", workflow_uuid)
        assert res.headers.get("Content-Type") != "application/zip"
        assert res.data == files["foo/1.txt"]


def test_get_files(app, session, user0, tmp_shared_volume_path, cwl_workflow_with_name):
    """Test get files list."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()
        # create file
        absolute_path_workflow_workspace = workflow.workspace_path
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
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        for file_ in json.loads(res.data.decode())["items"]:
            assert file_.get("name") in test_files


def test_get_files_deleted_workflow(
    app, user0, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test get files list of a deleted workflow without a workspace."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")

        # delete workflow
        res = client.put(
            url_for(
                "statuses.set_workflow_status",
                workflow_id_or_name=workflow_uuid,
            ),
            query_string={"user": user0.id_, "status": "deleted"},
            content_type="application/json",
            data=json.dumps({}),
        )
        assert res.status_code == 200

        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()
        assert workflow.status == RunStatus.deleted
        assert not os.path.exists(workflow.workspace_path)

        # get list of files
        res = client.get(
            url_for("workspaces.get_files", workflow_id_or_name=workflow_uuid),
            query_string={"user": user0.id_},
            content_type="application/json",
        )
        assert res.status_code == 404


def test_get_files_unknown_workflow(app, user0):
    """Test get list of files for non existing workflow."""
    with app.test_client() as client:
        # create workflow
        random_workflow_uuid = str(uuid.uuid4())
        res = client.get(
            url_for("workspaces.get_files", workflow_id_or_name=random_workflow_uuid),
            query_string={"user": user0.id_},
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
    app, session, user0, cwl_workflow_with_name, tmp_shared_volume_path
):
    """Test get workflow status."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()

        res = client.get(
            url_for("statuses.get_workflow_status", workflow_id_or_name=workflow_uuid),
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        json_response = json.loads(res.data.decode())
        assert json_response.get("status") == workflow.status.name
        workflow.status = RunStatus.finished
        session.commit()

        res = client.get(
            url_for("statuses.get_workflow_status", workflow_id_or_name=workflow_uuid),
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        json_response = json.loads(res.data.decode())
        assert json_response.get("status") == workflow.status.name


def test_get_workflow_status_with_name(app, session, user0, cwl_workflow_with_name):
    """Test get workflow status."""
    with app.test_client() as client:
        # create workflow
        workflow_uuid = uuid.uuid4()
        workflow_name = "my_test_workflow"
        workflow = Workflow(
            id_=workflow_uuid,
            name=workflow_name,
            status=RunStatus.finished,
            owner_id=user0.id_,
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
            query_string={"user": user0.id_},
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
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        json_response = json.loads(res.data.decode())
        assert json_response.get("status") == workflow.status.name


def test_get_workflow_status_unauthorized(
    app, user0, cwl_workflow_with_name, tmp_shared_volume_path
):
    """Test get workflow status unauthorized."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
        assert res.status_code == 404


def test_get_workflow_status_unknown_workflow(app, user0, cwl_workflow_with_name):
    """Test get workflow status for unknown workflow."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        random_workflow_uuid = uuid.uuid4()
        res = client.get(
            url_for(
                "statuses.get_workflow_status", workflow_id_or_name=random_workflow_uuid
            ),
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )
        assert res.status_code == 404


def test_set_workflow_status(
    app,
    corev1_api_client_with_user_secrets,
    user_secrets,
    session,
    user0,
    yadage_workflow_with_name,
    tmp_shared_volume_path,
):
    """Test set workflow status "Start"."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
                    query_string={"user": user0.id_, "status": "start"},
                )
                json_response = json.loads(res.data.decode())
                assert json_response.get("status") == status_dict[payload].name
                k8s_api_client.create_namespaced_job.assert_called_once()


def test_start_already_started_workflow(
    app,
    session,
    user0,
    corev1_api_client_with_user_secrets,
    user_secrets,
    yadage_workflow_with_name,
    tmp_shared_volume_path,
):
    """Test start workflow twice."""
    with app.test_client() as client:
        os.environ["TESTS"] = "True"
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
                    query_string={"user": user0.id_, "status": "start"},
                )
                json_response = json.loads(res.data.decode())
                assert json_response.get("status") == status_dict[payload].name
                res = client.put(
                    url_for(
                        "statuses.set_workflow_status",
                        workflow_id_or_name=workflow_created_uuid,
                    ),
                    query_string={"user": user0.id_, "status": "start"},
                )
                json_response = json.loads(res.data.decode())
                assert res.status_code == 409
                expected_message = (
                    "Workflow {0} could not be started because"
                    " it is already pending."
                ).format(workflow_created_uuid)
                assert json_response.get("message") == expected_message


@pytest.mark.parametrize(
    "current_status, expected_status, expected_http_status_code, "
    "k8s_stop_call_count, should_update_logs",
    [
        (RunStatus.created, RunStatus.created, 409, 0, False),
        (RunStatus.running, RunStatus.stopped, 200, 1, True),
        (RunStatus.failed, RunStatus.failed, 409, 0, False),
        (RunStatus.finished, RunStatus.finished, 409, 0, False),
    ],
)
def test_stop_workflow(
    current_status,
    expected_status,
    expected_http_status_code,
    k8s_stop_call_count,
    should_update_logs,
    app,
    user0,
    yadage_workflow_with_name,
    sample_serial_workflow_in_db,
    session,
):
    """Test stop workflow."""
    with app.test_client() as client:
        sample_serial_workflow_in_db.status = current_status
        session.add(sample_serial_workflow_in_db)
        session.commit()
        workflow_engine_logs = "these are the logs of workflow-engine"
        with mock.patch(
            "reana_workflow_controller.consumer.current_k8s_batchv1_api_client"
        ) as batch_api_mock, mock.patch(
            "reana_workflow_controller.consumer._get_workflow_engine_pod_logs"
        ) as get_logs_mock:
            get_logs_mock.return_value = workflow_engine_logs
            res = client.put(
                url_for(
                    "statuses.set_workflow_status",
                    workflow_id_or_name=sample_serial_workflow_in_db.name,
                ),
                query_string={"user": user0.id_, "status": "stop"},
            )
            assert sample_serial_workflow_in_db.status == expected_status
            assert res.status_code == expected_http_status_code
            assert (
                batch_api_mock.delete_namespaced_job.call_count == k8s_stop_call_count
            )
            if should_update_logs:
                assert workflow_engine_logs in sample_serial_workflow_in_db.logs


def test_set_workflow_status_unauthorized(
    app, user0, yadage_workflow_with_name, tmp_shared_volume_path
):
    """Test set workflow status unauthorized."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
        assert res.status_code == 404


def test_set_workflow_status_unknown_workflow(
    app, user0, yadage_workflow_with_name, tmp_shared_volume_path
):
    """Test set workflow status for unknown workflow."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        random_workflow_uuid = uuid.uuid4()
        payload = START
        res = client.put(
            url_for(
                "statuses.set_workflow_status", workflow_id_or_name=random_workflow_uuid
            ),
            query_string={"user": user0.id_, "status": payload},
            content_type="application/json",
            data=json.dumps({}),
        )
        assert res.status_code == 404


def test_upload_file(
    app, session, user0, tmp_shared_volume_path, cwl_workflow_with_name
):
    """Test upload file."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
            query_string={"user": user0.id_, "file_name": file_name},
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
            workflow_workspace, secure_filename(file_name)
        )

        with open(absolute_file_path, "rb") as f:
            assert f.read() == file_binary_content


def test_upload_file_unknown_workflow(app, user0):
    """Test upload file to non existing workflow."""
    with app.test_client() as client:
        random_workflow_uuid = uuid.uuid4()
        # create file
        file_name = "dataset.csv"
        file_binary_content = b"1,2,3,4\n5,6,7,8"

        res = client.post(
            url_for("workspaces.upload_file", workflow_id_or_name=random_workflow_uuid),
            query_string={"user": user0.id_, "file_name": file_name},
            content_type="application/octet-stream",
            input_stream=io.BytesIO(file_binary_content),
        )
        assert res.status_code == 404


def test_delete_file(app, user0, sample_serial_workflow_in_db):
    """Test delete file."""
    # Move to fixture
    from flask import current_app

    create_workflow_workspace(sample_serial_workflow_in_db.workspace_path)
    file_name = "dataset.csv"
    file_binary_content = b"1,2,3,4\n5,6,7,8"
    abs_path_to_file = os.path.join(
        sample_serial_workflow_in_db.workspace_path, file_name
    )
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
            query_string={"user": user0.id_},
        )
        assert res.status_code == 200
        assert not os.path.exists(abs_path_to_file)


@pytest.mark.parametrize(
    "opensearch_return_value",
    [
        ("test logs\ntest logs\n"),
        (""),
        (None),
    ],
)
def test_get_created_workflow_logs(
    opensearch_return_value,
    app,
    user0,
    cwl_workflow_with_name,
    tmp_shared_volume_path,
    session,
):
    """Test get workflow logs."""
    from reana_workflow_controller.opensearch import OpenSearchLogFetcher

    with mock.patch.object(
        OpenSearchLogFetcher, "fetch_logs", return_value=opensearch_return_value
    ) as mock_method, mock.patch(
        "reana_workflow_controller.opensearch.REANA_OPENSEARCH_ENABLED", True
    ):
        with app.test_client() as client:
            # create workflow
            res = client.post(
                url_for("workflows.create_workflow"),
                query_string={
                    "user": user0.id_,
                    "workspace_root_path": tmp_shared_volume_path,
                },
                content_type="application/json",
                data=json.dumps(cwl_workflow_with_name),
            )
            response_data = json.loads(res.get_data(as_text=True))
            workflow_uuid = response_data.get("workflow_id")
            workflow_name = response_data.get("workflow_name")

            # create a job for the workflow
            workflow_job = Job(
                id_=uuid.UUID("9a22c3a4-6d72-4812-93e7-7e0efdeb985d"),
                workflow_uuid=workflow_uuid,
            )
            workflow_job.status = "running"
            workflow_job.logs = "test job logs"
            session.add(workflow_job)
            session.commit()

            res = client.get(
                url_for(
                    "statuses.get_workflow_logs", workflow_id_or_name=workflow_uuid
                ),
                query_string={"user": user0.id_},
                content_type="application/json",
                data=json.dumps(None),
            )
            assert res.status_code == 200
            response_data = json.loads(res.get_data(as_text=True))
            expected_data = {
                "workflow_id": workflow_uuid,
                "workflow_name": workflow_name,
                "user": str(user0.id_),
                "live_logs_enabled": False,
                "logs": json.dumps(
                    {
                        "workflow_logs": (
                            opensearch_return_value if opensearch_return_value else ""
                        ),
                        "job_logs": {
                            str(workflow_job.id_): {
                                "workflow_uuid": str(workflow_job.workflow_uuid),
                                "job_name": "",
                                "compute_backend": "",
                                "backend_job_id": "",
                                "docker_img": "",
                                "cmd": "",
                                "status": workflow_job.status.name,
                                "logs": (
                                    opensearch_return_value
                                    if opensearch_return_value
                                    else workflow_job.logs
                                ),
                                "started_at": None,
                                "finished_at": None,
                            }
                        },
                        "service_logs": {},
                        "engine_specific": None,
                    }
                ),
            }
            assert response_data == expected_data
            assert mock_method.call_count == 2


def test_get_created_workflow_logs_by_steps(
    app,
    user0,
    cwl_workflow_with_name,
    tmp_shared_volume_path,
    session,
):
    """Test get workflow logs, filtering by steps."""
    with app.test_client() as client:
        # Create the workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(cwl_workflow_with_name),
        )

        # Get the generated workflow UUID
        response_data = json.loads(res.get_data(as_text=True))
        workflow_uuid = response_data.get("workflow_id")
        workflow_name = response_data.get("workflow_name")

        # Create a job for the workflow
        workflow_job = Job(
            id_=uuid.UUID("9a22c3a4-6d72-4812-93e7-7e0efdeb985d"),
            workflow_uuid=workflow_uuid,
        )
        workflow_job.status = "running"
        workflow_job.logs = "test job logs"
        workflow_job.job_name = "gendata"
        session.add(workflow_job)
        session.commit()

        # Call the API to fetch the workflow logs, filtering by steps
        res = client.get(
            url_for("statuses.get_workflow_logs", workflow_id_or_name=workflow_uuid),
            query_string={"user": user0.id_},
            content_type="application/json",
            data=json.dumps(["gendata", "fitdata"]),
        )

        # Expect a successful response
        assert res.status_code == 200

        # Check the response data is as expected
        response_data = json.loads(res.get_data(as_text=True))
        expected_data = {
            "workflow_id": workflow_uuid,
            "workflow_name": workflow_name,
            "user": str(user0.id_),
            "live_logs_enabled": False,
            "logs": json.dumps(
                {
                    "workflow_logs": None,
                    "job_logs": {
                        str(workflow_job.id_): {
                            "workflow_uuid": str(workflow_job.workflow_uuid),
                            "job_name": workflow_job.job_name,
                            "compute_backend": "",
                            "backend_job_id": "",
                            "docker_img": "",
                            "cmd": "",
                            "status": workflow_job.status.name,
                            "logs": "test job logs",
                            "started_at": None,
                            "finished_at": None,
                        }
                    },
                    "engine_specific": None,
                }
            ),
        }
        assert response_data == expected_data


def test_get_created_workflow_opensearch_disabled(
    app, user0, cwl_workflow_with_name, tmp_shared_volume_path
):
    """Test get workflow logs when Opensearch is disabled (default)."""
    from reana_workflow_controller.opensearch import OpenSearchLogFetcher

    with mock.patch.object(
        OpenSearchLogFetcher, "fetch_logs", return_value=None
    ) as mock_method:
        with app.test_client() as client:
            # create workflow
            res = client.post(
                url_for("workflows.create_workflow"),
                query_string={
                    "user": user0.id_,
                    "workspace_root_path": tmp_shared_volume_path,
                },
                content_type="application/json",
                data=json.dumps(cwl_workflow_with_name),
            )
            response_data = json.loads(res.get_data(as_text=True))
            workflow_uuid = response_data.get("workflow_id")
            workflow_name = response_data.get("workflow_name")
            res = client.get(
                url_for(
                    "statuses.get_workflow_logs", workflow_id_or_name=workflow_uuid
                ),
                query_string={"user": user0.id_},
                content_type="application/json",
                data=json.dumps(None),
            )
            assert res.status_code == 200
            response_data = json.loads(res.get_data(as_text=True))
            expected_data = {
                "workflow_id": workflow_uuid,
                "workflow_name": workflow_name,
                "user": str(user0.id_),
                "live_logs_enabled": False,
                "logs": '{"workflow_logs": "", "job_logs": {}, "service_logs": {},'
                ' "engine_specific": null}',
            }
            assert response_data == expected_data
            mock_method.assert_not_called()


def test_get_unknown_workflow_logs(
    app, user0, yadage_workflow_with_name, tmp_shared_volume_path
):
    """Test set workflow status for unknown workflow."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        random_workflow_uuid = uuid.uuid4()
        res = client.get(
            url_for(
                "statuses.get_workflow_logs", workflow_id_or_name=random_workflow_uuid
            ),
            query_string={"user": user0.id_},
            content_type="application/json",
        )
        assert res.status_code == 404


def test_get_workflow_logs_unauthorized(
    app, user0, yadage_workflow_with_name, tmp_shared_volume_path
):
    """Test set workflow status for unknown workflow."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
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
        assert res.status_code == 404


def test_start_input_parameters(
    app,
    session,
    user0,
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
                    query_string={"user": user0.id_, "status": "start"},
                    content_type="application/json",
                    data=json.dumps(parameters),
                )
                json_response = json.loads(res.data.decode())
                assert json_response.get("status") == status_dict[payload].name
                workflow = Workflow.query.filter(
                    Workflow.id_ == workflow_created_uuid
                ).first()
                assert workflow.input_parameters == parameters["input_parameters"]


def test_start_no_input_parameters(
    app,
    session,
    user0,
    user_secrets,
    corev1_api_client_with_user_secrets,
    sample_serial_workflow_in_db,
):
    """Test start workflow with inupt parameters."""
    workflow = sample_serial_workflow_in_db
    workflow_uuid = str(sample_serial_workflow_in_db.id_)

    with app.test_client() as client:
        # create workflow
        workflow.status = RunStatus.created
        session.add(workflow)
        session.commit()

        payload = START
        parameters = {"operational_options": {}}
        with mock.patch(
            "reana_workflow_controller.workflow_run_manager."
            "current_k8s_batchv1_api_client"
        ):
            # provide user secret store
            with mock.patch(
                "reana_commons.k8s.secrets.current_k8s_corev1_api_client",
                corev1_api_client_with_user_secrets(user_secrets),
            ):
                # set workflow status to START and pass parameters
                res = client.put(
                    url_for(
                        "statuses.set_workflow_status",
                        workflow_id_or_name=workflow_uuid,
                    ),
                    query_string={"user": user0.id_, "status": "start"},
                    content_type="application/json",
                    data=json.dumps(parameters),
                )
        json_response = json.loads(res.data.decode())
        assert json_response["status"] == status_dict[payload].name
        workflow = Workflow.query.filter(Workflow.id_ == workflow_uuid).first()
        assert workflow.input_parameters == dict()


def test_start_workflow_db_failure(
    app,
    session,
    user0,
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
                query_string={"user": user0.id_, "status": "start"},
                content_type="application/json",
                data=json.dumps({}),
            )
            assert res.status_code == 502


def test_start_workflow_kubernetes_failure(
    app,
    session,
    user0,
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
                query_string={"user": user0.id_, "status": "start"},
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
        RunStatus.deleted,
        pytest.param(RunStatus.running, marks=pytest.mark.xfail(strict=True)),
    ],
)
def test_delete_workflow(app, session, user0, sample_yadage_workflow_in_db, status):
    """Test deletion of a workflow in all possible statuses."""
    sample_yadage_workflow_in_db.status = status
    session.add(sample_yadage_workflow_in_db)
    session.commit()
    with app.test_client() as client:
        client.put(
            url_for(
                "statuses.set_workflow_status",
                workflow_id_or_name=sample_yadage_workflow_in_db.id_,
            ),
            query_string={"user": user0.id_, "status": "deleted"},
            content_type="application/json",
            data=json.dumps({}),
        )
        assert sample_yadage_workflow_in_db.status == RunStatus.deleted


def test_delete_all_workflow_runs(app, session, user0, yadage_workflow_with_name):
    """Test deletion of all runs of a given workflow."""
    # add 5 workflows in the database with the same name
    for i in range(5):
        workflow = Workflow(
            id_=uuid.uuid4(),
            name=yadage_workflow_with_name["name"],
            owner_id=user0.id_,
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
        client.put(
            url_for(
                "statuses.set_workflow_status", workflow_id_or_name=first_workflow.id_
            ),
            query_string={"user": user0.id_, "status": "deleted"},
            content_type="application/json",
            data=json.dumps({"all_runs": True}),
        )
    for workflow in session.query(Workflow).filter_by(name=first_workflow.name).all():
        assert workflow.status == RunStatus.deleted


@pytest.mark.parametrize(
    "workspace", [True, pytest.param(False, marks=pytest.mark.xfail(strict=True))]
)
def test_workspace_deletion(
    app,
    session,
    user0,
    yadage_workflow_with_name,
    tmp_shared_volume_path,
    workspace,
):
    """Test workspace deletion."""
    with app.test_client() as client:
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        assert res.status_code == 201
        response_data = json.loads(res.get_data(as_text=True))

        workflow = Workflow.query.filter(
            Workflow.id_ == response_data.get("workflow_id")
        ).first()
        assert workflow

        # create a job for the workflow
        workflow_job = Job(id_=uuid.uuid4(), workflow_uuid=workflow.id_)
        job_cache_entry = JobCache(job_id=workflow_job.id_)
        session.add(workflow_job)
        session.commit()
        session.add(job_cache_entry)
        session.commit()

        # check that the workflow workspace exists
        assert os.path.exists(workflow.workspace_path)
        with app.test_client() as client:
            res = client.put(
                url_for(
                    "statuses.set_workflow_status", workflow_id_or_name=workflow.id_
                ),
                query_string={"user": user0.id_, "status": "deleted"},
                content_type="application/json",
                data=json.dumps({"workspace": workspace}),
            )
            assert res.status_code == 200
        if workspace:
            assert not os.path.exists(workflow.workspace_path)

        # check that all cache entries for jobs
        # of the deleted workflow are removed
        cache_entries_after_delete = JobCache.query.filter_by(
            job_id=workflow_job.id_
        ).all()
        assert not cache_entries_after_delete


def test_deletion_of_workspace_of_an_already_deleted_workflow(
    app, session, user0, yadage_workflow_with_name, tmp_shared_volume_path
):
    """Test workspace deletion of an already deleted workflow."""
    with app.test_client() as client:
        res = client.post(
            url_for("workflows.create_workflow"),
            query_string={
                "user": user0.id_,
                "workspace_root_path": tmp_shared_volume_path,
            },
            content_type="application/json",
            data=json.dumps(yadage_workflow_with_name),
        )
        assert res.status_code == 201
        response_data = json.loads(res.get_data(as_text=True))

        workflow = Workflow.query.filter(
            Workflow.id_ == response_data.get("workflow_id")
        ).first()
        assert workflow

        # check that the workflow workspace exists
        assert os.path.exists(workflow.workspace_path)
        with app.test_client() as client:
            res = client.put(
                url_for(
                    "statuses.set_workflow_status", workflow_id_or_name=workflow.id_
                ),
                query_string={"user": user0.id_, "status": "deleted"},
                content_type="application/json",
                data=json.dumps({"workspace": False}),
            )
        assert os.path.exists(workflow.workspace_path)

        delete_workflow(workflow, workspace=True)
        assert not os.path.exists(workflow.workspace_path)


def test_get_workflow_diff(
    app,
    user0,
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
            query_string={"user": user0.id_},
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
    user0,
    sample_yadage_workflow_in_db,
    sample_serial_workflow_in_db,
    tmp_shared_volume_path,
):
    """Test get workspace differences."""
    # create the workspaces for the two workflows
    workspace_path_a = sample_serial_workflow_in_db.workspace_path
    workspace_path_b = sample_yadage_workflow_in_db.workspace_path
    # Create files that differ in one line
    csv_line = "1,2,3,4"
    file_name = "test.csv"
    for index, workspace in enumerate([workspace_path_a, workspace_path_b]):
        with open(
            os.path.join(workspace, file_name),
            "w",
        ) as f:
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
            query_string={"user": user0.id_},
            content_type="application/json",
        )
        assert res.status_code == 200
        response_data = json.loads(res.get_data(as_text=True))
        assert "# File" in response_data["workspace_listing"]


def test_create_interactive_session(
    app, user0, sample_serial_workflow_in_db, interactive_session_environments
):
    """Test create interactive session."""
    wrm = WorkflowRunManager(sample_serial_workflow_in_db)
    expected_data = {"path": wrm._generate_interactive_workflow_path()}
    with app.test_client() as client:
        # create workflow
        with mock.patch.multiple(
            "reana_workflow_controller.k8s",
            current_k8s_corev1_api_client=mock.DEFAULT,
            current_k8s_networking_api_client=mock.DEFAULT,
            current_k8s_appsv1_api_client=mock.DEFAULT,
            UserSecretsStore=mock.DEFAULT,
        ):
            res = client.post(
                url_for(
                    "workflows_session.open_interactive_session",
                    workflow_id_or_name=sample_serial_workflow_in_db.id_,
                    interactive_session_type="jupyter",
                ),
                query_string={"user": user0.id_},
            )
            assert res.json == expected_data


def test_create_interactive_session_unknown_type(
    app, user0, sample_serial_workflow_in_db, interactive_session_environments
):
    """Test create interactive session for unknown interactive type."""
    with app.test_client() as client:
        # create workflow
        res = client.post(
            url_for(
                "workflows_session.open_interactive_session",
                workflow_id_or_name=sample_serial_workflow_in_db.id_,
                interactive_session_type="terminal",
            ),
            query_string={"user": user0.id_},
        )
        assert res.status_code == 404


def test_create_interactive_session_custom_image(
    app, user0, sample_serial_workflow_in_db, interactive_session_environments
):
    """Create an interactive session with custom image."""
    custom_image = "docker_image_2"
    interactive_session_configuration = {"image": custom_image}
    with app.test_client() as client:
        # create workflow
        with mock.patch.multiple(
            "reana_workflow_controller.k8s",
            current_k8s_corev1_api_client=mock.DEFAULT,
            current_k8s_networking_api_client=mock.DEFAULT,
            current_k8s_appsv1_api_client=mock.DEFAULT,
            UserSecretsStore=mock.DEFAULT,
        ) as mocks:
            client.post(
                url_for(
                    "workflows_session.open_interactive_session",
                    workflow_id_or_name=sample_serial_workflow_in_db.id_,
                    interactive_session_type="jupyter",
                ),
                query_string={"user": user0.id_},
                content_type="application/json",
                data=json.dumps(interactive_session_configuration),
            )
            fargs, _ = mocks[
                "current_k8s_appsv1_api_client"
            ].create_namespaced_deployment.call_args
            assert fargs[1].spec.template.spec.containers[0].image == custom_image


def test_close_interactive_session(app, session, user0, sample_serial_workflow_in_db):
    """Test close an interactive session."""
    expected_data = {"message": "The interactive session has been closed"}
    path = "/5d9b30fd-f225-4615-9107-b1373afec070"
    name = "interactive-jupyter-5d9b30fd-f225-4615-9107-b1373afec070-5lswkp"
    int_session = InteractiveSession(
        name=name,
        path=path,
        owner_id=sample_serial_workflow_in_db.owner_id,
    )
    sample_serial_workflow_in_db.sessions.append(int_session)
    session.add(sample_serial_workflow_in_db)
    session.commit()
    with app.test_client() as client:
        with mock.patch(
            "reana_workflow_controller.k8s" ".current_k8s_networking_api_client"
        ):
            res = client.post(
                url_for(
                    "workflows_session.close_interactive_session",
                    workflow_id_or_name=sample_serial_workflow_in_db.id_,
                ),
                query_string={"user": user0.id_},
                content_type="application/json",
            )
        assert res.json == expected_data


def test_close_interactive_session_not_opened(
    app, session, user0, sample_serial_workflow_in_db
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
            query_string={"user": user0.id_},
            content_type="application/json",
        )
        assert res.json == expected_data
        assert res._status_code == 404


def test_get_workflow_retention_rules(app, sample_serial_workflow_with_retention_rule):
    """Test get_workflow_retention_rules for a workflow without retention rules."""
    workflow = sample_serial_workflow_with_retention_rule
    with app.test_client() as client:
        res = client.get(
            url_for(
                "workflows.get_workflow_retention_rules",
                workflow_id_or_name=workflow.id_,
            ),
            query_string={"user": workflow.owner.id_},
        )
        assert res.status_code == 200
        assert res.json["workflow_id"] == str(workflow.id_)
        assert res.json["workflow_name"] == workflow.get_full_workflow_name()
        assert res.json["retention_rules"] == [
            rule.serialize() for rule in workflow.retention_rules
        ]


def test_get_workflow_retention_rules_no_rules(app, sample_serial_workflow_in_db):
    """Test get_workflow_retention_rules for a workflow without retention rules."""
    workflow = sample_serial_workflow_in_db
    with app.test_client() as client:
        res = client.get(
            url_for(
                "workflows.get_workflow_retention_rules",
                workflow_id_or_name=workflow.id_,
            ),
            query_string={"user": workflow.owner.id_},
        )
        assert res.status_code == 200
        assert res.json["workflow_id"] == str(workflow.id_)
        assert res.json["workflow_name"] == workflow.get_full_workflow_name()
        assert res.json["retention_rules"] == []


def test_get_workflow_retention_rules_invalid_workflow(app, user0):
    """Test get_workflow_retention_rules for invalid workflow."""
    with app.test_client() as client:
        res = client.get(
            url_for(
                "workflows.get_workflow_retention_rules",
                workflow_id_or_name="invalid_name",
            ),
            query_string={"user": user0.id_},
        )
        assert res.status_code == 404
        assert b"invalid_name" in res.data


def test_get_workflow_retention_rules_invalid_user(app, sample_serial_workflow_in_db):
    """Test get_workflow_retention_rules for invalid user."""
    workflow = sample_serial_workflow_in_db
    with app.test_client() as client:
        res = client.get(
            url_for(
                "workflows.get_workflow_retention_rules",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": uuid.uuid4()},
        )
        assert res.status_code == 404


def test_share_workflow(
    app, session, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test share workflow."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    share_details = {
        "user_email_to_share_with": user2.email,
    }
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert response_data["message"] == "The workflow has been shared with the user."

    session.query(UserWorkflow).filter_by(user_id=user2.id_).delete()


def test_share_workflow_with_message_and_valid_until(
    app, session, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test share workflow with a message and a valid until date."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    share_details = {
        "user_email_to_share_with": user2.email,
        "message": "This is a shared workflow with a message.",
        "valid_until": "2999-12-31",
    }
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert response_data["message"] == "The workflow has been shared with the user."

    session.query(UserWorkflow).filter_by(user_id=user2.id_).delete()


def test_share_workflow_invalid_email(
    app, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test share workflow with invalid email format."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    invalid_emails = [
        "invalid_email",
        "invalid_email@",
        "@invalid_email.com",
        "invalid_email.com",
        "invalid@ email.com",  # Contains a space
        "invalid email@domain.com",  # Contains a space
        "invalid_email@.com",  # Empty domain
        "invalid_email@com.",  # Empty top-level domain
        "invalid_email@com",  # Missing top-level domain
        "invalid_email@com.",  # Extra dot in top-level domain
    ]

    with app.test_client() as client:
        for invalid_email in invalid_emails:
            share_details = {
                "user_email_to_share_with": invalid_email,
            }

            res = client.post(
                url_for(
                    "workflows.share_workflow",
                    workflow_id_or_name=str(workflow.id_),
                ),
                query_string={
                    "user": str(user2.id_),
                },
                content_type="application/json",
                data=json.dumps(share_details),
            )
            assert res.status_code == 404
            response_data = res.get_json()
            assert (
                response_data["message"]
                == f"User with email '{invalid_email}' does not exist."
            )


def test_share_workflow_with_valid_email_but_unexisting_user(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test share workflow with valid email but unexisting user."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    valid_emails = [
        "valid_email@example.com",
        "another_valid_email@test.org",
        "john.doe@email-domain.net",
        "alice.smith@sub.domain.co.uk",
        "user2234@gmail.com",
        "admin@company.com",
        "support@website.org",
        "marketing@example.net",
        "jane_doe@sub.example.co",
        "user.name@sub.domain.co.uk",
    ]

    with app.test_client() as client:
        for valid_email in valid_emails:
            share_details = {
                "user_email_to_share_with": valid_email,
            }

            res = client.post(
                url_for(
                    "workflows.share_workflow",
                    workflow_id_or_name=str(workflow.id_),
                ),
                query_string={
                    "user": str(user1.id_),
                },
                content_type="application/json",
                data=json.dumps(share_details),
            )
            assert res.status_code == 404
            response_data = res.get_json()
            assert (
                response_data["message"]
                == f"User with email '{valid_email}' does not exist."
            )


def test_share_workflow_with_invalid_date_format(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test share workflow with an invalid date format for 'valid_until'."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    share_details = {
        "user_email_to_share_with": user2.email,
        "valid_until": "invalid date",  # Invalid format
    }
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 400
        response_data = res.get_json()
        assert (
            response_data["message"]
            == "Field 'valid_until': Date format is not valid. Please use YYYY-MM-DD format."
        )


def test_share_non_existent_workflow(app, user1, user2):
    """Test sharing a non-existent workflow."""
    non_existent_workflow_id = "non_existent_workflow_id"
    share_details = {
        "user_email_to_share_with": user2.email,
    }
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=non_existent_workflow_id,
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 400
        response_data = res.get_json()
        assert (
            response_data["message"]
            == f"REANA_WORKON is set to {non_existent_workflow_id}, but that workflow does not exist. Please set your REANA_WORKON environment variable appropriately."
        )


def test_share_workflow_with_self(
    app, user1, sample_serial_workflow_in_db_owned_by_user1
):
    """Test attempting to share a workflow with yourself."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    share_details = {
        "user_email_to_share_with": user1.email,
    }
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 400
        response_data = res.get_json()
        assert response_data["message"] == "Unable to share a workflow with yourself."


def test_share_workflow_already_shared(
    app, session, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test attempting to share a workflow that is already shared with the user."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    share_details = {
        "user_email_to_share_with": user2.email,
    }
    with app.test_client() as client:
        client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )

    # Attempt to share the same workflow again
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 409
        response_data = res.get_json()
        assert (
            response_data["message"]
            == f"{workflow.get_full_workflow_name()} is already shared with {user2.email}."
        )

    session.query(UserWorkflow).filter_by(user_id=user2.id_).delete()


def test_share_workflow_with_past_valid_until_date(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test share workflow with a 'valid_until' date in the past."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    share_details = {
        "user_email_to_share_with": user2.email,
        "valid_until": "2021-01-01",  # A date in the past
    }
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 400
        response_data = res.get_json()
        assert (
            response_data["message"] == "The 'valid_until' date cannot be in the past."
        )


def test_share_workflow_with_long_message(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test share workflow with a message exceeding 5000 characters."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    long_message = "A" * 5001  # A message exceeding the 5000-character limit
    share_details = {
        "user_email_to_share_with": user2.email,
        "message": long_message,
    }
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 400
        response_data = res.get_json()
        assert (
            response_data["message"]
            == "Field 'message': Message is too long. Please keep it under 5000 characters."
        )


def test_share_multiple_workflows(
    app,
    session,
    user1,
    user2,
    sample_serial_workflow_in_db_owned_by_user1,
    sample_yadage_workflow_in_db_owned_by_user1,
):
    """Test sharing multiple workflows with different users."""
    workflow1 = sample_serial_workflow_in_db_owned_by_user1
    share_details = {
        "user_email_to_share_with": user2.email,
    }
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow1.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert response_data["message"] == "The workflow has been shared with the user."

    workflow2 = sample_yadage_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow2.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
            content_type="application/json",
            data=json.dumps(share_details),
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert response_data["message"] == "The workflow has been shared with the user."

    session.query(UserWorkflow).filter_by(user_id=user2.id_).delete()


def test_unshare_workflow(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test unshare workflow."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # share workflow
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps({"user_email_to_share_with": user2.email}),
        )
        assert res.status_code == 200
        # unshare workflow
        res = client.post(
            url_for(
                "workflows.unshare_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_unshare_with": user2.email,
            },
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert (
            response_data["message"] == "The workflow has been unshared with the user."
        )


def test_unshare_workflow_not_shared(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test unshare workflow that is not shared with the user."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # unshare workflow
        res = client.post(
            url_for(
                "workflows.unshare_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_unshare_with": user2.email,
            },
        )
        assert res.status_code == 409
        response_data = res.get_json()
        assert (
            response_data["message"]
            == f"{workflow.get_full_workflow_name()} is not shared with {user2.email}."
        )


def test_unshare_workflow_with_self(
    app, user1, sample_serial_workflow_in_db_owned_by_user1
):
    """Test attempting to unshare a workflow with yourself."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.unshare_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_unshare_with": user1.email,
            },
        )
        assert res.status_code == 400
        response_data = res.get_json()
        assert response_data["message"] == "Unable to unshare a workflow with yourself."


def test_unshare_workflow_with_invalid_email(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test unshare workflow with invalid email format."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    invalid_emails = [
        "invalid_email",
        "invalid_email@",
        "@invalid_email.com",
        "invalid_email.com",
        "invalid@ email.com",  # Contains a space
        "invalid @email",  # Contains a space
        "invalid_email@.com",  # Empty domain
        "invalid_email@com.",  # Empty top-level domain
        "invalid_email@com",  # Missing top-level domain
        "invalid_email@com.",  # Extra dot in top-level domain
    ]

    with app.test_client() as client:
        for invalid_email in invalid_emails:
            res = client.post(
                url_for(
                    "workflows.unshare_workflow",
                    workflow_id_or_name=str(workflow.id_),
                ),
                query_string={
                    "user": str(user1.id_),
                    "user_email_to_unshare_with": invalid_email,
                },
            )
            assert res.status_code == 404
            response_data = res.get_json()
            assert (
                response_data["message"]
                == f"User with email '{invalid_email}' does not exist."
            )


def test_unshare_workflow_with_valid_email_but_unexisting_user(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test unshare workflow with valid email but unexisting user."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    valid_emails = [
        "valid_email@example.com",
        "another_valid_email@test.org",
        "john.doe@email-domain.net",
        "alice.smith@sub.domain.co.uk",
        "user2234@gmail.com",
        "admin@company.com",
        "support@website.org",
        "marketing@example.net",
        "jane_doe@sub.example.co",
        "user.name@sub.domain.co.uk",
    ]

    with app.test_client() as client:
        for valid_email in valid_emails:
            res = client.post(
                url_for(
                    "workflows.unshare_workflow",
                    workflow_id_or_name=str(workflow.id_),
                ),
                query_string={
                    "user": str(user1.id_),
                    "user_email_to_unshare_with": valid_email,
                },
            )
            assert res.status_code == 404
            response_data = res.get_json()
            assert (
                response_data["message"]
                == f"User with email '{valid_email}' does not exist."
            )


def test_unshare_non_existent_workflow(app, user1, user2):
    """Test unsharing a non-existent workflow."""
    non_existent_workflow_id = "non_existent_workflow_id"
    with app.test_client() as client:
        res = client.post(
            url_for(
                "workflows.unshare_workflow",
                workflow_id_or_name=non_existent_workflow_id,
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_unshare_with": user2.email,
            },
        )
        assert res.status_code == 400
        response_data = res.get_json()
        assert (
            response_data["message"]
            == f"REANA_WORKON is set to {non_existent_workflow_id}, but that workflow does not exist. Please set your REANA_WORKON environment variable appropriately."
        )


def test_unshare_workflow_already_unshared(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test unsharing a workflow that is already unshared with the user."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # unshare workflow
        res = client.post(
            url_for(
                "workflows.unshare_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_unshare_with": user2.email,
            },
        )
        assert res.status_code == 409
        response_data = res.get_json()
        assert (
            response_data["message"]
            == f"{workflow.get_full_workflow_name()} is not shared with {user2.email}."
        )


def test_unshare_multiple_workflows(
    app,
    user1,
    user2,
    sample_serial_workflow_in_db_owned_by_user1,
    sample_yadage_workflow_in_db_owned_by_user1,
):
    """Test unsharing multiple workflows with different users."""
    workflow1 = sample_serial_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # share workflow
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow1.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps({"user_email_to_share_with": user2.email}),
        )
        assert res.status_code == 200
        # unshare workflow
        res = client.post(
            url_for(
                "workflows.unshare_workflow",
                workflow_id_or_name=str(workflow1.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_unshare_with": user2.email,
            },
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert (
            response_data["message"] == "The workflow has been unshared with the user."
        )

    workflow2 = sample_yadage_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # share workflow
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow2.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps({"user_email_to_share_with": user2.email}),
        )
        assert res.status_code == 200
        # unshare workflow
        res = client.post(
            url_for(
                "workflows.unshare_workflow",
                workflow_id_or_name=str(workflow2.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_unshare_with": user2.email,
            },
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert (
            response_data["message"] == "The workflow has been unshared with the user."
        )


def test_unshare_workflow_with_message_and_valid_until(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test unshare workflow with a message and a valid until date."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    message = "This is a shared workflow with a message."
    valid_until = "2123-12-31"
    with app.test_client() as client:
        # share workflow
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps(
                {
                    "user_email_to_share_with": user2.email,
                    "message": message,
                    "valid_until": valid_until,
                }
            ),
        )
        assert res.status_code == 200
        # unshare workflow
        res = client.post(
            url_for(
                "workflows.unshare_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_unshare_with": user2.email,
            },
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert (
            response_data["message"] == "The workflow has been unshared with the user."
        )


def test_get_workflow_share_status(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test get_workflow_share_status."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # share workflow
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps({"user_email_to_share_with": user2.email}),
        )
        assert res.status_code == 200
        # get workflow share status
        res = client.get(
            url_for(
                "workflows.get_workflow_share_status",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
                "user_email_to_check": user2.email,
            },
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert response_data["shared_with"][0]["user_email"] == "user2@reana.io"


def test_get_workflow_share_status_not_shared(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    """Test get_workflow_share_status for a workflow that is not shared."""
    workflow = sample_serial_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # get workflow share status
        res = client.get(
            url_for(
                "workflows.get_workflow_share_status",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
        )
        assert res.status_code == 200
        response_data = res.get_json()
        assert response_data["shared_with"] == []


def test_get_workflow_share_status_valid_until_not_set(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    workflow = sample_serial_workflow_in_db_owned_by_user1
    with app.test_client() as client:
        # Share the workflow without setting valid_until
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps({"user_email_to_share_with": user2.email}),
        )
        assert res.status_code == 200
        res = client.get(
            url_for(
                "workflows.get_workflow_share_status",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
        )
        assert res.status_code == 200
        response_data = res.get_json()
        shared_with = response_data["shared_with"][0]
        assert shared_with["valid_until"] is None


def test_get_workflow_share_status_valid_until_set(
    app, user1, user2, sample_serial_workflow_in_db_owned_by_user1
):
    workflow = sample_serial_workflow_in_db_owned_by_user1
    valid_until = "2123-12-31"
    with app.test_client() as client:
        # Share the workflow setting valid_until
        res = client.post(
            url_for(
                "workflows.share_workflow",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={"user": str(user1.id_)},
            content_type="application/json",
            data=json.dumps(
                {
                    "user_email_to_share_with": user2.email,
                    "valid_until": valid_until,
                }
            ),
        )
        assert res.status_code == 200
        res = client.get(
            url_for(
                "workflows.get_workflow_share_status",
                workflow_id_or_name=str(workflow.id_),
            ),
            query_string={
                "user": str(user1.id_),
            },
        )
        assert res.status_code == 200
        response_data = res.get_json()
        shared_with = response_data["shared_with"][0]
        assert shared_with["valid_until"] == valid_until + "T00:00:00"
