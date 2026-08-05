import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.context.conversation import ConversationStatus
from app.context.dialog_manager import DialogTurnManager
from app.integrations.odoo.profile_schema import (
    ProfileField,
    ProfileOption,
    ProfileResource,
    ProfileSection,
    ProfileSnapshot,
    ProfileWriteMode,
)
from app.orchestration.nodes.detect_turn_type import detect_turn_type_node
from app.orchestration.nodes.resolve_profile_write import (
    _merge_profile_target,
    resolve_profile_write_node,
)
from app.orchestration.state import TurnType
from app.routing.profile_target_resolver import (
    ProfileTargetResolution,
    ProfileTargetResolver,
)
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import Intent, Operation, QueryRoute, SubjectScope


def _field(
    key: str,
    label: str,
    *,
    section: str,
    resource: str | None = None,
    field_type: str = "text",
    required: bool = False,
    option_provider: str | None = None,
) -> ProfileField:
    return ProfileField(
        key=key,
        label=label,
        field_type=field_type,
        readable=True,
        creatable=resource == "certificate_records",
        updatable=True,
        deletable=False,
        required_on_create=required,
        write_mode=ProfileWriteMode.APPROVAL_REQUEST,
        section_key=section,
        resource_key=resource,
        option_provider=option_provider,
    )


MOBILE = _field(
    "mobile_phone",
    "Điện thoại di động",
    section="basic_profile",
    resource="contact_information",
    field_type="phone",
)
EMAIL = _field(
    "work_email",
    "Email công việc",
    section="basic_profile",
    resource="contact_information",
    field_type="email",
)
HOMETOWN = _field("hometown", "Quê quán", section="basic_profile")
CERTIFICATE_TYPE = _field(
    "certificate_type",
    "Loại chứng chỉ",
    section="education_training",
    resource="certificate_records",
    field_type="text",
    required=True,
    option_provider="certificate_type_options",
)
CERTIFICATE_FIELD = _field(
    "certificate_field",
    "Lĩnh vực chứng chỉ",
    section="education_training",
    resource="certificate_records",
    field_type="many2one",
    required=True,
    option_provider="certificate_field_options",
)
CERTIFICATE_NAME = _field(
    "certificate_name",
    "Tên văn bằng/chứng chỉ",
    section="education_training",
    resource="certificate_records",
    field_type="many2one",
    required=True,
    option_provider="certificate_name_options",
)

CONTACT = ProfileResource(
    key="contact_information",
    label="Thông tin liên hệ",
    section_key="basic_profile",
    resource_type="singleton",
    readable=True,
    creatable=False,
    updatable=True,
    deletable=False,
    fields=(MOBILE, EMAIL),
)
CERTIFICATES = ProfileResource(
    key="certificate_records",
    label="Văn bằng, chứng chỉ",
    section_key="education_training",
    resource_type="collection",
    readable=True,
    creatable=True,
    updatable=True,
    deletable=True,
    fields=(CERTIFICATE_TYPE, CERTIFICATE_FIELD, CERTIFICATE_NAME),
)
BASIC = ProfileSection(
    key="basic_profile",
    label="Thông tin cơ bản",
    direct_fields=(HOMETOWN,),
    resource_keys=(CONTACT.key,),
)
EDUCATION = ProfileSection(
    key="education_training",
    label="Giáo dục và đào tạo",
    resource_keys=(CERTIFICATES.key,),
)
SECTIONS = (BASIC, EDUCATION)
RESOURCES = (CONTACT, CERTIFICATES)


class _Llm:
    def __init__(self, result: ProfileTargetResolution) -> None:
        self.result = result
        self.payloads: list[dict[str, Any]] = []

    async def complete_structured(self, **kwargs: Any) -> ProfileTargetResolution:
        self.payloads.append(json.loads(kwargs["user_prompt"]))
        return self.result


class _Schema:
    async def get_sections(self, operation: Operation | None, **kwargs: Any):
        return SECTIONS

    async def get_section(
        self, key: str, operation: Operation | None, **kwargs: Any
    ) -> ProfileSection:
        return next(item for item in SECTIONS if item.key == key)

    async def get_resources(
        self, section_key: str, operation: Operation | None, **kwargs: Any
    ):
        return tuple(item for item in RESOURCES if item.section_key == section_key)

    async def get_resource(self, key: str, **kwargs: Any) -> ProfileResource:
        return next(item for item in RESOURCES if item.key == key)

    async def get_fields(
        self, key: str, operation: Operation, **kwargs: Any
    ) -> tuple[ProfileField, ...]:
        resource = await self.get_resource(key)
        return tuple(field for field in resource.fields if field.allows(operation))

    async def get_current_snapshot(self, key: str, **kwargs: Any):
        return ProfileSnapshot(
            resource_key=key,
            snapshot={"mobile_phone": "0900000000", "work_email": "old@vnpt.vn"},
            version="resource-v1",
        )

    async def get_section_snapshot(self, key: str, **kwargs: Any):
        return ProfileSnapshot(
            section_key=key,
            snapshot={"hometown": "Hà Nội"},
            version="section-v1",
        )

    async def get_field_options(self, key: str, field: str, **kwargs: Any):
        return (ProfileOption(value="allowed-1", label=f"Option {field}"),)


class _Conversations:
    def __init__(self) -> None:
        self.cleared: list[tuple[str, int]] = []

    async def load_owned(self, *args: Any, **kwargs: Any):
        return object()

    async def update(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def clear_active_workflow(self, conversation_id: str, actor: int):
        self.cleared.append((conversation_id, actor))


class _Pending:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def cancel(self, action_id: str, **kwargs: Any):
        self.cancelled.append(action_id)


class _EntityMemory:
    def capture(self, *, memory, **kwargs: Any):
        return memory


async def _run(
    query: str,
    intent: Intent,
    operation: Operation,
    resolution: ProfileTargetResolution,
):
    llm = _Llm(resolution)
    conversations = _Conversations()
    context = SimpleNamespace(
        profile_schema_client=_Schema(),
        profile_target_resolver=ProfileTargetResolver(llm),
        conversation_service=conversations,
        pending_action_service=_Pending(),
        entity_memory_service=_EntityMemory(),
    )
    classification = QueryClassification(
        route=QueryRoute.TASK,
        domain=Domain.PROFILE,
        intent=intent,
        operation=operation,
        scope=SubjectScope.SELF,
        confidence=0.99,
        reason_code="TEST",
    )
    state = {
        "conversation_id": "new-conversation",
        "request_id": "request-1",
        "user_message": query,
        "trusted_context": {"odoo_user_id": 7},
        "classification": classification.model_dump(mode="json"),
        "workflow_data": {},
        "collected_arguments": {},
        "entity_memory": {},
    }
    result = await resolve_profile_write_node(
        state,
        SimpleNamespace(context=context),
    )
    payload = (
        llm.payloads[0]
        if llm.payloads
        else {
            "candidate_sections": ProfileTargetResolver._candidate_sections(
                SECTIONS,
                RESOURCES,
                intent,
            )
        }
    )
    return result, payload


@pytest.mark.asyncio
async def test_1_mobile_resolves_field_without_section_question() -> None:
    result, payload = await _run(
        "sửa số di động",
        Intent.PROFILE_CONTACT,
        Operation.UPDATE,
        ProfileTargetResolution(
            section_key=BASIC.key,
            resource_key=CONTACT.key,
            field_keys=[MOBILE.key],
            confidence=0.99,
            needs_clarification=False,
            reason_code="FIELD_MATCH",
        ),
    )
    assert result["response_data"]["clarification"]["slot_name"] == MOBILE.key
    assert result["profile_field_keys"] == [MOBILE.key]
    assert payload["candidate_sections"][0]["singleton_resources"][0][
        "fields"
    ][0]["label"] == MOBILE.label


@pytest.mark.asyncio
async def test_2_email_resolves_field_without_section_or_resource_question() -> None:
    result, payload = await _run(
        "sửa email",
        Intent.PROFILE_CONTACT,
        Operation.UPDATE,
        ProfileTargetResolution(
            section_key=BASIC.key,
            resource_key=CONTACT.key,
            field_keys=[EMAIL.key],
            confidence=0.99,
            needs_clarification=False,
            reason_code="FIELD_MATCH",
        ),
    )
    assert result["response_data"]["clarification"]["slot_name"] == EMAIL.key
    labels = {
        field["label"]
        for field in payload["candidate_sections"][0]["singleton_resources"][0][
            "fields"
        ]
    }
    assert EMAIL.label in labels


@pytest.mark.asyncio
async def test_3_hometown_direct_field_allows_null_resource_and_asks_value() -> None:
    result, payload = await _run(
        "sửa quê quán",
        Intent.PROFILE_ADDRESS,
        Operation.UPDATE,
        ProfileTargetResolution(
            section_key=BASIC.key,
            resource_key=None,
            field_keys=[HOMETOWN.key],
            confidence=0.99,
            needs_clarification=False,
            reason_code="DIRECT_FIELD_MATCH",
        ),
    )
    assert result["profile_resource_key"] is None
    assert result["response_data"]["clarification"]["slot_name"] == HOMETOWN.key
    assert payload["candidate_sections"][0]["direct_fields"][0]["label"] == (
        HOMETOWN.label
    )


@pytest.mark.asyncio
async def test_4_certificate_create_resolves_collection_and_select_slot() -> None:
    result, payload = await _run(
        "thêm 1 chứng chỉ",
        Intent.PROFILE_CERTIFICATES,
        Operation.CREATE,
        ProfileTargetResolution(
            section_key=EDUCATION.key,
            resource_key=CERTIFICATES.key,
            field_keys=[],
            confidence=0.99,
            needs_clarification=False,
            reason_code="COLLECTION_MATCH",
        ),
    )
    clarification = result["response_data"]["clarification"]
    assert clarification["slot_name"] == CERTIFICATE_TYPE.key
    assert clarification["input_type"] == "searchable_select"
    assert clarification["options"]
    collections = payload["candidate_sections"][1]["collection_resources"]
    assert collections[0]["label"] == CERTIFICATES.label


def test_5_direct_field_validation_accepts_null_resource() -> None:
    ProfileTargetResolver._validate_allowlist(
        ProfileTargetResolution(
            section_key=BASIC.key,
            resource_key=None,
            field_keys=[HOMETOWN.key],
            confidence=1,
            needs_clarification=False,
            reason_code="DIRECT_FIELD_MATCH",
        ),
        SECTIONS,
        RESOURCES,
    )


def test_6_resolution_merge_preserves_good_field_from_empty_later_result() -> None:
    merged = _merge_profile_target(
        BASIC.key,
        CONTACT.key,
        [EMAIL.key],
        None,
        ProfileTargetResolution(
            confidence=0.4,
            needs_clarification=True,
            reason_code="NO_REFINEMENT",
        ),
    )
    assert merged[:3] == (BASIC.key, CONTACT.key, [EMAIL.key])


@pytest.mark.asyncio
async def test_7_new_query_cancels_pending_confirmation_without_execution() -> None:
    pending = _Pending()
    conversations = _Conversations()
    state = {
        "conversation_id": "conversation-1",
        "user_message": "sửa email",
        "action_type": None,
        "clarification": None,
        "conversation_status": ConversationStatus.AWAITING_CONFIRMATION.value,
        "workflow_data": {"pending_action_id": "old-action"},
        "trusted_context": {"odoo_user_id": 7},
        "stage_timings": {},
        "graph_events": [],
        "current_step": 0,
    }
    runtime = SimpleNamespace(
        context=SimpleNamespace(
            conversation_service=conversations,
            pending_action_service=pending,
            dialog_turn_manager=object(),
        )
    )
    update = await detect_turn_type_node(state, runtime)
    assert update["turn_type"] is TurnType.NEW_QUERY
    assert pending.cancelled == ["old-action"]
    assert conversations.cleared == [("conversation-1", 7)]
    assert update["workflow_data"] == {}

    clarification_conversations = _Conversations()
    clarification_state = {
        **state,
        "conversation_status": ConversationStatus.AWAITING_CLARIFICATION.value,
        "workflow_data": {"current_field": "mobile_phone"},
    }
    clarification_runtime = SimpleNamespace(
        context=SimpleNamespace(
            conversation_service=clarification_conversations,
            pending_action_service=_Pending(),
            dialog_turn_manager=DialogTurnManager(),
        )
    )
    clarification_update = await detect_turn_type_node(
        clarification_state,
        clarification_runtime,
    )
    assert clarification_update["turn_type"] is TurnType.NEW_QUERY_OVERRIDE
    assert clarification_update["workflow_data"] == {}


@pytest.mark.asyncio
async def test_8_ambiguous_profile_write_still_asks_section() -> None:
    result, _ = await _run(
        "sửa hồ sơ",
        Intent.PROFILE_SUMMARY,
        Operation.UPDATE,
        ProfileTargetResolution(
            confidence=0.3,
            needs_clarification=True,
            reason_code="AMBIGUOUS_TARGET",
        ),
    )
    assert result["response_data"]["clarification"]["slot_name"] == (
        "profile_section_key"
    )
