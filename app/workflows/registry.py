from app.workflows.definitions import WorkflowDefinition


class WorkflowRegistry:
    def __init__(
        self, definitions: tuple[WorkflowDefinition, ...] = ()
    ) -> None:
        self._definitions = {
            definition.tool_name: definition for definition in definitions
        }

    def get(self, tool_name: str) -> WorkflowDefinition | None:
        return self._definitions.get(tool_name)


def build_workflow_registry() -> WorkflowRegistry:
    return WorkflowRegistry(
        (
            WorkflowDefinition(
                tool_name="leave_create_request",
                clarification_priority=(
                    "date_from",
                    "date_to",
                    "leave_type_id",
                    "reason",
                ),
                confirmation_title="Xác nhận tạo đơn nghỉ phép",
                confirmation_question=(
                    "Bạn có xác nhận tạo đơn nghỉ phép không?"
                ),
            ),
            WorkflowDefinition(
                tool_name="leave_update_request",
                clarification_priority=(
                    "request_id",
                    "date_from",
                    "date_to",
                    "leave_type_id",
                    "reason",
                ),
                confirmation_title="Xác nhận cập nhật đơn nghỉ phép",
                confirmation_question=(
                    "Bạn có xác nhận cập nhật đơn nghỉ phép không?"
                ),
            ),
            WorkflowDefinition(
                tool_name="leave_cancel_request",
                clarification_priority=("request_id",),
                confirmation_title="Xác nhận hủy đơn nghỉ phép",
                confirmation_question=(
                    "Bạn có xác nhận hủy đơn nghỉ phép không?"
                ),
            ),
        )
    )
