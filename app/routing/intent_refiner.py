from __future__ import annotations

from app.context.entities import SubjectMention
from app.routing.intent_taxonomy import (
    INTENT_DEFINITIONS,
    RoutingCanonicalizationError,
    canonicalize_classification,
)
from app.routing.schemas import (
    NormalizedQuery,
    QueryClassification,
    RuleHints,
)
from app.routing.taxonomy import Operation, QueryRoute, SubjectScope, SubjectType


def _subject_from_hints(hints: RuleHints) -> SubjectMention:
    if hints.named_employee_reference:
        subject_type = SubjectType.EMPLOYEE
    elif hints.department_reference:
        subject_type = SubjectType.DEPARTMENT
    elif hints.company_reference:
        subject_type = SubjectType.COMPANY
    elif hints.self_reference:
        subject_type = SubjectType.SELF
    else:
        subject_type = SubjectType.GENERAL
    return SubjectMention(type=subject_type)


def direct_classify_from_exclusive_hints(
    query: NormalizedQuery,
    hints: RuleHints,
) -> QueryClassification | None:
    del query
    exclusive = [hint for hint in hints.semantic_hints if hint.is_exclusive]
    if hints.operation_signals:
        return None
    intents = {
        intent for hint in exclusive for intent in hint.candidate_intents
    }
    all_hint_intents = {
        intent
        for hint in hints.semantic_hints
        for intent in hint.candidate_intents
    }
    if len(exclusive) != 1 or len(intents) != 1 or len(all_hint_intents) != 1:
        return None
    intent = next(iter(intents))
    definition = INTENT_DEFINITIONS[intent]
    if definition.operation is not Operation.READ:
        return None
    subject = _subject_from_hints(hints)
    scope = {
        SubjectType.SELF: SubjectScope.SELF,
        SubjectType.EMPLOYEE: SubjectScope.NAMED_EMPLOYEE,
        SubjectType.DEPARTMENT: SubjectScope.DEPARTMENT,
        SubjectType.COMPANY: SubjectScope.COMPANY,
        SubjectType.GENERAL: SubjectScope.GENERAL,
    }[subject.type]
    if scope not in definition.supported_scopes:
        return None
    return QueryClassification(
        route=QueryRoute.DATA_QUERY,
        domain=definition.domain,
        intent=intent,
        operation=Operation.READ,
        scope=scope,
        confidence=exclusive[0].confidence,
        reason_code="EXCLUSIVE_RULE_CLASSIFICATION",
    )


def repair_classification(
    classification: QueryClassification,
    subject: SubjectMention,
) -> QueryClassification:
    return canonicalize_classification(classification, subject)


__all__ = [
    "RoutingCanonicalizationError",
    "direct_classify_from_exclusive_hints",
    "repair_classification",
]
