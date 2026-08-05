from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.odoo.profile_schema import (
    ProfileField,
    ProfileResource,
    ProfileSchemaError,
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
    def __init__(self, save_error: ProfileSchemaError | None = None) -> None:
        self.saved_drafts: list[dict[str, Any]] = []
        self.save_error = save_error
        self.saved_values: dict[str, Any] = {}

    async def get_sections(self, operation, **kwargs):
        return SECTIONS

    async def get_resources(self, section_key, operation, **kwargs):
        resources = tuple(item for item in RESOURCES
                          if item.section_key == section_key)
        if operation is None:
            return resources
        return tuple(item for item in resources if item.allows(operation))

    async def get_section(self, key, operation=None, **kwargs):
        section = next(item for item in SECTIONS if item.key == key)
        if operation is None:
            return section
        return section.model_copy(update={
            "direct_fields": tuple(
                item for item in section.direct_fields
                if item.allows(operation)
            )
        })

    async def get_resource(self, key, **kwargs):
        return next(item for item in RESOURCES if item.key == key)

    async def get_fields(self, key, operation, **kwargs):
        resource = await self.get_resource(key)
        return tuple(item for item in resource.fields if item.allows(operation))

    async def get_section_snapshot(self, key, **kwargs):
        return ProfileSnapshot(
            section_key=key,
            snapshot={"alternate_name": "Định Lò", **self.saved_values},
            version="section-v1",
        )

    async def get_current_snapshot(self, key, **kwargs):
        return ProfileSnapshot(
            resource_key=key,
            snapshot={"mobile_phone": "0936261889", **self.saved_values},
            version="resource-v1",
        )

    async def get_field_options(self, *args, **kwargs):
        return ()

    async def get_section_field_options(self, *args, **kwargs):
        return ()

    async def list_records(self, *args, **kwargs):
        return ()

    async def save_draft(self, payload, **kwargs):
        self.saved_drafts.append(payload)
        if self.save_error is not None:
            raise self.save_error
        self.saved_values.update(payload.get("changes", {}))
        return SimpleNamespace(
            message=("Các thay đổi đã được lưu vào hồ sơ tự khai nhưng "
                     "chưa gửi phê duyệt."),
            draft_saved=True,
            record_id=payload.get("record_id"),
        )


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


class FakeEntityMemory:
    def capture(self, *, memory, **kwargs):
        return memory


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
                     previous_workflow: dict[str, Any] | None = None,
                     answer_field: str | None = None,
                     answer_type: str = "option_select",
                     answer_label: str | None = None,
                     schema_error: ProfileSchemaError | None = None):
    schema = FakeSchema(schema_error)
    pending = FakePending()
    context = SimpleNamespace(
        profile_schema_client=schema, pending_action_service=pending,
        conversation_service=FakeConversations(),
        entity_memory_service=FakeEntityMemory(),
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
    if answer_field is not None:
        state["clarification"] = {
            "answer_type": answer_type,
            "field": answer_field,
        }
        if answer_label is not None:
            state["clarification"]["label"] = answer_label
    result = await resolve_profile_write_node(
        state, SimpleNamespace(context=context)
    )
    return result, pending, schema


@pytest.mark.asyncio
async def test_1_alternate_name_is_direct_field_and_asks_value_immediately():
    resolution = ProfileTargetResolution(
        section_key="basic_profile", resource_key=None,
        field_keys=["alternate_name"], record_reference_text=None,
        confidence=0.99, needs_clarification=False, reason_code="DIRECT_FIELD",
    )
    ProfileTargetResolver._validate_allowlist(resolution, SECTIONS, RESOURCES)
    result, pending, _ = await run_target(
        section=BASIC.key, resource=None, fields=(ALTERNATE_NAME.key,),
    )
    clarification = result["response_data"]["clarification"]
    assert clarification["slot_name"] == "alternate_name"
    assert result["profile_resource_key"] is None
    assert pending.created == []


@pytest.mark.asyncio
async def test_2_basic_section_lists_direct_fields_and_resources():
    result, _, _ = await run_target(section=BASIC.key, resource=None)
    options = result["response_data"]["clarification"]["options"]
    values = {item["value"] for item in options}
    assert {"full_name", "gender", "alternate_name", "birth_date"} <= values
    assert {"contact_information", "employment_information"} <= values


@pytest.mark.asyncio
async def test_3_contact_resource_lists_only_contact_fields():
    result, _, _ = await run_target(section=BASIC.key, resource=CONTACT.key)
    assert result["response_data"]["clarification"]["input_type"] == "resource_form"
    options = result["response_data"]["clarification"]["options"]
    assert {item["value"] for item in options} == {"finish", "cancel"}
    form = result["response_data"]["clarification"]
    assert {item["field_key"] for item in form["fields"]} == {
        "mobile_phone", "work_email"
    }
    assert form["session_id"].startswith("profile-")


@pytest.mark.asyncio
async def test_4_add_mobile_is_normalized_to_singleton_update():
    result, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key, fields=(MOBILE.key,),
        operation=Operation.CREATE,
    )
    assert result["response_data"]["clarification"]["slot_name"] == "mobile_phone"
    assert result["workflow_data"]["operation"] == "update"


@pytest.mark.asyncio
async def test_5_employment_exposes_all_edition_writable_fields():
    result, _, _ = await run_target(section=BASIC.key, resource=EMPLOYMENT.key)
    values = {
        item["value"]
        for item in result["response_data"]["clarification"]["options"]
    }
    assert values == {"finish", "cancel"}
    rows = result["response_data"]["clarification"]["fields"]
    assert {item["field_key"] for item in rows if not item["readonly"]} == {
        "employee_type", "manager", "main_job"
    }
    assert "department" not in values


@pytest.mark.asyncio
async def test_6_derived_education_field_redirects_to_collection():
    result, pending, _ = await run_target(
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
    first, _, _ = await run_target(
        section=EDUCATION.key, resource=CERTIFICATES.key,
        operation=Operation.CREATE,
    )
    form = first["response_data"]["clarification"]
    assert form["slot_name"] == "profile_edit_action"
    assert form["input_type"] == "record_form"
    assert {
        item["field_key"] for item in form["fields"] if item["required"]
    } == {"certificate_name", "certificate_type"}
    second, _, _ = await run_target(
        section=EDUCATION.key, resource=CERTIFICATES.key,
        operation=Operation.CREATE, collected={"certificate_name": "IELTS"},
        previous_workflow=first["workflow_data"],
    )
    assert second["response_data"]["clarification"]["slot_name"] == (
        "profile_edit_action"
    )
    assert second["workflow_data"]["profile_changes"]["certificate_name"] == "IELTS"


@pytest.mark.asyncio
async def test_8_forbidden_field_has_explicit_restriction_reason():
    result, pending, _ = await run_target(
        section=BASIC.key, resource=EMPLOYMENT.key,
        fields=(DEPARTMENT.key,), changes={DEPARTMENT.key: "9"},
    )
    assert DEPARTMENT.restriction_reason == "removed_by_edition_write"
    assert result["response_data"]["error_code"] == "PROFILE_OPERATION_FORBIDDEN"
    assert "removed_by_edition_write" in result["response_text"]
    assert pending.created == []


@pytest.mark.asyncio
async def test_9_direct_update_stays_draft_until_submit():
    ask, pending, _ = await run_target(
        section=BASIC.key, resource=None, fields=(ALTERNATE_NAME.key,),
    )
    assert pending.created == []

    edited, pending, _ = await run_target(
        section=BASIC.key, resource=None,
        collected={ALTERNATE_NAME.key: "Tên mới"},
        previous_workflow=ask["workflow_data"],
    )
    assert edited["response_data"]["clarification"]["input_type"] == "edit_summary"
    assert pending.created == []

    reviewed, pending, _ = await run_target(
        section=BASIC.key, resource=None,
        collected={"profile_edit_action": "finish"},
        previous_workflow=edited["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert reviewed["response_data"]["clarification"]["input_type"] == (
        "edit_session_actions"
    )
    assert pending.created == []

    confirmed, pending, _ = await run_target(
        section=BASIC.key, resource=None,
        collected={"profile_edit_action": "submit"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert confirmed["response_data"]["message_type"] == "confirmation"
    assert len(pending.created) == 1


@pytest.mark.asyncio
async def test_10_save_draft_does_not_create_pending_action():
    ask, _, _ = await run_target(
        section=BASIC.key, resource=None, fields=(ALTERNATE_NAME.key,),
    )
    edited, _, _ = await run_target(
        section=BASIC.key, resource=None,
        collected={ALTERNATE_NAME.key: "Tên nháp"},
        previous_workflow=ask["workflow_data"],
    )
    reviewed, _, _ = await run_target(
        section=BASIC.key, resource=None,
        collected={"profile_edit_action": "finish"},
        previous_workflow=edited["workflow_data"],
        answer_field="profile_edit_action",
    )
    saved, pending, schema = await run_target(
        section=BASIC.key, resource=None,
        collected={"profile_edit_action": "save_draft"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert saved["response_data"]["draft_saved"] is True
    assert pending.created == []
    assert len(schema.saved_drafts) == 1
    assert schema.saved_drafts[0]["changes"] == {"alternate_name": "Tên nháp"}


@pytest.mark.asyncio
async def test_11_same_value_returns_form_without_pending_action():
    ask, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key, fields=(MOBILE.key,),
    )
    result, pending, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={MOBILE.key: "0936261889"},
        previous_workflow=ask["workflow_data"],
    )
    assert result["response_data"]["clarification"]["input_type"] == "resource_form"
    assert result["workflow_data"]["profile_changes"] == {}
    assert pending.created == []


@pytest.mark.asyncio
async def test_12_raw_text_is_rejected_for_selection_field():
    ask, _, _ = await run_target(
        section=BASIC.key, resource=None, fields=(GENDER.key,),
    )
    result, pending, _ = await run_target(
        section=BASIC.key, resource=None,
        collected={GENDER.key: "Nữ"},
        previous_workflow=ask["workflow_data"],
    )
    clarification = result["response_data"]["clarification"]
    assert clarification["input_type"] == "single_select"
    assert "chọn từ danh sách" in result["response_text"]
    assert result["workflow_data"]["profile_changes"] == {}
    assert pending.created == []


def test_13_duplicate_field_aliases_resolve_to_bounded_ambiguity():
    common_alias = "\u0111\u1ecba ch\u1ec9 chi ti\u1ebft"
    permanent = field("permanent_detail", "Chi ti\u1ebft h\u1ed9 kh\u1ea9u").model_copy(
        update={"aliases": (common_alias,)}
    )
    current = field("current_detail", "Chi ti\u1ebft n\u01a1i \u1edf").model_copy(
        update={"aliases": (common_alias,)}
    )
    address = ProfileResource(
        key="address_information",
        label="Th\u00f4ng tin \u0111\u1ecba ch\u1ec9",
        section_key=BASIC.key,
        resource_type="singleton",
        readable=True,
        creatable=False,
        updatable=True,
        deletable=False,
        fields=(permanent, current),
    )

    resolution = ProfileTargetResolver._resolve_exact_match(
        "th\u00eam \u0111\u1ecba ch\u1ec9 chi ti\u1ebft",
        Intent.PROFILE_ADDRESS,
        Operation.UPDATE,
        (BASIC,),
        (address,),
    )

    assert resolution is not None
    assert resolution.needs_clarification is True
    assert resolution.resource_key == address.key
    assert set(resolution.field_keys) == {permanent.key, current.key}


def test_14_collection_label_punctuation_does_not_downgrade_to_field():
    certificate_name = field(
        "certificate_name", "T\u00ean v\u0103n b\u1eb1ng/ch\u1ee9ng ch\u1ec9"
    ).model_copy(update={"aliases": ("ch\u1ee9ng ch\u1ec9", "v\u0103n b\u1eb1ng")})
    certificates = ProfileResource(
        key="certificate_records",
        label="V\u0103n b\u1eb1ng, ch\u1ee9ng ch\u1ec9",
        section_key=EDUCATION.key,
        resource_type="collection",
        readable=True,
        creatable=True,
        updatable=True,
        deletable=True,
        fields=(certificate_name,),
    )

    resolution = ProfileTargetResolver._resolve_exact_match(
        "th\u00eam m\u1ed9t v\u0103n b\u1eb1ng ch\u1ee9ng ch\u1ec9",
        Intent.PROFILE_CERTIFICATES,
        Operation.CREATE,
        (EDUCATION,),
        (certificates,),
    )

    assert resolution is not None
    assert resolution.resource_key == certificates.key
    assert resolution.field_keys == []
    assert resolution.reason_code == "EXACT_COLLECTION_MATCH"


def test_15_create_of_derived_summary_redirects_to_source_collection():
    derived = HIGHEST_EDUCATION.model_copy(
        update={"aliases": ("tr\u00ecnh \u0111\u1ed9 chuy\u00ean m\u00f4n",)}
    )
    summary = EDUCATION_SUMMARY.model_copy(update={"fields": (derived,)})

    resolution = ProfileTargetResolver._resolve_exact_match(
        "th\u00eam m\u1ed9t tr\u00ecnh \u0111\u1ed9 chuy\u00ean m\u00f4n",
        Intent.PROFILE_EDUCATION,
        Operation.CREATE,
        (EDUCATION,),
        (summary, EDUCATION_RECORDS),
    )

    assert resolution is not None
    assert resolution.resource_key == EDUCATION_RECORDS.key
    assert resolution.field_keys == []
    assert resolution.reason_code == "DERIVED_COLLECTION_CREATE"


def test_16_operation_prefix_does_not_remove_words_inside_target():
    course = field("course_name", "Kh\u00f3a \u0111\u00e0o t\u1ea1o")
    training = ProfileResource(
        key="training_records",
        label="\u0110\u00e0o t\u1ea1o, b\u1ed3i d\u01b0\u1ee1ng",
        section_key=EDUCATION.key,
        resource_type="collection",
        readable=True,
        creatable=True,
        updatable=True,
        deletable=True,
        fields=(course,),
    )

    query = (
        "th\u00eam m\u1ed9t qu\u00e1 tr\u00ecnh "
        "\u0111\u00e0o t\u1ea1o b\u1ed3i d\u01b0\u1ee1ng"
    )
    resolution = ProfileTargetResolver._resolve_exact_match(
        query,
        Intent.PROFILE_EDUCATION,
        Operation.CREATE,
        (EDUCATION,),
        (training,),
    )

    assert resolution is not None
    assert resolution.resource_key == training.key
    assert "dao tao" in ProfileTargetResolver._target_text(query)


@pytest.mark.asyncio
async def test_17_resource_finish_keeps_draft_changes_and_opens_review():
    form, _, _ = await run_target(section=BASIC.key, resource=CONTACT.key)
    ask_value, _, _ = await run_target(
        section=BASIC.key,
        resource=CONTACT.key,
        collected={"profile_edit_action": "edit:mobile_phone"},
        previous_workflow=form["workflow_data"],
        answer_field="profile_edit_action",
    )
    edited, _, _ = await run_target(
        section=BASIC.key,
        resource=CONTACT.key,
        collected={MOBILE.key: "0987654321"},
        previous_workflow=ask_value["workflow_data"],
    )
    reviewed, pending, _ = await run_target(
        section=BASIC.key,
        resource=CONTACT.key,
        collected={"profile_edit_action": "finish"},
        previous_workflow=edited["workflow_data"],
        answer_field="profile_edit_action",
    )

    clarification = reviewed["response_data"]["clarification"]
    assert clarification["input_type"] == "edit_session_actions"
    assert reviewed["workflow_data"]["profile_changes"] == {
        MOBILE.key: "0987654321"
    }
    assert pending.created == []


def test_18_small_typo_uses_registry_alias_without_hardcoded_phrase():
    certificate_name = field(
        "certificate_name", "T\u00ean v\u0103n b\u1eb1ng/ch\u1ee9ng ch\u1ec9"
    )
    certificates = ProfileResource(
        key="certificate_records",
        label="V\u0103n b\u1eb1ng, ch\u1ee9ng ch\u1ec9",
        aliases=("ch\u1ee9ng ch\u1ec9",),
        section_key=EDUCATION.key,
        resource_type="collection",
        readable=True,
        creatable=True,
        updatable=True,
        deletable=True,
        fields=(certificate_name,),
    )

    resolution = ProfileTargetResolver._resolve_exact_match(
        "th\u00eam 1 ch\u1ee9ng ch\u1ee7",
        Intent.PROFILE_CERTIFICATES,
        Operation.CREATE,
        (EDUCATION,),
        (certificates,),
    )

    assert resolution is not None
    assert resolution.resource_key == certificates.key
    assert resolution.reason_code == "EXACT_COLLECTION_MATCH"


@pytest.mark.parametrize(
    ("query", "expected_key"),
    (("sửa giới tính", "gender"), ("sửa ngày sinh", "birth_date")),
)
def test_19_unqualified_duplicate_label_prefers_direct_section_field(
    query, expected_key,
):
    relation_field = field(expected_key, {
        "gender": "Giới tính", "birth_date": "Ngày sinh"
    }[expected_key])
    relations = ProfileResource(
        key="family_relations", label="Quan hệ thân nhân",
        aliases=("người thân",), section_key="family",
        resource_type="collection", readable=True, creatable=True,
        updatable=True, deletable=True, fields=(relation_field,),
    )
    resolution = ProfileTargetResolver._resolve_exact_match(
        query, Intent.PROFILE_BASIC, Operation.UPDATE,
        (BASIC,), (CONTACT, relations),
    )
    assert resolution is not None
    assert resolution.resource_key is None
    assert resolution.field_keys == [expected_key]
    assert resolution.reason_code == "DIRECT_FIELD_TIE_BREAK"


def test_19b_duplicate_resource_field_uses_classifier_intent_owner():
    address_hometown = field("hometown", "Quê quán")
    relative_hometown = field("hometown", "Quê quán")
    address = ProfileResource(
        key="address_information", label="Thông tin địa chỉ",
        section_key=BASIC.key, resource_type="singleton", readable=True,
        creatable=False, updatable=True, deletable=False,
        fields=(address_hometown,),
    )
    family = ProfileResource(
        key="family_relations", label="Quan hệ gia đình",
        section_key="family", resource_type="collection", readable=True,
        creatable=True, updatable=True, deletable=True,
        fields=(relative_hometown,),
    )
    resolution = ProfileTargetResolver._resolve_exact_match(
        "sửa quê quán", Intent.PROFILE_ADDRESS, Operation.UPDATE,
        (BASIC, ProfileSection(key="family", label="Gia đình")),
        (address, family),
    )
    assert resolution is not None
    assert resolution.resource_key == address.key
    assert resolution.field_keys == ["hometown"]
    assert resolution.reason_code == "INTENT_OWNED_FIELD_MATCH"


@pytest.mark.parametrize(
    "query",
    (
        "sửa hồ sơ",
        "cập nhật thông tin của tôi",
        "sửa hồ sơ tự khai cá nhân",
    ),
)
def test_19c_generic_profile_target_does_not_select_a_field(query: str):
    resolution = ProfileTargetResolver._resolve_exact_match(
        query, Intent.PROFILE_SUMMARY, Operation.UPDATE,
        SECTIONS, RESOURCES,
    )
    assert resolution is not None
    assert resolution.section_key is None
    assert resolution.resource_key is None
    assert resolution.field_keys == []
    assert resolution.needs_clarification is True
    assert resolution.reason_code == "GENERIC_PROFILE_TARGET"


@pytest.mark.asyncio
async def test_20_invalid_draft_save_keeps_review_controls_and_changes():
    reviewed, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        fields=(MOBILE.key,), changes={MOBILE.key: "0987654321"},
        collected={"profile_edit_action": "finish"},
        answer_field="profile_edit_action",
    )
    failed, pending, schema = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "save_draft"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
        schema_error=ProfileSchemaError(
            "PROFILE_INVALID_VALUE",
            "Ngày vào đơn vị phải nhỏ hơn ngày chính thức",
        ),
    )
    clarification = failed["response_data"]["clarification"]
    assert clarification["input_type"] == "resource_form"
    assert {item["value"] for item in clarification["options"]} == {
        "finish", "cancel",
    }
    assert "Ngày vào đơn vị" in failed["response_text"]
    assert failed["workflow_data"]["profile_changes"] == {
        MOBILE.key: "0987654321"
    }
    assert pending.created == []
    assert len(schema.saved_drafts) == 1


@pytest.mark.asyncio
async def test_21_inline_edits_accumulate_and_continue_keeps_session():
    form, _, _ = await run_target(section=BASIC.key, resource=CONTACT.key)
    session_id = form["response_data"]["clarification"]["session_id"]
    first, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={MOBILE.key: "0987654321"},
        previous_workflow=form["workflow_data"],
        answer_field=MOBILE.key, answer_type="profile_field_edit",
    )
    second, _, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={EMAIL.key: "dev@vnpt.vn"},
        previous_workflow=first["workflow_data"],
        answer_field=EMAIL.key, answer_type="profile_field_edit",
    )
    assert second["workflow_data"]["profile_changes"] == {
        MOBILE.key: "0987654321", EMAIL.key: "dev@vnpt.vn",
    }
    reviewed, pending, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "finish"},
        previous_workflow=second["workflow_data"],
        answer_field="profile_edit_action",
    )
    assert pending.created == []
    resumed, pending, _ = await run_target(
        section=BASIC.key, resource=CONTACT.key,
        collected={"profile_edit_action": "continue"},
        previous_workflow=reviewed["workflow_data"],
        answer_field="profile_edit_action",
    )
    clarification = resumed["response_data"]["clarification"]
    assert clarification["input_type"] == "resource_form"
    assert clarification["session_id"] == session_id
    assert resumed["workflow_data"]["profile_changes"] == {
        MOBILE.key: "0987654321", EMAIL.key: "dev@vnpt.vn",
    }
    assert pending.created == []


@pytest.mark.asyncio
async def test_22_create_finish_requires_all_registry_required_fields():
    form, _, _ = await run_target(
        section=EDUCATION.key, resource=CERTIFICATES.key,
        operation=Operation.CREATE,
    )
    result, pending, _ = await run_target(
        section=EDUCATION.key, resource=CERTIFICATES.key,
        operation=Operation.CREATE,
        collected={"profile_edit_action": "finish"},
        previous_workflow=form["workflow_data"],
        answer_field="profile_edit_action",
    )
    clarification = result["response_data"]["clarification"]
    assert result["response_text"].startswith(
        "Vui lòng hoàn thiện các trường bắt buộc"
    )
    assert {
        item["field_key"] for item in clarification["fields"]
        if item["status"] == "invalid"
    } == {CERTIFICATE_NAME.key, CERTIFICATE_TYPE.key}
    assert pending.created == []


@pytest.mark.asyncio
async def test_23_many2one_draft_uses_selected_label_not_opaque_id():
    form, _, _ = await run_target(
        section=EDUCATION.key, resource=CERTIFICATES.key,
        operation=Operation.CREATE,
    )
    edited, _, _ = await run_target(
        section=EDUCATION.key, resource=CERTIFICATES.key,
        operation=Operation.CREATE,
        collected={CERTIFICATE_TYPE.key: "2"},
        previous_workflow=form["workflow_data"],
        answer_field=CERTIFICATE_TYPE.key,
        answer_type="profile_field_edit",
        answer_label="Chứng chỉ ngoại ngữ",
    )
    clarification = edited["response_data"]["clarification"]
    row = next(
        item for item in clarification["fields"]
        if item["field_key"] == CERTIFICATE_TYPE.key
    )
    assert row["draft_raw_value"] == "2"
    assert row["draft_value"] == "Chứng chỉ ngoại ngữ"
    assert row["display_value"] == "— → Chứng chỉ ngoại ngữ"
