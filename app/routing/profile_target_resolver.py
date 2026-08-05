from __future__ import annotations

import json
import logging
import re
import unicodedata
from difflib import SequenceMatcher

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.odoo.profile_schema import (
    ProfileField,
    ProfileResource,
    ProfileSection,
)
from app.llm.client import LlmClientError, StructuredOutputClient
from app.llm.structured_output import StructuredOutputError
from app.routing.taxonomy import Intent, Operation

logger = logging.getLogger(__name__)


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
    def hierarchy_is_consistent(self) -> ProfileTargetResolution:
        if self.field_keys and self.section_key is None:
            raise ValueError("section_key is required when field_keys are set")
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
Fields may belong directly to a section. For a direct field, return its
section_key and field_keys while leaving resource_key null. For a field inside
a singleton or collection, return its resource_key and owning section_key.
Recent profile targets are canonical short-term memory. Resolve a pronoun only
when exactly one recent target is compatible; otherwise request clarification.
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
        recent_profile_targets: list[dict[str, object]] | None = None,
        request_id: str | None = None,
    ) -> ProfileTargetResolution:
        exact = self._resolve_exact_match(
            original_query,
            intent,
            operation,
            sections,
            resources,
        )
        if exact is not None:
            self._validate_allowlist(exact, sections, resources)
            logger.info(
                "profile_target_resolved request_id=%s source=exact_allowlist "
                "sections=%s resources=%s fields=%s section_key=%s "
                "resource_key=%s field_keys=%s confidence=%s "
                "needs_clarification=%s reason_code=%s",
                request_id,
                len(sections),
                len(resources),
                sum(len(item.direct_fields) for item in sections)
                + sum(len(item.fields) for item in resources),
                exact.section_key,
                exact.resource_key,
                exact.field_keys,
                exact.confidence,
                exact.needs_clarification,
                exact.reason_code,
            )
            return exact
        candidate_sections = self._candidate_sections(
            sections,
            resources,
            intent,
        )
        payload = {
            "original_query": original_query,
            "intent": intent.value,
            "operation": operation.value,
            "candidate_sections": candidate_sections,
            "recent_profile_targets": (recent_profile_targets or [])[:5],
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
        logger.info(
            "profile_target_resolved request_id=%s sections=%s resources=%s "
            "fields=%s section_key=%s resource_key=%s field_keys=%s "
            "confidence=%s needs_clarification=%s reason_code=%s",
            request_id,
            len(sections),
            len(resources),
            sum(len(item.direct_fields) for item in sections)
            + sum(len(item.fields) for item in resources),
            result.section_key,
            result.resource_key,
            result.field_keys,
            result.confidence,
            result.needs_clarification,
            result.reason_code,
        )
        return result

    @classmethod
    def _resolve_exact_match(
        cls,
        original_query: str,
        intent: Intent,
        operation: Operation,
        sections: tuple[ProfileSection, ...],
        resources: tuple[ProfileResource, ...],
    ) -> ProfileTargetResolution | None:
        target = cls._target_text(original_query)
        if not target:
            return None

        intent_tokens = set(
            cls._normalized(intent.value.split(".", 1)[-1]).split()
        )

        def score(key: str, label: str, aliases: tuple[str, ...]) -> int:
            values = (key.replace("_", " "), label, *aliases)
            normalized = [cls._normalized(value) for value in values]
            semantic = max(
                (
                    100
                    if value == target
                    else 80
                    if target in value or value in target
                    else (
                        70 + round(20 * similarity)
                        if (similarity := SequenceMatcher(
                            None, target, value
                        ).ratio()) >= 0.82
                        else 0
                    )
                )
                for value in normalized
                if value
            )
            ranking = max(
                (
                    len(intent_tokens.intersection(value.split()))
                    for value in normalized
                ),
                default=0,
            )
            return semantic + ranking

        resource_matches = sorted(
            (
                (score(item.key, item.label, item.aliases), item)
                for item in resources
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        field_matches = sorted(
            [
                (score(field.key, field.label, field.aliases), section, None, field)
                for section in sections
                for field in section.direct_fields
            ]
            + [
                (score(field.key, field.label, field.aliases), None, resource, field)
                for resource in resources
                for field in resource.fields
            ],
            key=lambda item: item[0],
            reverse=True,
        )

        if not resource_matches or not field_matches:
            return None
        best_resource_score, best_resource = resource_matches[0]
        resource_is_unique = (
            len(resource_matches) == 1
            or best_resource_score > resource_matches[1][0]
        )
        tied_resources = [
            item for item in resource_matches if item[0] == best_resource_score
        ]
        if best_resource_score >= 80 and len(tied_resources) > 1:
            owning_sections = {item.section_key for _, item in tied_resources}
            if len(owning_sections) == 1:
                return ProfileTargetResolution(
                    section_key=next(iter(owning_sections)),
                    confidence=1,
                    needs_clarification=True,
                    reason_code="AMBIGUOUS_RESOURCE_MATCH",
                )
        if (
            operation is Operation.CREATE
            and best_resource.resource_type == "collection"
            and best_resource_score >= 80
            and resource_is_unique
        ):
            return ProfileTargetResolution(
                section_key=best_resource.section_key,
                resource_key=best_resource.key,
                confidence=1,
                needs_clarification=False,
                reason_code="EXACT_COLLECTION_MATCH",
            )

        best_field_score, section, resource, field = field_matches[0]
        field_is_unique = (
            len(field_matches) == 1 or best_field_score > field_matches[1][0]
        )
        tied_fields = [
            item for item in field_matches if item[0] == best_field_score
        ]
        if best_field_score >= 80 and len(tied_fields) > 1:
            # Labels such as "Ngày sinh" and "Giới tính" legitimately occur
            # both as a direct employee field and inside collection rows.  A
            # resource-qualified query selects that owner; otherwise the sole
            # direct section field is the most specific self-profile target.
            contextual_resources = {
                item.key
                for score_value, item in resource_matches
                if score_value >= 80
            }
            contextual = [
                item for item in tied_fields
                if item[2] is not None and item[2].key in contextual_resources
            ]
            if len(contextual) == 1:
                _, _, matched_resource, matched_field = contextual[0]
                return ProfileTargetResolution(
                    section_key=matched_resource.section_key,
                    resource_key=matched_resource.key,
                    field_keys=[matched_field.key],
                    confidence=1,
                    needs_clarification=False,
                    reason_code="CONTEXTUAL_FIELD_MATCH",
                )
            direct = [item for item in tied_fields if item[1] is not None]
            if not contextual_resources and len(direct) == 1:
                _, matched_section, _, matched_field = direct[0]
                return ProfileTargetResolution(
                    section_key=matched_section.key,
                    resource_key=None,
                    field_keys=[matched_field.key],
                    confidence=1,
                    needs_clarification=False,
                    reason_code="DIRECT_FIELD_TIE_BREAK",
                )
            owners = {
                (
                    item_section.key if item_section else item_resource.section_key,
                    item_resource.key if item_resource else None,
                )
                for _, item_section, item_resource, _ in tied_fields
            }
            if len(owners) == 1:
                owner_section, owner_resource = next(iter(owners))
                return ProfileTargetResolution(
                    section_key=owner_section,
                    resource_key=owner_resource,
                    field_keys=[item_field.key for *_, item_field in tied_fields],
                    confidence=1,
                    needs_clarification=True,
                    reason_code="AMBIGUOUS_FIELD_MATCH",
                )
        if best_field_score >= 80 and field_is_unique:
            if operation is Operation.CREATE and field.derived_from_resource:
                derived_resource = next(
                    (
                        item for item in resources
                        if item.key == field.derived_from_resource
                        and item.resource_type == "collection"
                        and item.creatable
                    ),
                    None,
                )
                if derived_resource is not None:
                    return ProfileTargetResolution(
                        section_key=derived_resource.section_key,
                        resource_key=derived_resource.key,
                        confidence=1,
                        needs_clarification=False,
                        reason_code="DERIVED_COLLECTION_CREATE",
                    )
            return ProfileTargetResolution(
                section_key=(section.key if section else resource.section_key),
                resource_key=resource.key if resource else None,
                field_keys=[field.key],
                confidence=1,
                needs_clarification=False,
                reason_code="EXACT_FIELD_MATCH",
            )
        if best_resource_score >= 80 and resource_is_unique:
            return ProfileTargetResolution(
                section_key=best_resource.section_key,
                resource_key=best_resource.key,
                confidence=1,
                needs_clarification=False,
                reason_code="EXACT_RESOURCE_MATCH",
            )
        return None

    @classmethod
    def _target_text(cls, query: str) -> str:
        leading_operation_words = {
            "sua",
            "them",
            "xoa",
            "cap",
            "nhat",
            "thay",
            "doi",
            "tao",
            "bo",
            "sung",
            "mot",
        }
        words = cls._normalized(query).split()
        while words and (
            words[0] in leading_operation_words or words[0].isdigit()
        ):
            words.pop(0)
        return " ".join(words)

    @staticmethod
    def _normalized(value: str) -> str:
        folded = unicodedata.normalize("NFD", value.casefold())
        letters = "".join(
                character
                for character in folded
                if unicodedata.category(character) != "Mn"
            )
        letters = letters.replace("đ", "d").replace("_", " ")
        return " ".join(re.sub(r"[^\w\s]", " ", letters).split())

    @staticmethod
    def _candidate_sections(
        sections: tuple[ProfileSection, ...],
        resources: tuple[ProfileResource, ...],
        intent: Intent,
    ) -> list[dict[str, object]]:
        """Build a compact, actor-scoped hierarchy without operation filtering."""

        def field_candidate(field: ProfileField) -> dict[str, object]:
            return {
                "key": field.key,
                "label": field.label,
                "aliases": field.aliases,
            }

        def resource_candidate(resource: ProfileResource) -> dict[str, object]:
            return {
                "key": resource.key,
                "label": resource.label,
                "aliases": resource.aliases,
                "fields": [field_candidate(field) for field in resource.fields],
            }

        intent_tokens = {
            token
            for part in intent.value.split(".", 1)[-1].split("_")
            for token in (part, part.removesuffix("s"))
            if token
        }

        def priority(value: object) -> tuple[bool, str]:
            searchable = " ".join(
                str(item)
                for item in (
                    getattr(value, "key", ""),
                    getattr(value, "label", ""),
                    *getattr(value, "aliases", ()),
                )
            ).casefold()
            return (
                not any(token in searchable for token in intent_tokens),
                searchable,
            )

        ordered_resources = sorted(resources, key=priority)
        ordered_sections = sorted(sections, key=priority)
        return [
            {
                "key": section.key,
                "label": section.label,
                "aliases": section.aliases,
                "direct_fields": [
                    field_candidate(field)
                    for field in sorted(section.direct_fields, key=priority)
                ],
                "singleton_resources": [
                    resource_candidate(resource)
                    for resource in ordered_resources
                    if resource.section_key == section.key
                    and resource.resource_type == "singleton"
                ],
                "collection_resources": [
                    resource_candidate(resource)
                    for resource in ordered_resources
                    if resource.section_key == section.key
                    and resource.resource_type == "collection"
                ],
            }
            for section in ordered_sections
        ]

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
            if result.section_key is None:
                if result.field_keys:
                    raise ProfileTargetOutsideAllowlistError()
                return
            direct_fields = {
                item.key for item in section_map[result.section_key].direct_fields
            }
            if any(key not in direct_fields for key in result.field_keys):
                raise ProfileTargetOutsideAllowlistError()
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
