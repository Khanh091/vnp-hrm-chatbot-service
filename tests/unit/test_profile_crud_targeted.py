from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.odoo.profile_schema import (
    ProfileField,
    ProfileOption,
    ProfileResource,
    ProfileSection,
    ProfileWriteMode,
)
from app.orchestration.nodes.resolve_profile_write import resolve_profile_write_node
from app.routing.capabilities import CapabilityResolver
from app.routing.profile_target_resolver import (
    ProfileTargetOutsideAllowlistError,
    ProfileTargetResolution,
    ProfileTargetResolver,
)
from app.routing.query_classifier import QueryClassifier
from app.routing.query_normalizer import QueryNormalizer
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import (
    Intent,
    Operation,
    QueryRoute,
    SubjectScope,
    SubjectType,
)


def field(
    key: str,
    label: str,
    field_type: str = "text",
    *,
    create: bool = False,
    update: bool = True,
    delete: bool = False,
    required: bool = False,
    mode: ProfileWriteMode = ProfileWriteMode.APPROVAL_REQUEST,
    description: str | None = None,
) -> ProfileField:
    return ProfileField(
        key=key,
        label=label,
        field_type=field_type,
        readable=True,
        creatable=create,
        updatable=update,
        deletable=delete,
        required_on_create=required,
        write_mode=mode,
        description=description,
    )


PHONE = field("mobile_phone", "Số điện thoại", "phone")
DEPARTMENT = field(
    "department",
    "Phòng ban",
    "many2one",
    update=False,
    mode=ProfileWriteMode.FORBIDDEN,
    description="Vui lòng liên hệ bộ phận nhân sự.",
)
CERTIFICATE_NAME = field(
    "certificate_name", "Tên chứng chỉ", create=True, required=True
)
GENDER = field("gender", "Giới tính", "selection")


def resource(
    key: str,
    label: str,
    section: str,
    fields: tuple[ProfileField, ...],
    *,
    collection: bool = False,
    create: bool = False,
    delete: bool = False,
) -> ProfileResource:
    return ProfileResource(
        key=key,
        label=label,
        section_key=section,
        resource_type="collection" if collection else "singleton",
        readable=True,
        creatable=create,
        updatable=True,
        deletable=delete,
        fields=fields,
    )


CONTACT = resource(
    "contact_information", "Thông tin liên hệ", "basic_profile", (PHONE,)
)
EMPLOYMENT = resource(
    "employment_information",
    "Thông tin việc làm",
    "basic_profile",
    (DEPARTMENT, PHONE),
)
BASIC = resource("basic_information", "Thông tin chung", "basic_profile", (GENDER,))
CERTIFICATES = resource(
    "certificate_records",
    "Chứng chỉ",
    "qualifications",
    (CERTIFICATE_NAME,),
    collection=True,
    create=True,
    delete=True,
)
RESOURCES = (CONTACT, EMPLOYMENT, BASIC, CERTIFICATES)
SECTIONS = (
    ProfileSection(
        key="basic_profile",
        label="Thông tin cơ bản",
        resource_keys=(CONTACT.key, EMPLOYMENT.key, BASIC.key),
    ),
    ProfileSection(
        key="qualifications",
        label="Trình độ",
        resource_keys=(CERTIFICATES.key,),
    ),
)


class QueueLlm:
    def __init__(self, *results: Any) -> None:
        self.results = list(results)

    async def complete_structured(self, **_: Any) -> Any:
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeSchema:
    def __init__(self) -> None:
        self.options_calls: list[tuple[str, str]] = []

    async def get_sections(
        self, operation: Operation | None, **_: Any
    ) -> tuple[Any, ...]:
        return SECTIONS

    async def get_resources(
        self, section_key: str, operation: Operation | None, **_: Any
    ) -> tuple[ProfileResource, ...]:
        return tuple(
            item
            for item in RESOURCES
            if item.section_key == section_key
            and (operation is None or item.allows(operation))
        )

    async def get_resource(self, resource_key: str, **_: Any) -> ProfileResource:
        return next(item for item in RESOURCES if item.key == resource_key)

    async def get_fields(
        self, resource_key: str, operation: Operation | None, **_: Any
    ) -> tuple[ProfileField, ...]:
        item = await self.get_resource(resource_key)
        return tuple(
            value
            for value in item.fields
            if operation is None or value.allows(operation)
        )

    async def get_field_options(
        self, resource_key: str, field_key: str, **_: Any
    ) -> tuple[ProfileOption, ...]:
        self.options_calls.append((resource_key, field_key))
        return (
            ProfileOption(value="nam", label="Nam"),
            ProfileOption(value="nu", label="Nữ"),
        )


class FakeConversations:
    async def load_owned(self, *_: Any) -> SimpleNamespace:
        return SimpleNamespace()

    async def update(self, *_: Any, **__: Any) -> None:
        return None


def classification(intent: Intent, operation: Operation) -> QueryClassification:
    return QueryClassification(
        route=QueryRoute.TASK,
        domain=Domain.PROFILE,
        intent=intent,
        operation=operation,
        scope=SubjectScope.SELF,
        confidence=0.95,
        reason_code="TEST",
    )


def resolution(
    section: str | None,
    resource_key: str | None = None,
    fields: list[str] | None = None,
    reference: str | None = None,
) -> ProfileTargetResolution:
    return ProfileTargetResolution(
        section_key=section,
        resource_key=resource_key,
        field_keys=fields or [],
        record_reference_text=reference,
        confidence=0.95,
        needs_clarification=resource_key is None,
        reason_code="TARGET_RESOLVED",
    )


async def run_node(
    query: str,
    classified: QueryClassification,
    *targets: ProfileTargetResolution,
    schema: FakeSchema | None = None,
) -> dict[str, Any]:
    context = SimpleNamespace(
        profile_schema_client=schema or FakeSchema(),
        profile_target_resolver=ProfileTargetResolver(QueueLlm(*targets)),
        conversation_service=FakeConversations(),
    )
    state = {
        "conversation_id": "conv-1",
        "request_id": "req-1",
        "user_message": query,
        "trusted_context": {"odoo_user_id": 7},
        "classification": classified.model_dump(mode="json"),
        "workflow_data": {},
        "collected_arguments": {},
        "entity_memory": {},
    }
    return await resolve_profile_write_node(state, SimpleNamespace(context=context))


@pytest.mark.asyncio
async def test_1_phone_update_classifies_and_resolves_field() -> None:
    result = await QueryClassifier(
        QueueLlm(classification(Intent.PROFILE_CONTACT, Operation.READ))
    ).classify(QueryNormalizer().normalize("đổi số điện thoại"))
    assert (result.intent, result.operation, result.route, result.domain) == (
        Intent.PROFILE_CONTACT,
        Operation.UPDATE,
        QueryRoute.TASK,
        Domain.PROFILE,
    )
    capability = CapabilityResolver().resolve(
        intent=result.intent,
        operation=result.operation,
        subject_type=SubjectType.SELF,
    )
    assert [item.name for item in capability] == ["employee_contact_update"]
    target = resolution("basic_profile", "contact_information", ["mobile_phone"])
    node = await run_node("đổi số điện thoại", result, target, target)
    assert node["response_data"]["clarification"]["slot_name"] == "mobile_phone"


@pytest.mark.asyncio
async def test_2_broad_basic_section_asks_for_resource() -> None:
    node = await run_node(
        "sửa thông tin cơ bản",
        classification(Intent.PROFILE_SUMMARY, Operation.UPDATE),
        resolution("basic_profile"),
    )
    contract = node["response_data"]["clarification"]
    assert contract["input_type"] == "resource_select"
    assert contract["slot_name"] == "profile_resource_key"


@pytest.mark.asyncio
async def test_3_department_update_is_forbidden_by_registry() -> None:
    target = resolution("basic_profile", "employment_information", ["department"])
    node = await run_node(
        "đổi phòng ban",
        classification(Intent.PROFILE_DEPARTMENT, Operation.UPDATE),
        target,
        target,
    )
    assert node["response_data"]["error_code"] == "PROFILE_OPERATION_FORBIDDEN"
    assert "không thể thay đổi" in node["response_text"]


@pytest.mark.asyncio
async def test_4_create_certificate_builds_required_slots() -> None:
    target = resolution("qualifications", "certificate_records")
    node = await run_node(
        "thêm chứng chỉ",
        classification(Intent.PROFILE_CERTIFICATES, Operation.CREATE),
        target,
        target,
    )
    assert node["missing_profile_slots"] == ["certificate_name"]
    assert node["response_data"]["clarification"]["slot_name"] == "certificate_name"


@pytest.mark.asyncio
async def test_5_delete_certificate_is_not_cancel() -> None:
    result = await QueryClassifier(
        QueueLlm(classification(Intent.PROFILE_CERTIFICATES, Operation.CANCEL))
    ).classify(QueryNormalizer().normalize("xóa chứng chỉ TOEIC"))
    assert result.intent is Intent.PROFILE_CERTIFICATES
    assert result.operation is Operation.DELETE
    target = resolution("qualifications", "certificate_records", reference="TOEIC")
    node = await run_node("xóa chứng chỉ TOEIC", result, target, target)
    clarification = node["response_data"]["clarification"]
    assert clarification["input_type"] == "record_select"
    assert node["profile_record_reference"] == "TOEIC"


@pytest.mark.asyncio
async def test_6_resolver_rejects_resource_outside_allowlist() -> None:
    invalid = resolution("qualifications", "hr_employee_certificate")
    with pytest.raises(ProfileTargetOutsideAllowlistError):
        await ProfileTargetResolver(QueueLlm(invalid)).resolve(
            original_query="xóa chứng chỉ",
            intent=Intent.PROFILE_CERTIFICATES,
            operation=Operation.DELETE,
            sections=SECTIONS,
            resources=(CERTIFICATES,),
        )


@pytest.mark.asyncio
async def test_7_selection_options_come_from_schema_endpoint() -> None:
    schema = FakeSchema()
    target = resolution("basic_profile", "basic_information", ["gender"])
    node = await run_node(
        "sửa giới tính",
        classification(Intent.PROFILE_BASIC, Operation.UPDATE),
        target,
        target,
        schema=schema,
    )
    clarification = node["response_data"]["clarification"]
    assert schema.options_calls == [("basic_information", "gender")]
    assert clarification["input_type"] == "single_select"
    assert clarification["options"][0]["value"] == "nam"


@pytest.mark.asyncio
async def test_8_leave_cancel_remains_cancel() -> None:
    llm_result = QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=Domain.PROFILE,
        intent=Intent.LEAVE_CANCEL,
        operation=Operation.DELETE,
        scope=SubjectScope.SELF,
        confidence=0.9,
        reason_code="TEST",
    )
    result = await QueryClassifier(QueueLlm(llm_result)).classify(
        QueryNormalizer().normalize("hủy đơn nghỉ")
    )
    assert (result.intent, result.operation, result.route, result.domain) == (
        Intent.LEAVE_CANCEL,
        Operation.CANCEL,
        QueryRoute.TASK,
        Domain.LEAVE,
    )
