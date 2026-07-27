from app.tools.catalogs.attendance import ATTENDANCE_TOOLS
from app.tools.catalogs.leave import LEAVE_TOOLS
from app.tools.catalogs.profile import PROFILE_TOOLS
from app.tools.definitions import ToolDefinition

ALL_TOOLS: tuple[ToolDefinition, ...] = (
    *PROFILE_TOOLS,
    *ATTENDANCE_TOOLS,
    *LEAVE_TOOLS,
)

__all__ = [
    "ALL_TOOLS",
    "ATTENDANCE_TOOLS",
    "LEAVE_TOOLS",
    "PROFILE_TOOLS",
]
