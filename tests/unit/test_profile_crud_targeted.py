from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.context.conversation import PendingActionStatus
from app.context.pending_action_service import PendingActionError, PendingActionService
from app.integrations.odoo.profile_schema import (
    ProfileExecutionResult,
    ProfileField,
    ProfileRecord,
    ProfileResource,
    ProfileSchemaError,
    ProfileSection,
    ProfileSnapshot,
    ProfileWriteMode,
)
from app.orchestration.nodes.execute_write_tool import execute_write_tool_node
from app.orchestration.nodes.resolve_profile_write import resolve_profile_write_node
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import Intent, Operation, QueryRoute, SubjectScope

PHONE = ProfileField(
    key="mobile_phone", label="Số điện thoại", field_type="phone",
    readable=True, creatable=False, updatable=True, deletable=False,
    write_mode=ProfileWriteMode.APPROVAL_REQUEST,
)
DEPARTMENT = ProfileField(
    key="department", label="Phòng ban", field_type="many2one",
    readable=True, creatable=False, updatable=False, deletable=False,
    write_mode=ProfileWriteMode.FORBIDDEN,
)
CERTIFICATE = ProfileField(
    key="certificate_name", label="Tên chứng chỉ", field_type="text",
    readable=True, creatable=True, updatable=True, deletable=True,
    required_on_create=True, write_mode=ProfileWriteMode.APPROVAL_REQUEST,
)
CONTACT = ProfileResource(
    key="contact_information", label="Thông tin liên hệ",
    section_key="basic_profile", resource_type="singleton", readable=True,
    creatable=False, updatable=True, deletable=False, fields=(PHONE,),
)
EMPLOYMENT = ProfileResource(
    key="employment_information", label="Thông tin công việc",
    section_key="basic_profile", resource_type="singleton", readable=True,
    creatable=False, updatable=True, deletable=False, fields=(DEPARTMENT,),
)
CERTIFICATES = ProfileResource(
    key="certificate_records", label="Chứng chỉ",
    section_key="education_training", resource_type="collection", readable=True,
    creatable=True, updatable=True, deletable=True, fields=(CERTIFICATE,),
    record_label_field="certificate_name", deletion_mode="unlink",
)
SECTIONS = (
    ProfileSection(key="basic_profile", label="Hồ sơ cơ bản",
                   resource_keys=(CONTACT.key, EMPLOYMENT.key)),
    ProfileSection(key="education_training", label="Giáo dục",
                   resource_keys=(CERTIFICATES.key,)),
)
RESOURCES = (CONTACT, EMPLOYMENT, CERTIFICATES)


def certificate(record_id: int, issue_date: str) -> ProfileRecord:
    return ProfileRecord(
        record_id=record_id, label=f"TOEIC · {issue_date}",
        description="Loại: Ngoại ngữ",
        snapshot={"certificate_name": "TOEIC", "issue_date": issue_date},
        version=f"version-{record_id}", can_update=True, can_delete=True,
    )


class FakeSchema:
    def __init__(self, *, records=(), execution_error: str | None = None) -> None:
        self.records = tuple(records)
        self.execution_error = execution_error
        self.executions: list[dict[str, Any]] = []
        self.direct_executions: list[dict[str, Any]] = []

    async def get_sections(self, operation, **kwargs):
        return SECTIONS

    async def get_resources(self, section_key, operation, **kwargs):
        return tuple(item for item in RESOURCES if item.section_key == section_key
                     and (operation is None or item.allows(operation)))

    async def get_resource(self, key, **kwargs):
        return next(item for item in RESOURCES if item.key == key)

    async def get_fields(self, key, operation, **kwargs):
        resource = await self.get_resource(key)
        return tuple(field for field in resource.fields if field.allows(operation))

    async def list_records(self, key, **kwargs):
        return self.records

    async def get_record(self, key, record_id, **kwargs):
        item = next(
            (record for record in self.records if record.record_id == record_id),
            None,
        )
        if item is None:
            raise ProfileSchemaError("PROFILE_RECORD_NOT_FOUND", "not found")
        return item

    async def get_current_snapshot(self, key, **kwargs):
        return ProfileSnapshot(
            resource_key=key,
            snapshot={"mobile_phone": "0936261889", "work_email": "old@vnpt.vn"},
            version="phone-version-1",
        )

    async def execute_change_request(self, payload, **kwargs):
        self.executions.append(dict(payload))
        if self.execution_error:
            raise ProfileSchemaError(self.execution_error, "execution failed")
        return ProfileExecutionResult(
            resource_key=payload["resource_key"], operation=payload["operation"],
            write_mode="approval_request", request_id=88, state="wait",
        )

    async def execute_direct(self, payload, **kwargs):
        self.direct_executions.append(dict(payload))
        return {"ok": True}


class FakePending:
    def __init__(self, persisted=None) -> None:
        self.created: list[dict[str, Any]] = []
        self.persisted = persisted
        self.finished: list[dict[str, Any]] = []

    async def create(self, **values):
        self.created.append(values)
        return SimpleNamespace(
            action_id="act-profile-1", expires_at=datetime.now(timezone.utc)
        )

    async def load_owned(self, *args, **kwargs):
        return self.persisted

    async def finish(self, *args, **kwargs):
        self.finished.append(kwargs)


class FakeConversations:
    async def load_owned(self, *args, **kwargs):
        return SimpleNamespace()

    async def update(self, *args, **kwargs):
        return None


def classified(operation: Operation, intent: Intent = Intent.PROFILE_CONTACT):
    return QueryClassification(
        route=QueryRoute.TASK, domain=Domain.PROFILE, intent=intent,
        operation=operation, scope=SubjectScope.SELF, confidence=0.99,
        reason_code="TEST",
    )


async def prepare(operation, resource, *, fields=(), changes=None, record_id=None,
                  reference=None, schema=None):
    schema = schema or FakeSchema()
    pending = FakePending()
    context = SimpleNamespace(
        profile_schema_client=schema,
        pending_action_service=pending,
        conversation_service=FakeConversations(),
    )
    workflow = {
        "profile_target_resolved": True,
        "profile_section_key": resource.section_key,
        "profile_resource_key": resource.key,
        "profile_field_keys": list(fields),
        "profile_changes": changes or {},
        "profile_record_id": record_id,
        "profile_record_reference": reference,
    }
    state = {
        "conversation_id": "conv-1", "request_id": "req-1",
        "user_message": "profile write", "trusted_context": {"odoo_user_id": 7},
        "classification": classified(operation).model_dump(mode="json"),
        "workflow_data": workflow, "collected_arguments": {}, "entity_memory": {},
    }
    result = await resolve_profile_write_node(state, SimpleNamespace(context=context))
    return result, pending, schema


@pytest.mark.asyncio
async def test_1_phone_update_creates_pending_without_writing() -> None:
    result, pending, schema = await prepare(
        Operation.UPDATE, CONTACT, fields=("mobile_phone",),
        changes={"mobile_phone": "0987654321"},
    )
    assert len(pending.created) == 1
    assert schema.executions == []
    assert result["response_data"]["message_type"] == "confirmation"
    assert (
        pending.created[0]["validated_arguments"]["expected_version"]
        == "phone-version-1"
    )


@pytest.mark.asyncio
async def test_2_confirm_update_sends_only_selected_field() -> None:
    schema = FakeSchema()
    action = SimpleNamespace(
        action_id="act-1", tool_name="profile_crud_workflow", tool_version="1.0",
        idempotency_key="idem-1", validated_arguments={
            "intent": "profile_contact", "operation": "update",
            "resource_key": "contact_information",
            "changes": {"mobile_phone": "0987654321"},
            "current_snapshot": {
                "mobile_phone": "0936261889",
                "work_email": "old@vnpt.vn",
            },
            "expected_version": "phone-version-1", "write_mode": "approval_request",
        },
    )
    pending = FakePending(action)
    context = SimpleNamespace(
        pending_action_service=pending, profile_schema_client=schema,
        conversation_service=FakeConversations(),
    )
    state = {
        "pending_action": {"action_id": "act-1"}, "conversation_id": "conv-1",
        "request_id": "req-1", "trusted_context": {"odoo_user_id": 7},
    }
    await execute_write_tool_node(state, SimpleNamespace(context=context))
    assert schema.executions[0]["changes"] == {"mobile_phone": "0987654321"}
    assert "work_email" not in schema.executions[0]["changes"]


@pytest.mark.asyncio
async def test_3_duplicate_toeic_requires_record_select() -> None:
    result, pending, _ = await prepare(
        Operation.UPDATE, CERTIFICATES, fields=("certificate_name",),
        changes={"certificate_name": "TOEIC 900"}, reference="TOEIC",
        schema=FakeSchema(
            records=(
                certificate(10, "2026-07-17"),
                certificate(11, "2025-05-01"),
            )
        ),
    )
    clarification = result["response_data"]["clarification"]
    assert clarification["input_type"] == "record_select"
    assert [option["value"] for option in clarification["options"]] == ["10", "11"]
    assert pending.created == []


@pytest.mark.asyncio
async def test_4_delete_requires_confirmation_and_replay_is_blocked() -> None:
    result, pending, schema = await prepare(
        Operation.DELETE, CERTIFICATES, reference="TOEIC",
        schema=FakeSchema(records=(certificate(10, "2026-07-17"),)),
    )
    assert result["response_data"]["confirmation"]["action"] == "delete"
    assert schema.executions == [] and len(pending.created) == 1
    with pytest.raises(PendingActionError) as error:
        PendingActionService._raise_terminal_status(
            PendingActionStatus.EXECUTED.value, "profile_crud_workflow"
        )
    assert error.value.code == "PENDING_ACTION_ALREADY_EXECUTED"


@pytest.mark.asyncio
async def test_5_forbidden_field_does_not_create_pending() -> None:
    result, pending, _ = await prepare(
        Operation.UPDATE, EMPLOYMENT, fields=("department",),
        changes={"department": "9"},
    )
    assert result["response_data"]["error_code"] == "PROFILE_OPERATION_FORBIDDEN"
    assert pending.created == []


@pytest.mark.asyncio
async def test_6_approval_request_never_uses_direct_write() -> None:
    schema = FakeSchema()
    action = SimpleNamespace(
        action_id="act-approval", tool_name="profile_crud_workflow", tool_version="1.0",
        idempotency_key="idem-approval", validated_arguments={
            "intent": "profile_contact", "operation": "update",
            "resource_key": "contact_information", "changes": {"mobile_phone": "0987"},
            "expected_version": "v1", "write_mode": "approval_request",
        },
    )
    context = SimpleNamespace(
        pending_action_service=FakePending(action), profile_schema_client=schema,
        conversation_service=FakeConversations(),
    )
    result = await execute_write_tool_node(
        {"pending_action": {"action_id": action.action_id}, "conversation_id": "conv-1",
         "request_id": "req-1", "trusted_context": {"odoo_user_id": 7}},
        SimpleNamespace(context=context),
    )
    assert len(schema.executions) == 1 and schema.direct_executions == []
    assert "chờ xử lý" in result["response_text"]


@pytest.mark.asyncio
async def test_7_changed_record_returns_typed_concurrency_error() -> None:
    schema = FakeSchema(execution_error="PROFILE_RECORD_CHANGED")
    action = SimpleNamespace(
        action_id="act-stale", tool_name="profile_crud_workflow", tool_version="1.0",
        idempotency_key="idem-stale", validated_arguments={
            "intent": "profile_contact", "operation": "update",
            "resource_key": "contact_information", "changes": {"mobile_phone": "0987"},
            "expected_version": "stale", "write_mode": "approval_request",
        },
    )
    pending = FakePending(action)
    result = await execute_write_tool_node(
        {"pending_action": {"action_id": action.action_id}, "conversation_id": "conv-1",
         "request_id": "req-1", "trusted_context": {"odoo_user_id": 7}},
        SimpleNamespace(context=SimpleNamespace(
            pending_action_service=pending, profile_schema_client=schema,
            conversation_service=FakeConversations(),
        )),
    )
    assert result["response_data"]["error_code"] == "PROFILE_RECORD_CHANGED"
    assert pending.finished[0]["success"] is False


@pytest.mark.asyncio
async def test_8_foreign_record_id_is_not_found() -> None:
    result, pending, _ = await prepare(
        Operation.UPDATE, CERTIFICATES, fields=("certificate_name",),
        changes={"certificate_name": "Khác"}, record_id=999,
        schema=FakeSchema(records=(certificate(10, "2026-07-17"),)),
    )
    assert result["response_data"]["error_code"] == "PROFILE_RECORD_NOT_FOUND"
    assert pending.created == []
