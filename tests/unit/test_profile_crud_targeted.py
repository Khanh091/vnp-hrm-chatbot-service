from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.odoo.profile_schema import (
    ProfileField,
    ProfileResource,
    ProfileSection,
    ProfileSnapshot,
    ProfileWriteMode,
)
from app.orchestration.nodes.resolve_profile_write import resolve_profile_write_node
from app.routing.profile_target_resolver import (
    ProfileTargetResolution,
    ProfileTargetResolver,
)
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import Intent, Operation, QueryRoute, SubjectScope


def field(key: str, label: str, *, writable: bool = True,
          required: bool = False, derived: str | None = None,
          reason: str | None = None, field_type: str = "text") -> ProfileField:
    return ProfileField(
        key=key, label=label, field_type=field_type,
        readable=True, creatable=writable, updatable=writable,
        deletable=False, required_on_create=required,
        write_mode=(ProfileWriteMode.APPROVAL_REQUEST if writable
                    else ProfileWriteMode.FORBIDDEN),
        section_key="basic_profile", derived_from_resource=derived,
        restriction_reason=reason,
    )


FULL_NAME = field("full_name", "Họ và tên")
GENDER = field("gender", "Giới tính", field_type="selection")
ALTERNATE_NAME = field("alternate_name", "Tên gọi khác")
BIRTH_DATE = field("birth_date", "Ngày sinh", field_type="date")
MOBILE = field("mobile_phone", "Di động", field_type="phone")
EMAIL = field("work_email", "Email", field_type="email")
EMPLOYEE_TYPE = field("employee_type", "Loại nhân sự", field_type="many2one")
MANAGER = field("manager", "Người quản lý", field_type="many2one")
MAIN_JOB = field("main_job", "Công việc chính được giao")
DEPARTMENT = field(
    "department", "Đơn vị / Phòng ban", writable=False,
    reason="removed_by_edition_write", field_type="many2one",
)
HIGHEST_EDUCATION = field(
    "highest_qualification", "Trình độ chuyên môn cao nhất",
    writable=False, derived="education_records",
    reason="derived_from_education_records", field_type="many2one",
)
CERTIFICATE_NAME = field(
    "certificate_name", "Tên chứng chỉ", required=True,
)
CERTIFICATE_TYPE = field(
    "certificate_type", "Loại chứng chỉ", required=True,
    field_type="many2one",
)

CONTACT = ProfileResource(
    key="contact_information", label="Thông tin liên hệ",
    section_key="basic_profile", resource_type="singleton", readable=True,
    creatable=False, updatable=True, deletable=False,
    fields=(MOBILE, EMAIL),
)
EMPLOYMENT = ProfileResource(
    key="employment_information", label="Thông tin công việc",
    section_key="basic_profile", resource_type="singleton", readable=True,
    creatable=False, updatable=True, deletable=False,
    fields=(DEPARTMENT, EMPLOYEE_TYPE, MANAGER, MAIN_JOB),
)
EDUCATION_SUMMARY = ProfileResource(
    key="education_summary", label="Thông tin trình độ đào tạo",
    section_key="education_training", resource_type="singleton", readable=True,
    creatable=False, updatable=True, deletable=False,
    fields=(HIGHEST_EDUCATION,),
)
EDUCATION_RECORDS = ProfileResource(
    key="education_records", label="Quá trình đào tạo",
    section_key="education_training", resource_type="collection", readable=True,
    creatable=True, updatable=True, deletable=True,
    fields=(field("education_name", "Trình độ", required=True),),
)
CERTIFICATES = ProfileResource(
    key="certificate_records", label="Văn bằng, chứng chỉ",
    section_key="education_training", resource_type="collection", readable=True,
    creatable=True, updatable=True, deletable=True,
    fields=(CERTIFICATE_NAME, CERTIFICATE_TYPE),
)
BASIC = ProfileSection(
    key="basic_profile", label="I. Thông tin cơ bản",
    direct_fields=(FULL_NAME, GENDER, ALTERNATE_NAME, BIRTH_DATE),
    fields=(FULL_NAME, GENDER, ALTERNATE_NAME, BIRTH_DATE),
    resource_keys=(CONTACT.key, EMPLOYMENT.key),
)
EDUCATION = ProfileSection(
    key="education_training", label="Giáo dục và đào tạo",
    resource_keys=(EDUCATION_SUMMARY.key, EDUCATION_RECORDS.key,
                   CERTIFICATES.key),
)
SECTIONS = (BASIC, EDUCATION)
RESOURCES = (
    CONTACT, EMPLOYMENT, EDUCATION_SUMMARY, EDUCATION_RECORDS, CERTIFICATES,
)


class FakeSchema:
    async def get_sections(self, operation, **kwargs):
        return SECTIONS

    async def get_resources(self, section_key, operation, **kwargs):
        resources = tuple(item for item in RESOURCES
                          if item.section_key == section_key)
        if operation is None:
            return resources
        return tuple(item for item in resources if item.allows(operation))

    async def get_resource(self, key, **kwargs):
        return next(item for item in RESOURCES if item.key == key)

    async def get_fields(self, key, operation, **kwargs):
        resource = await self.get_resource(key)
        return tuple(item for item in resource.fields if item.allows(operation))

    async def get_section_snapshot(self, key, **kwargs):
        return ProfileSnapshot(
            section_key=key,
            snapshot={"alternate_name": "Định Lò"},
            version="section-v1",
        )

    async def get_current_snapshot(self, key, **kwargs):
        return ProfileSnapshot(
            resource_key=key, snapshot={"mobile_phone": "0936261889"},
            version="resource-v1",
        )

    async def get_field_options(self, *args, **kwargs):
        return ()

    async def get_section_field_options(self, *args, **kwargs):
        return ()

    async def list_records(self, *args, **kwargs):
        return ()


class FakePending:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def create(self, **values):
        self.created.append(values)
        return SimpleNamespace(action_id="action-1", expires_at=SimpleNamespace(
            isoformat=lambda: "2026-08-04T12:00:00+07:00"
        ))


class FakeConversations:
    async def load_owned(self, *args, **kwargs):
        return SimpleNamespace()

    async def update(self, *args, **kwargs):
        return None


def classification(operation: Operation) -> QueryClassification:
    return QueryClassification(
        route=QueryRoute.TASK, domain=Domain.PROFILE,
        intent=Intent.PROFILE_CONTACT, operation=operation,
        scope=SubjectScope.SELF, confidence=0.99, reason_code="TEST",
    )


async def run_target(*, section: str, resource: str | None,
                     fields: tuple[str, ...] = (), operation=Operation.UPDATE,
                     changes: dict[str, Any] | None = None,
                     collected: dict[str, Any] | None = None,
                     previous_workflow: dict[str, Any] | None = None):
    schema = FakeSchema()
    pending = FakePending()
    context = SimpleNamespace(
        profile_schema_client=schema, pending_action_service=pending,
        conversation_service=FakeConversations(),
    )
    workflow = dict(previous_workflow or {})
    workflow.update({
        "profile_target_resolved": True,
        "profile_section_key": section,
        "profile_resource_key": resource,
    })
    if not previous_workflow:
        workflow.update({
            "profile_field_keys": list(fields),
            "profile_changes": changes or {},
        })
    state = {
        "conversation_id": "conv-1", "request_id": "req-1",
        "user_message": "profile write",
        "trusted_context": {"odoo_user_id": 7},
        "classification": classification(operation).model_dump(mode="json"),
        "workflow_data": workflow,
        "collected_arguments": collected or {}, "entity_memory": {},
    }
    result = await resolve_profile_write_node(
        state, SimpleNamespace(context=context)
    )
    return result, pending


@pytest.mark.asyncio
async def test_1_alternate_name_is_direct_field_and_asks_value_immediately():
    resolution = ProfileTargetResolution(
        section_key="basic_profile", resource_key=None,
        field_keys=["alternate_name"], record_reference_text=None,
        confidence=0.99, needs_clarification=False, reason_code="DIRECT_FIELD",
    )
    ProfileTargetResolver._validate_allowlist(resolution, SECTIONS, RESOURCES)
    result, pending = await run_target(
        section=BASIC.key, resource=None, fields=(ALTERNATE_NAME.key,),
    )
    clarification = result["response_data"]["clarification"]
    assert clarification["slot_name"] == "alternate_name"
    assert result["profile_resource_key"] is None
    assert pending.created == []


@pytest.mark.asyncio
async def test_2_basic_section_lists_direct_fields_and_resources():
    result, _ = await run_target(section=BASIC.key, resource=None)
    options = result["response_data"]["clarification"]["options"]
    values = {item["value"] for item in options}
    assert {"full_name", "gender", "alternate_name", "birth_date"} <= values
    assert {"contact_information", "employment_information"} <= values


@pytest.mark.asyncio
async def test_3_contact_resource_lists_only_contact_fields():
    result, _ = await run_target(section=BASIC.key, resource=CONTACT.key)
    options = result["response_data"]["clarification"]["options"]
    assert {item["value"] for item in options} == {"mobile_phone", "work_email"}


@pytest.mark.asyncio
async def test_4_add_mobile_is_normalized_to_singleton_update():
    result, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key, fields=(MOBILE.key,),
        operation=Operation.CREATE,
    )
    assert result["response_data"]["clarification"]["slot_name"] == "mobile_phone"
    assert result["workflow_data"]["operation"] == "update"


@pytest.mark.asyncio
async def test_5_employment_exposes_all_edition_writable_fields():
    result, _ = await run_target(section=BASIC.key, resource=EMPLOYMENT.key)
    values = {
        item["value"]
        for item in result["response_data"]["clarification"]["options"]
    }
    assert values == {"employee_type", "manager", "main_job"}
    assert "department" not in values


@pytest.mark.asyncio
async def test_6_derived_education_field_redirects_to_collection():
    result, pending = await run_target(
        section=EDUCATION.key, resource=EDUCATION_SUMMARY.key,
        fields=(HIGHEST_EDUCATION.key,),
    )
    clarification = result["response_data"]["clarification"]
    assert clarification["slot_name"] == "derived_resource_action"
    assert {item["value"] for item in clarification["options"]} == {
        "create", "update",
    }
    assert result["workflow_data"]["derived_from_resource"] == "education_records"
    assert pending.created == []


@pytest.mark.asyncio
async def test_7_certificate_text_answer_advances_to_next_required_slot():
    first, _ = await run_target(
        section=EDUCATION.key, resource=CERTIFICATES.key,
        operation=Operation.CREATE,
    )
    assert first["response_data"]["clarification"]["slot_name"] == "certificate_name"
    second, _ = await run_target(
        section=EDUCATION.key, resource=CERTIFICATES.key,
        operation=Operation.CREATE, collected={"certificate_name": "IELTS"},
        previous_workflow=first["workflow_data"],
    )
    assert second["response_data"]["clarification"]["slot_name"] == "certificate_type"
    assert second["workflow_data"]["profile_changes"]["certificate_name"] == "IELTS"


@pytest.mark.asyncio
async def test_8_forbidden_field_has_explicit_restriction_reason():
    result, pending = await run_target(
        section=BASIC.key, resource=EMPLOYMENT.key,
        fields=(DEPARTMENT.key,), changes={DEPARTMENT.key: "9"},
    )
    assert DEPARTMENT.restriction_reason == "removed_by_edition_write"
    assert result["response_data"]["error_code"] == "PROFILE_OPERATION_FORBIDDEN"
    assert "removed_by_edition_write" in result["response_text"]
    assert pending.created == []
