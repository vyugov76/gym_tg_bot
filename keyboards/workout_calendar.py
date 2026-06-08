"""Календарь тренировок на базе aiogram-calendar с подсветкой дней."""

from __future__ import annotations

import calendar
import logging
from datetime import datetime

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram_calendar import SimpleCalendar
from aiogram_calendar.schemas import SimpleCalendarCallback, SimpleCalAct, highlight, superscript

import database.requests as db

logger = logging.getLogger(__name__)


class WorkoutCalendar(SimpleCalendar):
    """SimpleCalendar: дни с тренировками помечаются эмодзи 🔥."""

    def __init__(self, user_id: int, locale: str | None = None) -> None:
        super().__init__(locale=locale)
        self.user_id = user_id
        self.workout_days: set[int] = set()

    async def _load_workout_days(self, year: int, month: int) -> None:
        logger.info(
            "Загрузка дней тренировок: user_id=%s year=%s month=%s",
            self.user_id,
            year,
            month,
        )
        self.workout_days = await db.get_workout_days_for_month(
            self.user_id, year, month
        )
        logger.info(
            "Дни с тренировками: user_id=%s days=%s",
            self.user_id,
            sorted(self.workout_days),
        )

    async def start_calendar(
        self,
        year: int = datetime.now().year,
        month: int = datetime.now().month,
    ) -> InlineKeyboardMarkup:
        await self._load_workout_days(year, month)

        today = datetime.now()
        now_weekday = self._labels.days_of_week[today.weekday()]
        now_month, now_year, now_day = today.month, today.year, today.day

        def highlight_month() -> str:
            month_str = self._labels.months[month - 1]
            if now_month == month and now_year == year:
                return highlight(month_str)
            return month_str

        def highlight_weekday(weekday: str) -> str:
            if now_month == month and now_year == year and now_weekday == weekday:
                return highlight(weekday)
            return weekday

        def format_day_label(day: int) -> str:
            label = str(day)
            if day in self.workout_days:
                label = f"🔥{day}"
            date_to_check = datetime(year, month, day)
            if self.min_date and date_to_check < self.min_date:
                return superscript(label)
            if self.max_date and date_to_check > self.max_date:
                return superscript(label)
            if now_month == month and now_year == year and now_day == day:
                return highlight(label)
            return label

        kb: list[list[InlineKeyboardButton]] = []

        kb.append([
            InlineKeyboardButton(
                text="<<",
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.prev_y, year=year, month=month, day=1
                ).pack(),
            ),
            InlineKeyboardButton(
                text=str(year) if year != now_year else highlight(str(year)),
                callback_data=self.ignore_callback,
            ),
            InlineKeyboardButton(
                text=">>",
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.next_y, year=year, month=month, day=1
                ).pack(),
            ),
        ])

        kb.append([
            InlineKeyboardButton(
                text="<",
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.prev_m, year=year, month=month, day=1
                ).pack(),
            ),
            InlineKeyboardButton(text=highlight_month(), callback_data=self.ignore_callback),
            InlineKeyboardButton(
                text=">",
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.next_m, year=year, month=month, day=1
                ).pack(),
            ),
        ])

        kb.append([
            InlineKeyboardButton(text=highlight_weekday(wd), callback_data=self.ignore_callback)
            for wd in self._labels.days_of_week
        ])

        for week in calendar.monthcalendar(year, month):
            days_row = []
            for day in week:
                if day == 0:
                    days_row.append(
                        InlineKeyboardButton(text=" ", callback_data=self.ignore_callback)
                    )
                    continue
                days_row.append(
                    InlineKeyboardButton(
                        text=format_day_label(day),
                        callback_data=SimpleCalendarCallback(
                            act=SimpleCalAct.day, year=year, month=month, day=day
                        ).pack(),
                    )
                )
            kb.append(days_row)

        kb.append([
            InlineKeyboardButton(
                text=self._labels.cancel_caption,
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.cancel, year=year, month=month, day=1
                ).pack(),
            ),
            InlineKeyboardButton(text=" ", callback_data=self.ignore_callback),
            InlineKeyboardButton(
                text=self._labels.today_caption,
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.today, year=year, month=month, day=1
                ).pack(),
            ),
        ])

        return InlineKeyboardMarkup(inline_keyboard=kb)

    async def _update_calendar(self, query: CallbackQuery, with_date: datetime) -> None:
        await query.message.edit_reply_markup(
            reply_markup=await self.start_calendar(
                int(with_date.year), int(with_date.month)
            )
        )
