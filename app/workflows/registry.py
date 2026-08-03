from app.routing.taxonomy import Intent
from app.workflows.definitions import SlotDefinition, WorkflowDefinition


class WorkflowRegistry:
    def __init__(
        self,
        definitions: tuple[WorkflowDefinition, ...] = (),
    ) -> None:
        self._definitions = {
            definition.tool_name: definition for definition in definitions
        }
        self._by_intent = {
            definition.intent: definition for definition in definitions
        }

    def get(self, tool_name: str) -> WorkflowDefinition | None:
        return self._definitions.get(tool_name)

    def get_by_intent(self, intent: Intent) -> WorkflowDefinition | None:
        return self._by_intent.get(intent)


def _slot(
    name: str,
    entity_type: str,
    priority: int,
    prompt: str,
    *,
    required: bool = True,
    allows_structured_option: bool = False,
    validator_name: str | None = None,
) -> SlotDefinition:
    return SlotDefinition(
        name=name,
        entity_type=entity_type,
        required=required,
        priority=priority,
        prompt=prompt,
        allows_structured_option=allows_structured_option,
        validator_name=validator_name,
    )


def build_workflow_registry() -> WorkflowRegistry:
    date_from = _slot(
        "date_from",
        "temporal.date_from",
        1,
        "Bạn muốn bắt đầu nghỉ từ ngày nào?",
        validator_name="date",
    )
    date_to = _slot(
        "date_to",
        "temporal.date_to",
        2,
        "Bạn muốn nghỉ đến ngày nào?",
        validator_name="date_range",
    )
    leave_type = _slot(
        "leave_type_id",
        "business.leave_type",
        3,
        "Bạn muốn sử dụng loại nghỉ nào?",
        allows_structured_option=True,
        validator_name="positive_id",
    )
    reason = _slot(
        "reason",
        "business.reason",
        4,
        "Bạn muốn ghi lý do nghỉ là gì?",
    )
    request_id = _slot(
        "request_id",
        "business.leave_request",
        1,
        "Bạn muốn thao tác với đơn nghỉ nào?",
        allows_structured_option=True,
        validator_name="positive_id",
    )
    changes = _slot(
        "changes",
        "business.leave_changes",
        2,
        "Bạn muốn sửa thông tin nào?",
        allows_structured_option=True,
    )
    return WorkflowRegistry(
        (
            WorkflowDefinition(
                intent=Intent.LEAVE_CREATE,
                tool_name="leave_create_request",
                slots=(date_from, date_to, leave_type, reason),
                requires_confirmation=True,
                confirmation_title="Xác nhận tạo đơn nghỉ phép",
                confirmation_question=(
                    "Bạn có xác nhận tạo đơn nghỉ phép không?"
                ),
            ),
            WorkflowDefinition(
                intent=Intent.LEAVE_UPDATE,
                tool_name="leave_update_request",
                slots=(request_id, changes),
                requires_confirmation=True,
                confirmation_title="Xác nhận cập nhật đơn nghỉ phép",
                confirmation_question=(
                    "Bạn có xác nhận cập nhật đơn nghỉ phép không?"
                ),
            ),
            WorkflowDefinition(
                intent=Intent.LEAVE_CANCEL,
                tool_name="leave_cancel_request",
                slots=(request_id,),
                requires_confirmation=True,
                confirmation_title="Xác nhận hủy đơn nghỉ phép",
                confirmation_question=(
                    "Bạn có xác nhận hủy đơn nghỉ phép không?"
                ),
            ),
        )
    )
