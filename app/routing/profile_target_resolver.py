from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.odoo.profile_schema import ProfileResource, ProfileSection
from app.llm.client import LlmClientError, StructuredOutputClient
from app.llm.structured_output import StructuredOutputError
from app.routing.taxonomy import Intent, Operation


class ProfileTargetResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_key: str | None = None
    resource_key: str | None = None
    field_keys: list[str] = Field(default_factory=list)
    record_reference_text: str | None = Field(default=None, max_length=300)
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=80)

    @field_validator("field_keys")
    @classmethod
    def unique_fields(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("field_keys must be unique")
        return value

    @model_validator(mode="after")
    def hierarchy_is_consistent(self) -> "ProfileTargetResolution":
        if self.field_keys and self.resource_key is None:
            raise ValueError("resource_key is required when field_keys are set")
        if self.resource_key is not None and self.section_key is None:
            raise ValueError("section_key is required when resource_key is set")
        return self


class ProfileTargetResolverError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ProfileTargetOutsideAllowlistError(ProfileTargetResolverError):
    def __init__(self) -> None:
        super().__init__("PROFILE_TARGET_OUTSIDE_ALLOWLIST")


_SYSTEM_PROMPT = """
Bạn resolve mục tiêu hồ sơ tự khai từ câu tiếng Việt sang các key registry.
Chỉ chọn section_key, resource_key và field_keys có trong candidate allowlist.
Không được tạo model_name, ORM field, record_id, domain, capability hay endpoint.
Intent chỉ là gợi ý nhóm nghiệp vụ; operation chỉ là thao tác mong muốn, không
quyết định quyền. Nếu chỉ chắc section thì để resource_key null. Nếu chỉ chắc
resource thì để field_keys rỗng. Giữ nguyên cụm từ nhận diện một dòng collection
(ví dụ TOEIC hoặc mũi 4) trong record_reference_text. Đánh dấu needs_clarification
khi chưa đủ mục tiêu cần thiết hoặc tín hiệu không độc nhất.
""".strip()


class ProfileTargetResolver:
    def __init__(self, llm_client: StructuredOutputClient) -> None:
        self._llm = llm_client

    async def resolve(
        self,
        *,
        original_query: str,
        intent: Intent,
        operation: Operation,
        sections: tuple[ProfileSection, ...],
        resources: tuple[ProfileResource, ...],
        request_id: str | None = None,
    ) -> ProfileTargetResolution:
        payload = {
            "original_query": original_query,
            "intent": intent.value,
            "operation": operation.value,
            "candidate_sections": [
                item.model_dump(mode="json") for item in sections
            ],
            "candidate_resources": [
                item.model_dump(mode="json") for item in resources
            ],
        }
        try:
            result = await self._llm.complete_structured(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                schema=ProfileTargetResolution,
                operation="profile_target_resolution",
                request_id=request_id,
            )
        except (LlmClientError, StructuredOutputError) as error:
            raise ProfileTargetResolverError(
                "PROFILE_TARGET_RESOLUTION_FAILED"
            ) from error
        self._validate_allowlist(result, sections, resources)
        return result

    @staticmethod
    def _validate_allowlist(
        result: ProfileTargetResolution,
        sections: tuple[ProfileSection, ...],
        resources: tuple[ProfileResource, ...],
    ) -> None:
        section_map = {item.key: item for item in sections}
        resource_map = {item.key: item for item in resources}
        if result.section_key is not None and result.section_key not in section_map:
            raise ProfileTargetOutsideAllowlistError()
        if result.resource_key is None:
            return
        resource = resource_map.get(result.resource_key)
        if resource is None or resource.section_key != result.section_key:
            raise ProfileTargetOutsideAllowlistError()
        allowed_fields = {item.key for item in resource.fields}
        if any(key not in allowed_fields for key in result.field_keys):
            raise ProfileTargetOutsideAllowlistError()


__all__ = [
    "ProfileTargetOutsideAllowlistError",
    "ProfileTargetResolution",
    "ProfileTargetResolver",
    "ProfileTargetResolverError",
]
