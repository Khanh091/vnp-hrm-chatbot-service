from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.context.entities import SubjectMention
from app.routing.capabilities import capability_names_for_intent
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import (
    Intent,
    Operation,
    QueryRoute,
    SubjectScope,
    SubjectType,
)


class IntentDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    domain: Domain
    route: QueryRoute
    operation: Operation
    supported_scopes: frozenset[SubjectScope]
    capability_names: frozenset[str]


class RoutingCanonicalizationError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


_PROFILE_SCOPES = frozenset(
    {SubjectScope.SELF, SubjectScope.NAMED_EMPLOYEE}
)
_SELF_SCOPES = frozenset({SubjectScope.SELF})
_GENERAL_SCOPES = frozenset(
    {SubjectScope.GENERAL, SubjectScope.SELF, SubjectScope.UNKNOWN}
)


def _definition(intent: Intent) -> IntentDefinition:
    prefix = intent.value.split(".", 1)[0]
    if prefix == "profile":
        return IntentDefinition(
            domain=Domain.PROFILE,
            route=QueryRoute.DATA_QUERY,
            operation=Operation.READ,
            supported_scopes=_PROFILE_SCOPES,
            capability_names=capability_names_for_intent(intent),
        )
    if prefix == "attendance":
        return IntentDefinition(
            domain=Domain.ATTENDANCE,
            route=QueryRoute.DATA_QUERY,
            operation=Operation.READ,
            supported_scopes=_PROFILE_SCOPES,
            capability_names=capability_names_for_intent(intent),
        )
    if prefix == "leave":
        operation = {
            Intent.LEAVE_CREATE: Operation.CREATE,
            Intent.LEAVE_UPDATE: Operation.UPDATE,
            Intent.LEAVE_CANCEL: Operation.CANCEL,
        }.get(intent, Operation.READ)
        return IntentDefinition(
            domain=Domain.LEAVE,
            route=(
                QueryRoute.TASK
                if operation is not Operation.READ
                else QueryRoute.DATA_QUERY
            ),
            operation=operation,
            supported_scopes=_SELF_SCOPES,
            capability_names=capability_names_for_intent(intent),
        )
    if prefix == "directory":
        scopes = {
            Intent.DIRECTORY_DEPARTMENTS: frozenset(
                {SubjectScope.COMPANY}
            ),
            Intent.DIRECTORY_DEPARTMENT_EMPLOYEES: frozenset(
                {SubjectScope.DEPARTMENT}
            ),
            Intent.DIRECTORY_EMPLOYEE_IN_DEPARTMENT: frozenset(
                {SubjectScope.NAMED_EMPLOYEE}
            ),
            Intent.DIRECTORY_EMPLOYEE_BY_CERTIFICATE: frozenset(
                {SubjectScope.DEPARTMENT, SubjectScope.COMPANY}
            ),
        }.get(intent, frozenset({SubjectScope.NAMED_EMPLOYEE}))
        return IntentDefinition(
            domain=Domain.DIRECTORY,
            route=QueryRoute.DATA_QUERY,
            operation=Operation.READ,
            supported_scopes=scopes,
            capability_names=capability_names_for_intent(intent),
        )
    if prefix == "report":
        return IntentDefinition(
            domain=Domain.REPORTING,
            route=QueryRoute.DATA_QUERY,
            operation=Operation.READ,
            supported_scopes=frozenset(
                {SubjectScope.DEPARTMENT, SubjectScope.COMPANY}
            ),
            capability_names=capability_names_for_intent(intent),
        )
    if prefix == "knowledge":
        return IntentDefinition(
            domain=Domain.GENERAL,
            route=QueryRoute.KNOWLEDGE,
            operation=Operation.READ,
            supported_scopes=_GENERAL_SCOPES,
            capability_names=capability_names_for_intent(intent),
        )
    if prefix == "general":
        return IntentDefinition(
            domain=Domain.GENERAL,
            route=QueryRoute.GENERAL,
            operation=Operation.NONE,
            supported_scopes=_GENERAL_SCOPES,
            capability_names=capability_names_for_intent(intent),
        )
    if prefix == "unsafe":
        return IntentDefinition(
            domain=Domain.GENERAL,
            route=QueryRoute.UNSAFE,
            operation=Operation.NONE,
            supported_scopes=_GENERAL_SCOPES,
            capability_names=capability_names_for_intent(intent),
        )
    return IntentDefinition(
        domain=Domain.GENERAL,
        route=QueryRoute.UNSUPPORTED,
        operation=Operation.NONE,
        supported_scopes=_GENERAL_SCOPES,
        capability_names=capability_names_for_intent(intent),
    )


INTENT_DEFINITIONS: dict[Intent, IntentDefinition] = {
    intent: _definition(intent) for intent in Intent
}


def scope_from_subject(subject: SubjectMention | None) -> SubjectScope | None:
    if subject is None:
        return None
    return {
        SubjectType.SELF: SubjectScope.SELF,
        SubjectType.EMPLOYEE: SubjectScope.NAMED_EMPLOYEE,
        SubjectType.DEPARTMENT: SubjectScope.DEPARTMENT,
        SubjectType.COMPANY: SubjectScope.COMPANY,
        SubjectType.GENERAL: SubjectScope.GENERAL,
    }[subject.type]


def canonicalize_classification(
    classification: QueryClassification,
    subject: SubjectMention | None = None,
) -> QueryClassification:
    if classification.intent is None:
        return classification
    definition = INTENT_DEFINITIONS[classification.intent]
    subject_scope = scope_from_subject(subject)
    scope = classification.scope
    reason_code = "LLM_CLASSIFICATION"
    if subject_scope is not None and subject_scope in definition.supported_scopes:
        if subject_scope is not SubjectScope.GENERAL and subject_scope is not scope:
            scope = subject_scope
            reason_code = "SCOPE_REPAIRED_FROM_SUBJECT"
    if scope not in definition.supported_scopes:
        if subject_scope in definition.supported_scopes:
            scope = subject_scope
            reason_code = "SCOPE_REPAIRED_FROM_SUBJECT"
        else:
            raise RoutingCanonicalizationError("ROUTING_SCOPE_NOT_SUPPORTED")
    canonical_fields_changed = (
        classification.domain is not definition.domain
        or classification.route is not definition.route
        or classification.operation is not definition.operation
    )
    if canonical_fields_changed and reason_code != "SCOPE_REPAIRED_FROM_SUBJECT":
        reason_code = "TAXONOMY_CANONICALIZED"
    return classification.model_copy(
        update={
            "domain": definition.domain,
            "route": definition.route,
            "operation": definition.operation,
            "scope": scope,
            "reason_code": reason_code,
        }
    )
