import re
from calendar import monthrange
from datetime import date, datetime, timedelta

import dateparser  # type: ignore[import-untyped]

from app.routing.schemas import ResolvedDateRange


class AmbiguousDateExpression(ValueError):
    pass


class DateResolver:
    def resolve(
        self,
        text: str,
        *,
        current_date: date,
        timezone: str,
    ) -> ResolvedDateRange | None:
        normalized = " ".join(text.lower().split())

        if re.search(r"\bthứ hai\b", normalized) and not re.search(
            r"\b(tuần này|tuần trước|tuần sau)\b", normalized
        ):
            raise AmbiguousDateExpression("thứ hai")

        resolvers = (
            self._relative_day(normalized, current_date),
            self._monday_next_week(normalized, current_date),
            self._relative_week(normalized, current_date),
            self._relative_month(normalized, current_date),
            self._relative_year(normalized, current_date),
            self._quarter(normalized, current_date),
        )
        deterministic = next(
            (item for item in resolvers if item is not None), None
        )
        if deterministic is not None:
            return deterministic
        parsed = dateparser.parse(
            normalized,
            languages=["vi"],
            settings={
                "RELATIVE_BASE": datetime.combine(
                    current_date, datetime.min.time()
                ),
                "TIMEZONE": timezone,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
            },
        )
        if parsed is None:
            return None
        value = parsed.date()
        return self._result(value, value, text, "dateparser_fallback")

    @staticmethod
    def _result(
        value_from: date,
        value_to: date,
        expression: str,
        kind: str,
    ) -> ResolvedDateRange:
        return ResolvedDateRange(
            date_from=value_from,
            date_to=value_to,
            source_expression=expression,
            resolution_type=kind,
        )

    def _relative_day(
        self, text: str, current: date
    ) -> ResolvedDateRange | None:
        values = (
            ("hôm nay", 0, "today"),
            ("hôm qua", -1, "yesterday"),
            ("ngày mai", 1, "tomorrow"),
        )
        for expression, offset, kind in values:
            if expression in text:
                value = current + timedelta(days=offset)
                return self._result(value, value, expression, kind)
        return None

    def _monday_next_week(
        self, text: str, current: date
    ) -> ResolvedDateRange | None:
        expression = "thứ hai tuần sau"
        if expression not in text:
            return None
        monday = current - timedelta(days=current.weekday())
        value = monday + timedelta(days=7)
        return self._result(value, value, expression, "next_week_monday")

    def _relative_week(
        self, text: str, current: date
    ) -> ResolvedDateRange | None:
        values = (
            ("tuần này", 0, "current_week"),
            ("tuần trước", -1, "previous_week"),
            ("tuần sau", 1, "next_week"),
        )
        monday = current - timedelta(days=current.weekday())
        for expression, offset, kind in values:
            if expression in text:
                start = monday + timedelta(days=offset * 7)
                return self._result(
                    start, start + timedelta(days=6), expression, kind
                )
        return None

    def _relative_month(
        self, text: str, current: date
    ) -> ResolvedDateRange | None:
        values = (
            ("tháng này", 0, "current_month"),
            ("tháng trước", -1, "previous_month"),
            ("tháng sau", 1, "next_month"),
        )
        for expression, offset, kind in values:
            if expression not in text:
                continue
            month_index = current.year * 12 + current.month - 1 + offset
            year, zero_based_month = divmod(month_index, 12)
            month = zero_based_month + 1
            start = date(year, month, 1)
            end = date(year, month, monthrange(year, month)[1])
            return self._result(start, end, expression, kind)
        return None

    def _relative_year(
        self, text: str, current: date
    ) -> ResolvedDateRange | None:
        values = (
            ("năm nay", current.year, "current_year"),
            ("năm trước", current.year - 1, "previous_year"),
        )
        for expression, year, kind in values:
            if expression in text:
                return self._result(
                    date(year, 1, 1),
                    date(year, 12, 31),
                    expression,
                    kind,
                )
        return None

    def _quarter(
        self, text: str, current: date
    ) -> ResolvedDateRange | None:
        match = re.search(r"\bquý\s*(i{1,3}|iv)\b", text)
        if match is None:
            return None
        roman = match.group(1)
        quarter = {"i": 1, "ii": 2, "iii": 3, "iv": 4}[roman]
        month = (quarter - 1) * 3 + 1
        start = date(current.year, month, 1)
        end_month = month + 2
        end = date(
            current.year,
            end_month,
            monthrange(current.year, end_month)[1],
        )
        expression = match.group(0)
        return self._result(start, end, expression, f"quarter_{quarter}")
