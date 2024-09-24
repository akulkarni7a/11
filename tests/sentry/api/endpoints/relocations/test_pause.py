from datetime import datetime, timezone
from uuid import uuid4

from sentry.api.endpoints.relocations import (
    ERR_COULD_NOT_PAUSE_RELOCATION_AT_STEP,
    ERR_UNKNOWN_RELOCATION_STEP,
)
from sentry.api.endpoints.relocations.pause import (
    ERR_COULD_NOT_PAUSE_RELOCATION,
    ERR_NOT_PAUSABLE_STATUS,
)
from sentry.models.relocation import Relocation
from sentry.testutils.cases import APITestCase
from sentry.testutils.helpers.options import override_options
from sentry.utils.relocation import OrderedTask

TEST_DATE_ADDED = datetime(2023, 1, 23, 1, 23, 45, tzinfo=timezone.utc)


class PauseRelocationTest(APITestCase):
    endpoint = "sentry-api-0-relocations-pause"
    method = "put"

    def setUp(self):
        super().setUp()
        self.owner = self.create_user(
            email="owner", is_superuser=False, is_staff=True, is_active=True
        )
        self.superuser = self.create_user(is_superuser=True)
        self.staff_user = self.create_user(is_staff=True)
        self.relocation: Relocation = Relocation.objects.create(
            date_added=TEST_DATE_ADDED,
            creator_id=self.superuser.id,
            owner_id=self.owner.id,
            status=Relocation.Status.IN_PROGRESS.value,
            step=Relocation.Step.PREPROCESSING.value,
            provenance=Relocation.Provenance.SELF_HOSTED.value,
            want_org_slugs=["foo"],
            want_usernames=["alice", "bob"],
            latest_notified=Relocation.EmailKind.STARTED.value,
            latest_task=OrderedTask.PREPROCESSING_SCAN.name,
            latest_task_attempts=1,
        )

    @override_options({"staff.ga-rollout": True})
    def test_good_staff_pause_asap(self):
        self.login_as(user=self.staff_user, staff=True)
        response = self.get_success_response(self.relocation.uuid, status_code=200)

        assert response.data["status"] == Relocation.Status.IN_PROGRESS.name
        assert response.data["step"] == Relocation.Step.PREPROCESSING.name
        assert response.data["scheduledPauseAtStep"] == Relocation.Step.VALIDATING.name

    def test_good_pause_asap(self):
        self.login_as(user=self.superuser, superuser=True)
        response = self.get_success_response(self.relocation.uuid, status_code=200)

        assert response.data["status"] == Relocation.Status.IN_PROGRESS.name
        assert response.data["step"] == Relocation.Step.PREPROCESSING.name
        assert response.data["scheduledPauseAtStep"] == Relocation.Step.VALIDATING.name

    def test_good_pause_at_next_step(self):
        self.login_as(user=self.superuser, superuser=True)
        response = self.get_success_response(
            self.relocation.uuid, atStep=Relocation.Step.VALIDATING.name, status_code=200
        )

        assert response.data["status"] == Relocation.Status.IN_PROGRESS.name
        assert response.data["step"] == Relocation.Step.PREPROCESSING.name
        assert response.data["scheduledPauseAtStep"] == Relocation.Step.VALIDATING.name

    def test_good_pause_at_future_step(self):
        self.login_as(user=self.superuser, superuser=True)
        response = self.get_success_response(
            self.relocation.uuid, atStep=Relocation.Step.NOTIFYING.name, status_code=200
        )

        assert response.data["status"] == Relocation.Status.IN_PROGRESS.name
        assert response.data["step"] == Relocation.Step.PREPROCESSING.name
        assert response.data["scheduledPauseAtStep"] == Relocation.Step.NOTIFYING.name

    def test_good_already_paused(self):
        self.login_as(user=self.superuser, superuser=True)
        self.relocation.status = Relocation.Status.PAUSE.value
        self.relocation.save()
        response = self.get_success_response(
            self.relocation.uuid, atStep=Relocation.Step.IMPORTING.name, status_code=200
        )

        assert response.data["status"] == Relocation.Status.PAUSE.name
        assert response.data["step"] == Relocation.Step.PREPROCESSING.name
        assert response.data["scheduledPauseAtStep"] == Relocation.Step.IMPORTING.name

    def test_bad_not_found(self):
        self.login_as(user=self.superuser, superuser=True)
        does_not_exist_uuid = uuid4().hex
        response = self.client.put(f"/api/0/relocations/{str(does_not_exist_uuid)}/pause/")

        assert response.status_code == 404

    def test_bad_already_completed(self):
        self.login_as(user=self.superuser, superuser=True)
        self.relocation.status = Relocation.Status.FAILURE.value
        self.relocation.save()
        response = self.get_error_response(self.relocation.uuid, status_code=400)

        assert response.data.get("detail") is not None
        assert response.data.get("detail") == ERR_NOT_PAUSABLE_STATUS.substitute(
            status=Relocation.Status.FAILURE.name
        )

    def test_bad_invalid_step(self):
        self.login_as(user=self.superuser, superuser=True)
        response = self.get_error_response(
            self.relocation.uuid, atStep="nonexistent", status_code=400
        )

        assert response.data.get("detail") is not None
        assert response.data.get("detail") == ERR_UNKNOWN_RELOCATION_STEP.substitute(
            step="nonexistent"
        )

    def test_bad_unknown_step(self):
        self.login_as(user=self.superuser, superuser=True)
        response = self.get_error_response(
            self.relocation.uuid, atStep=Relocation.Step.UNKNOWN.name, status_code=400
        )

        assert response.data.get("detail") is not None
        assert response.data.get("detail") == ERR_COULD_NOT_PAUSE_RELOCATION_AT_STEP.substitute(
            step=Relocation.Step.UNKNOWN.name
        )

    def test_bad_current_step(self):
        self.login_as(user=self.superuser, superuser=True)
        response = self.get_error_response(
            self.relocation.uuid, atStep=Relocation.Step.PREPROCESSING.name, status_code=400
        )

        assert response.data.get("detail") is not None
        assert response.data.get("detail") == ERR_COULD_NOT_PAUSE_RELOCATION_AT_STEP.substitute(
            step=Relocation.Step.PREPROCESSING.name
        )

    def test_bad_past_step(self):
        self.login_as(user=self.superuser, superuser=True)
        response = self.get_error_response(
            self.relocation.uuid, atStep=Relocation.Step.UPLOADING.name, status_code=400
        )

        assert response.data.get("detail") is not None
        assert response.data.get("detail") == ERR_COULD_NOT_PAUSE_RELOCATION_AT_STEP.substitute(
            step=Relocation.Step.UPLOADING.name
        )

    def test_bad_last_step_specified(self):
        self.login_as(user=self.superuser, superuser=True)
        response = self.get_error_response(
            self.relocation.uuid, atStep=Relocation.Step.COMPLETED.name, status_code=400
        )

        assert response.data.get("detail") is not None
        assert response.data.get("detail") == ERR_COULD_NOT_PAUSE_RELOCATION_AT_STEP.substitute(
            step=Relocation.Step.COMPLETED.name
        )

    def test_bad_last_step_automatic(self):
        self.login_as(user=self.superuser, superuser=True)
        self.relocation.step = Relocation.Step.NOTIFYING.value
        self.relocation.save()
        response = self.get_error_response(self.relocation.uuid, status_code=400)

        assert response.data.get("detail") is not None
        assert response.data.get("detail") == ERR_COULD_NOT_PAUSE_RELOCATION

    def test_bad_no_auth(self):
        self.get_error_response(self.relocation.uuid, status_code=401)

    def test_bad_no_superuser(self):
        self.login_as(user=self.superuser, superuser=False)
        self.get_error_response(self.relocation.uuid, status_code=403)
