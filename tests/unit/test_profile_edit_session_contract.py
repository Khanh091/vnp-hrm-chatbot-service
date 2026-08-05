from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.integrations.odoo.profile_schema import (
    ProfileExecutionResult,
    ProfileField,
    ProfileOption,
    ProfileOptionList,
    ProfileRecord,
    ProfileResource,
    ProfileSchemaError,
    ProfileWriteMode,
)
from app.orchestration.nodes.execute_write_tool import _execute_profile_action
from app.orchestration.nodes.merge_clarification import merge_clarification_node
from app.orchestration.nodes.resolve_profile_write import (
    _clear_invalid_dependents,
    _draft_field_rows,
    _validate_current_option_sets,
    _validate_profile_fields,
    _verify_saved_draft,
    profile_values_equal,
)
from app.orchestration.state import ChatResponseType
from app.routing.taxonomy import Operation
from tests.unit.test_profile_crud_targeted import (
    BASIC,
    CONTACT,
    EMAIL,
    MOBILE,
    run_target,
)


def _field(key, field_type="text", **values):
    return ProfileField(
        key=key,
        label=values.pop("label", key),
        field_type=field_type,
        readable=True,
        creatable=True,
        updatable=True,
        deletable=False,
        write_mode=ProfileWriteMode.APPROVAL_REQUEST,
        **values,
    )


class _OptionSchema:
    def __init__(self, token="token-current", value="3"):
        self.token = token
        self.value = value
        self.calls = 0

    async def get_field_option_set(self, resource, field, query, context, **kwargs):
        self.calls += 1
        return ProfileOptionList(
            resource_key=resource,
            field_key=field,
            option_set_id=self.token,
            depends_on=context,
            items=(ProfileOption(value=self.value, label="TOEIC"),),
        )


def _merge_state(*, token="token-current", client_action_id=None, applied=None):
    client_action_id = client_action_id or f"client-{uuid4()}"
    metadata = {
        "input_type": "record_form",
        "slot_name": "profile_edit_action",
        "session_id": "profile-session",
        "form_revision": "form-1",
        "resource_key": "certificate_records",
        "fields": [
            {
                "field_key": "certificate_type",
                "input_type": "searchable_select",
                "readonly": False,
                "options_context_keys": [],
                "current_raw_value": None,
                "draft_raw_value": None,
            }
        ],
    }
    return {
        "conversation_id": "conv-1",
        "request_id": "req-1",
        "trusted_context": {"odoo_user_id": 7},
        "pending_tool_name": "profile_crud_workflow",
        "missing_arguments": ["profile_edit_action"],
        "ambiguous_arguments": [],
        "collected_arguments": {},
        "workflow_data": {
            "current_field": "profile_edit_action",
            "profile_edit_session_id": "profile-session",
            "profile_form_revision": "form-1",
            "profile_form_field_keys": ["certificate_type"],
            "profile_applied_action_ids": applied or [],
            "clarification_options": [],
            "clarification_metadata": metadata,
        },
        "clarification": {
            "answer_type": "profile_field_edit",
            "field": "certificate_type",
            "value": "3",
            "label": "TOEIC",
            "session_id": "profile-session",
            "form_revision": "form-1",
            "client_action_id": client_action_id,
            "option_set_id": token,
            "option_context": {},
        },
        "user_message": "TOEIC",
    }, client_action_id


def _merge_runtime(schema):
    return SimpleNamespace(context=SimpleNamespace(
        profile_schema_client=schema,
        workflow_registry=SimpleNamespace(get=lambda _name: None),
    ))


def test_01_singleton_diff_contains_only_touched_field():
    rows = _draft_field_rows(
        [MOBILE, EMAIL],
        {MOBILE.key: "0900", EMAIL.key: "old@vnpt.vn"},
        {MOBILE.key: "0911"},
    )
    assert [row["field_key"] for row in rows if row["status"] == "changed"] == [
        MOBILE.key
    ]


@pytest.mark.asyncio
async def test_02_review_excludes_unrelated_snapshot_fields():
    form, _, _ = await run_target(section=BASIC.key, resource=CONTACT.key)
    edited, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={MOBILE.key: "0987654321"},
        previous_workflow=form["workflow_data"],
        answer_field=MOBILE.key, answer_type="profile_field_edit",
    )
    review, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "finish"},
        previous_workflow=edited["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert [
        row["field_key"]
        for row in review["response_data"]["clarification"]["fields"]
    ] == [MOBILE.key]


@pytest.mark.asyncio
async def test_03_save_draft_calls_odoo_and_waits_for_ack():
    reviewed, _, _ = await _review_mobile()
    saved, _, schema = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "save_draft"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert len(schema.saved_drafts) == 1
    assert saved["response_data"]["draft_saved"] is True


@pytest.mark.asyncio
async def test_04_save_draft_is_visible_after_reload():
    reviewed, _, _ = await _review_mobile()
    saved, _, schema = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "save_draft"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
    )
    reloaded = await schema.get_current_snapshot(CONTACT.key)
    assert saved["response_data"]["draft_saved"] is True
    assert reloaded.snapshot[MOBILE.key] == "0987654321"


@pytest.mark.asyncio
async def test_04b_collection_draft_verification_retries_stale_reload(
    monkeypatch,
):
    field = _field("issuer")
    resource = ProfileResource(
        key="certificate_records",
        label="Văn bằng, chứng chỉ",
        section_key="education_training",
        resource_type="collection",
        readable=True,
        creatable=True,
        updatable=True,
        deletable=True,
        fields=(field,),
    )

    class _EventuallyConsistentSchema:
        calls = 0

        async def get_record(self, *_args, **_kwargs):
            self.calls += 1
            value = "" if self.calls == 1 else "PTIT"
            return ProfileRecord(
                record_id=18,
                label="A1",
                snapshot={"issuer": value},
                version=f"version-{self.calls}",
                can_update=True,
                can_delete=True,
            )

    async def _no_wait(_delay):
        return None

    monkeypatch.setattr(
        "app.orchestration.nodes.resolve_profile_write.asyncio.sleep",
        _no_wait,
    )
    schema = _EventuallyConsistentSchema()
    runtime = SimpleNamespace(
        context=SimpleNamespace(profile_schema_client=schema)
    )
    result = ProfileExecutionResult(
        resource_key=resource.key,
        operation="create",
        write_mode="approval_request",
        draft_saved=True,
        record_id=18,
    )

    await _verify_saved_draft(
        {
            "conversation_id": "conv-cert",
            "request_id": "req-cert",
            "trusted_context": {"odoo_user_id": 7},
        },
        runtime,
        None,
        resource,
        Operation.CREATE,
        None,
        {"issuer": "PTIT"},
        result,
    )

    assert schema.calls == 2


@pytest.mark.asyncio
async def test_05_save_failure_keeps_session_and_never_reports_success():
    reviewed, _, _ = await _review_mobile()
    failed, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "save_draft"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
        schema_error=ProfileSchemaError("PROFILE_INVALID_VALUE", "invalid"),
    )
    assert failed["workflow_data"]["profile_changes"] == {
        MOBILE.key: "0987654321"
    }
    assert failed.get("response_data", {}).get("draft_saved") is not True


@pytest.mark.asyncio
async def test_06_submit_creates_pending_action_only_after_review():
    reviewed, pending, _ = await _review_mobile()
    assert pending.created == []
    confirmation, pending, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "submit"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert len(pending.created) == 1
    assert confirmation["response_data"]["message_type"] == "confirmation"


@pytest.mark.asyncio
async def test_07_confirm_submit_executes_approval_once():
    context, action, state = _execution_fixture()
    result = await _execute_profile_action(
        state, SimpleNamespace(context=context), action, 0.0
    )
    assert context.profile_schema_client.calls == 1
    assert result["response_type"].value == "answer"


@pytest.mark.asyncio
async def test_08_submit_failure_restores_retryable_review():
    context, action, state = _execution_fixture(error=True)
    result = await _execute_profile_action(
        state, SimpleNamespace(context=context), action, 0.0
    )
    assert result["response_data"]["retryable"] is True
    assert result["workflow_data"]["profile_changes"][MOBILE.key] == "0987654321"


@pytest.mark.asyncio
async def test_09_valid_option_is_applied_once():
    schema = _OptionSchema()
    state, _ = _merge_state()
    result = await merge_clarification_node(state, _merge_runtime(schema))
    assert result["collected_arguments"]["certificate_type"] == "3"
    assert schema.calls == 1


@pytest.mark.asyncio
async def test_10_stale_option_returns_one_typed_error():
    schema = _OptionSchema(token="new-token")
    state, _ = _merge_state(token="old-token")
    result = await merge_clarification_node(state, _merge_runtime(schema))
    assert result["response_data"]["error_code"] == "PROFILE_OPTION_SET_STALE"
    assert len(result["response_data"]["field_errors"]) == 1


@pytest.mark.asyncio
async def test_10b_stale_form_revision_returns_current_form_for_recovery():
    state, _ = _merge_state()
    state["clarification"]["answer_type"] = "profile_edit_action"
    state["clarification"]["field"] = None
    state["clarification"]["value"] = "finish"
    state["clarification"]["form_revision"] = "form-stale"
    state["workflow_data"]["clarification_options"] = [
        {"value": "finish", "label": "Hoàn tất"},
        {"value": "cancel", "label": "Hủy"},
    ]

    result = await merge_clarification_node(
        state, _merge_runtime(_OptionSchema())
    )

    assert result["response_type"] is ChatResponseType.CLARIFICATION_REQUIRED
    assert result["response_data"]["error_code"] == (
        "PROFILE_EDIT_SESSION_INVALID_STATE"
    )
    current = result["response_data"]["clarification"]
    assert current["form_revision"] == "form-1"
    assert current["session_id"] == "profile-session"


@pytest.mark.asyncio
async def test_11_stale_option_does_not_mutate_draft_arguments():
    schema = _OptionSchema(token="new-token")
    state, _ = _merge_state(token="old-token")
    result = await merge_clarification_node(state, _merge_runtime(schema))
    assert "collected_arguments" not in result
    assert state["collected_arguments"] == {}


@pytest.mark.asyncio
async def test_11b_employee_option_resolves_persisted_subject():
    state = {
        "conversation_id": "conv-directory",
        "request_id": "req-directory",
        "trusted_context": {"odoo_user_id": 7},
        "pending_tool_name": "employee_get_employment",
        "missing_arguments": ["employee_id"],
        "ambiguous_arguments": [],
        "collected_arguments": {},
        "workflow_data": {
            "current_field": "employee_id",
            "clarification_options": [
                {
                    "value": 42,
                    "label": "NGUYỄN ANH TUẤN · Mã NV: 00234086",
                    "employee_code": "00234086",
                }
            ],
            "subject_resolution": {
                "status": "ambiguous",
                "subject": None,
                "options": [
                    {
                        "value": 42,
                        "label": "NGUYỄN ANH TUẤN · Mã NV: 00234086",
                        "employee_code": "00234086",
                    }
                ],
                "reason_code": "SUBJECT_AMBIGUOUS",
            },
        },
        "clarification": {
            "answer_type": "option_select",
            "field": "employee_id",
            "value": "42",
            "label": "NGUYỄN ANH TUẤN · Mã NV: 00234086",
        },
        "user_message": "NGUYỄN ANH TUẤN",
        "stage_timings": {},
        "graph_events": [],
    }
    tool = SimpleNamespace(enabled=True)
    runtime = SimpleNamespace(
        context=SimpleNamespace(
            tool_registry=SimpleNamespace(get=lambda _name: tool),
            workflow_registry=SimpleNamespace(get=lambda _name: None),
        )
    )

    result = await merge_clarification_node(state, runtime)

    assert result["collected_arguments"]["employee_id"] == 42
    assert result["workflow_data"]["subject_resolution"] == {
        "status": "resolved",
        "subject": {
            "type": "employee",
            "employee_id": 42,
            "employee_code": "00234086",
            "source": "structured_option",
        },
        "options": [],
        "reason_code": "SUBJECT_RESOLVED",
    }


def test_12_dependency_change_clears_all_invalid_descendants():
    parent = _field("certificate_type", "many2one")
    child = _field(
        "certificate_field", "many2one", depends_on=(parent.key,),
        clear_when_dependency_changes=True,
    )
    grandchild = _field(
        "certificate_catalog", "many2one", depends_on=(child.key,),
        clear_when_dependency_changes=True,
    )
    changes = {parent.key: "2", child.key: "4", grandchild.key: "8"}
    labels = {child.key: "English", grandchild.key: "TOEIC"}
    tokens = {child.key: {}, grandchild.key: {}}
    _clear_invalid_dependents(
        (parent, child, grandchild), parent.key, changes, labels, tokens
    )
    assert changes == {parent.key: "2"}
    assert labels == {}
    assert tokens == {}


def test_13_create_finish_is_blocked_when_required_is_missing():
    required = _field("issue_date", "date", required_on_create=True)
    assert _validate_profile_fields(
        [required], {}, operation=Operation.CREATE
    ) == {required.key: "Vui lòng nhập issue_date."}


@pytest.mark.asyncio
async def test_14_finish_is_blocked_when_option_version_changed():
    field = _field(
        "certificate_type", "many2one",
        option_provider="certificate_type_options",
    )
    schema = _OptionSchema(token="new-token")
    state = {"trusted_context": {"odoo_user_id": 7}, "request_id": "req"}
    workflow = {
        "profile_option_sets": {
            field.key: {
                "option_set_id": "old-token", "depends_on": {}, "value": "3"
            }
        },
        "profile_current_snapshot": {},
    }
    errors = await _validate_current_option_sets(
        state, _merge_runtime(schema),
        SimpleNamespace(key="certificate_records"), [field],
        {field.key: "3"}, workflow,
    )
    assert field.key in errors


def test_15_invalid_date_range_is_blocked_before_review():
    start = _field("training_from", "date")
    end = _field("training_to", "date", validator="gte:training_from")
    errors = _validate_profile_fields(
        [start, end],
        {start.key: "2026-08-05", end.key: "2026-01-01"},
        operation=Operation.CREATE,
    )
    assert end.key in errors


@pytest.mark.asyncio
async def test_16_replayed_client_action_is_rejected_before_apply():
    state, action_id = _merge_state(client_action_id="client-replayed")
    state["workflow_data"]["profile_applied_action_ids"] = [action_id]
    result = await merge_clarification_node(state, _merge_runtime(_OptionSchema()))
    assert result["response_data"]["error_code"] == "PROFILE_ACTION_REPLAYED"


@pytest.mark.asyncio
async def test_17_continue_from_review_preserves_draft():
    reviewed, _, _ = await _review_mobile()
    resumed, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "continue"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert resumed["workflow_data"]["profile_changes"] == {
        MOBILE.key: "0987654321"
    }


@pytest.mark.asyncio
async def test_18_successful_save_closes_active_session_state():
    reviewed, _, _ = await _review_mobile()
    saved, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "save_draft"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert saved["workflow_data"] == {}
    assert saved["pending_tool_name"] is None


def test_19_canonical_many2one_label_change_does_not_create_diff():
    field = _field("permanent_province", "many2one")
    assert profile_values_equal(
        field,
        {"value": "1", "label": "TP. Hà Nội"},
        {"value": "1", "label": "Hà Nội"},
    )


def test_20_untouched_stale_collected_values_are_not_reviewed():
    fields = [_field("place_of_birth"), _field("permanent_province", "many2one")]
    rows = _draft_field_rows(
        fields,
        {
            "place_of_birth": "Hà Tây",
            "permanent_province": {"value": "1", "label": "Hà Nội"},
        },
        {"place_of_birth": "Hà Tây mới"},
    )
    assert [row["field_key"] for row in rows if row["status"] == "changed"] == [
        "place_of_birth"
    ]


async def _review_mobile():
    form, _, _ = await run_target(section=BASIC.key, resource=CONTACT.key)
    edited, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={MOBILE.key: "0987654321"},
        previous_workflow=form["workflow_data"],
        answer_field=MOBILE.key, answer_type="profile_field_edit",
    )
    return await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "finish"},
        previous_workflow=edited["workflow_data"],
        answer_field="profile_edit_action",
    )


def _execution_fixture(error=False):
    class Schema:
        calls = 0

        async def execute_change_request(self, *args, **kwargs):
            self.calls += 1
            if error:
                raise ProfileSchemaError("PROFILE_SUBMIT_FAILED", "failed")
            return ProfileExecutionResult(
                section_key="basic_profile", operation="update",
                write_mode="approval_request", request_id=10, state="wait",
            )

    class Pending:
        async def finish(self, *args, **kwargs):
            return None

    class Conversations:
        async def load_owned(self, *args, **kwargs):
            return SimpleNamespace()

        async def update(self, *args, **kwargs):
            return None

    workflow = {
        "profile_edit_session_id": "profile-session",
        "profile_changes": {MOBILE.key: "0987654321"},
    }
    action = SimpleNamespace(
        action_id="action-1",
        idempotency_key="idem-1",
        validated_arguments={
            "operation": "update", "section_key": "basic_profile",
            "changes": workflow["profile_changes"],
            "write_mode": "approval_request",
        },
        display_summary={
            "workflow_data": workflow,
            "review": {"session_id": "profile-session", "fields": []},
        },
    )
    context = SimpleNamespace(
        profile_schema_client=Schema(), pending_action_service=Pending(),
        conversation_service=Conversations(),
    )
    state = {
        "conversation_id": "conv-1", "request_id": "req-1",
        "trusted_context": {"odoo_user_id": 7},
    }
    return context, action, state
