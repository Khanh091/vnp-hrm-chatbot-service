from __future__ import annotations

from typing import Any

import pytest

from app.routing.query_classifier import QueryClassifier
from app.routing.query_normalizer import QueryNormalizer
from app.routing.rules import infer_rule_hints
from app.routing.schemas import Domain, QueryClassification
from app.routing.taxonomy import (
    Intent,
    Operation,
    QueryRoute,
    SubjectScope,
)


class _ClassifierClient:
    def __init__(self, intent: Intent) -> None:
        self.intent = intent
        self.calls = 0
        self.user_prompt = ""

    async def complete_structured(self, **kwargs: Any) -> QueryClassification:
        self.calls += 1
        self.user_prompt = kwargs["user_prompt"]
        return QueryClassification(
            route=QueryRoute.UNSUPPORTED,
            domain=Domain.GENERAL,
            intent=self.intent,
            operation=Operation.NONE,
            scope=SubjectScope.SELF,
            confidence=0.92,
            reason_code="LLM_CLASSIFICATION",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "intent", "domain", "scope", "exclusive"),
    [
        (
            "tôi có là đảng viên không",
            Intent.PROFILE_PARTY_UNION,
            Domain.PROFILE,
            SubjectScope.SELF,
            True,
        ),
        (
            "trình độ giáo dục phổ thông của tôi",
            Intent.PROFILE_EDUCATION,
            Domain.PROFILE,
            SubjectScope.SELF,
            True,
        ),
        (
            "trình độ đào tạo của tôi",
            Intent.PROFILE_EDUCATION,
            Domain.PROFILE,
            SubjectScope.SELF,
            True,
        ),
        (
            "lịch sử đào tạo bồi dưỡng của tôi",
            Intent.PROFILE_TRAINING_HISTORY,
            Domain.PROFILE,
            SubjectScope.SELF,
            False,
        ),
        (
            "nơi ở hiện nay của tôi",
            Intent.PROFILE_ADDRESS,
            Domain.PROFILE,
            SubjectScope.SELF,
            True,
        ),
        (
            "ngày cấp CCCD của tôi",
            Intent.PROFILE_IDENTITY,
            Domain.PROFILE,
            SubjectScope.SELF,
            True,
        ),
        (
            "ngày cấp chứng chỉ TOEIC của tôi",
            Intent.PROFILE_CERTIFICATES,
            Domain.PROFILE,
            SubjectScope.SELF,
            False,
        ),
        (
            "so lan quen cham cong cua toi",
            Intent.ATTENDANCE_MISSING_PUNCH_COUNT,
            Domain.ATTENDANCE,
            SubjectScope.SELF,
            True,
        ),
        (
            "Lo Van Dinh o co quan nao",
            Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
            Domain.DIRECTORY,
            SubjectScope.NAMED_EMPLOYEE,
            False,
        ),
        (
            "địa chỉ cơ quan của Lò Văn Định",
            Intent.DIRECTORY_EMPLOYEE_DEPARTMENT,
            Domain.DIRECTORY,
            SubjectScope.NAMED_EMPLOYEE,
            False,
        ),
    ],
)
async def test_semantic_routing_cases(
    query: str,
    intent: Intent,
    domain: Domain,
    scope: SubjectScope,
    exclusive: bool,
) -> None:
    normalized = QueryNormalizer().normalize(query)
    hints = infer_rule_hints(normalized)
    client = _ClassifierClient(intent)

    result = await QueryClassifier(client).classify(normalized)

    assert result.intent is intent
    assert result.domain is domain
    assert result.route is QueryRoute.DATA_QUERY
    assert result.operation is Operation.READ
    assert result.scope is scope
    assert client.calls == (0 if exclusive else 1)
    assert normalized.folded_text
    if query == "ngày cấp chứng chỉ TOEIC của tôi":
        hinted = {
            item
            for hint in hints.semantic_hints
            for item in hint.candidate_intents
        }
        assert Intent.PROFILE_CERTIFICATES in hinted
        assert Intent.PROFILE_IDENTITY not in hinted
    if query == "địa chỉ cơ quan của Lò Văn Định":
        hinted = {
            item
            for hint in hints.semantic_hints
            for item in hint.candidate_intents
        }
        assert hinted == {Intent.DIRECTORY_EMPLOYEE_DEPARTMENT}
