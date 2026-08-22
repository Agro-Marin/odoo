// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { evaluateExpr } from "@web/core/py_js/py";

describe.current.tags("headless");

function canon(v) {
    if (v === null || v === undefined) {
        return "None";
    }
    if (v === true) {
        return "True";
    }
    if (v === false) {
        return "False";
    }
    if (typeof v === "number") {
        return Number.isFinite(v) ? String(v) : "nonfinite";
    }
    if (typeof v === "string") {
        return "s:" + v;
    }
    if (Array.isArray(v)) {
        return "[" + v.map(canon).join(",") + "]";
    }
    const pad = (n, w) => String(Math.abs(n)).padStart(w, "0");
    if ("year" in v && "hour" in v) {
        return `DT(${pad(v.year, 4)}-${pad(v.month, 2)}-${pad(v.day, 2)} ${pad(v.hour, 2)}:${pad(v.minute, 2)}:${pad(v.second, 2)}.${pad(v.microsecond, 6)})`;
    }
    if ("hour" in v) {
        return `T(${pad(v.hour, 2)}:${pad(v.minute, 2)}:${pad(v.second, 2)})`;
    }
    if ("year" in v) {
        return `D(${pad(v.year, 4)}-${pad(v.month, 2)}-${pad(v.day, 2)})`;
    }
    if ("days" in v && "seconds" in v && "microseconds" in v) {
        return `TD(${v.days},${v.seconds},${v.microseconds})`;
    }
    return "?" + typeof v;
}

const CORPUS = `
datetime.date(2024,1,31) + relativedelta(days=1) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - relativedelta(days=1) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) + relativedelta(days=-1) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) - relativedelta(days=-1) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) + relativedelta(days=0) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) - relativedelta(days=0) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) + relativedelta(days=45) :: ok :: D(2024-03-16)
datetime.date(2024,1,31) - relativedelta(days=45) :: ok :: D(2023-12-17)
datetime.date(2024,1,31) + relativedelta(days=-45) :: ok :: D(2023-12-17)
datetime.date(2024,1,31) - relativedelta(days=-45) :: ok :: D(2024-03-16)
datetime.date(2024,1,31) + relativedelta(weeks=2) :: ok :: D(2024-02-14)
datetime.date(2024,1,31) - relativedelta(weeks=2) :: ok :: D(2024-01-17)
datetime.date(2024,1,31) + relativedelta(weeks=-3) :: ok :: D(2024-01-10)
datetime.date(2024,1,31) - relativedelta(weeks=-3) :: ok :: D(2024-02-21)
datetime.date(2024,1,31) + relativedelta(months=1) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) - relativedelta(months=1) :: ok :: D(2023-12-31)
datetime.date(2024,1,31) + relativedelta(months=-1) :: ok :: D(2023-12-31)
datetime.date(2024,1,31) - relativedelta(months=-1) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) + relativedelta(months=13) :: ok :: D(2025-02-28)
datetime.date(2024,1,31) - relativedelta(months=13) :: ok :: D(2022-12-31)
datetime.date(2024,1,31) + relativedelta(months=-13) :: ok :: D(2022-12-31)
datetime.date(2024,1,31) - relativedelta(months=-13) :: ok :: D(2025-02-28)
datetime.date(2024,1,31) + relativedelta(months=12) :: ok :: D(2025-01-31)
datetime.date(2024,1,31) - relativedelta(months=12) :: ok :: D(2023-01-31)
datetime.date(2024,1,31) + relativedelta(years=1) :: ok :: D(2025-01-31)
datetime.date(2024,1,31) - relativedelta(years=1) :: ok :: D(2023-01-31)
datetime.date(2024,1,31) + relativedelta(years=-1) :: ok :: D(2023-01-31)
datetime.date(2024,1,31) - relativedelta(years=-1) :: ok :: D(2025-01-31)
datetime.date(2024,1,31) + relativedelta(years=100) :: ok :: D(2124-01-31)
datetime.date(2024,1,31) - relativedelta(years=100) :: ok :: D(1924-01-31)
datetime.date(2024,1,31) + relativedelta(hours=1) :: ok :: DT(2024-01-31 01:00:00.000000)
datetime.date(2024,1,31) - relativedelta(hours=1) :: ok :: DT(2024-01-30 23:00:00.000000)
datetime.date(2024,1,31) + relativedelta(hours=24) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - relativedelta(hours=24) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) + relativedelta(hours=-1) :: ok :: DT(2024-01-30 23:00:00.000000)
datetime.date(2024,1,31) - relativedelta(hours=-1) :: ok :: DT(2024-01-31 01:00:00.000000)
datetime.date(2024,1,31) + relativedelta(hours=-24) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) - relativedelta(hours=-24) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) + relativedelta(hours=48) :: ok :: D(2024-02-02)
datetime.date(2024,1,31) - relativedelta(hours=48) :: ok :: D(2024-01-29)
datetime.date(2024,1,31) + relativedelta(minutes=1) :: ok :: DT(2024-01-31 00:01:00.000000)
datetime.date(2024,1,31) - relativedelta(minutes=1) :: ok :: DT(2024-01-30 23:59:00.000000)
datetime.date(2024,1,31) + relativedelta(minutes=1440) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - relativedelta(minutes=1440) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) + relativedelta(minutes=-90) :: ok :: DT(2024-01-30 22:30:00.000000)
datetime.date(2024,1,31) - relativedelta(minutes=-90) :: ok :: DT(2024-01-31 01:30:00.000000)
datetime.date(2024,1,31) + relativedelta(seconds=1) :: ok :: DT(2024-01-31 00:00:01.000000)
datetime.date(2024,1,31) - relativedelta(seconds=1) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.date(2024,1,31) + relativedelta(seconds=86400) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - relativedelta(seconds=86400) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) + relativedelta(seconds=-3600) :: ok :: DT(2024-01-30 23:00:00.000000)
datetime.date(2024,1,31) - relativedelta(seconds=-3600) :: ok :: DT(2024-01-31 01:00:00.000000)
datetime.date(2024,1,31) + relativedelta(microseconds=1) :: ok :: DT(2024-01-31 00:00:00.000001)
datetime.date(2024,1,31) - relativedelta(microseconds=1) :: ok :: DT(2024-01-30 23:59:59.999999)
datetime.date(2024,1,31) + relativedelta(microseconds=1000000) :: ok :: DT(2024-01-31 00:00:01.000000)
datetime.date(2024,1,31) - relativedelta(microseconds=1000000) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.date(2024,1,31) + relativedelta(microseconds=-1) :: ok :: DT(2024-01-30 23:59:59.999999)
datetime.date(2024,1,31) - relativedelta(microseconds=-1) :: ok :: DT(2024-01-31 00:00:00.000001)
datetime.date(2024,1,31) + relativedelta(day=1) :: ok :: D(2024-01-01)
datetime.date(2024,1,31) - relativedelta(day=1) :: ok :: D(2024-01-01)
datetime.date(2024,1,31) + relativedelta(day=15) :: ok :: D(2024-01-15)
datetime.date(2024,1,31) - relativedelta(day=15) :: ok :: D(2024-01-15)
datetime.date(2024,1,31) + relativedelta(day=31) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) - relativedelta(day=31) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) + relativedelta(month=1) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) - relativedelta(month=1) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) + relativedelta(month=2) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) - relativedelta(month=2) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) + relativedelta(month=12) :: ok :: D(2024-12-31)
datetime.date(2024,1,31) - relativedelta(month=12) :: ok :: D(2024-12-31)
datetime.date(2024,1,31) + relativedelta(year=2000) :: ok :: D(2000-01-31)
datetime.date(2024,1,31) - relativedelta(year=2000) :: ok :: D(2000-01-31)
datetime.date(2024,1,31) + relativedelta(year=1999) :: ok :: D(1999-01-31)
datetime.date(2024,1,31) - relativedelta(year=1999) :: ok :: D(1999-01-31)
datetime.date(2024,1,31) + relativedelta(hour=0) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.date(2024,1,31) - relativedelta(hour=0) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.date(2024,1,31) + relativedelta(hour=5) :: ok :: DT(2024-01-31 05:00:00.000000)
datetime.date(2024,1,31) - relativedelta(hour=5) :: ok :: DT(2024-01-31 05:00:00.000000)
datetime.date(2024,1,31) + relativedelta(hour=23) :: ok :: DT(2024-01-31 23:00:00.000000)
datetime.date(2024,1,31) - relativedelta(hour=23) :: ok :: DT(2024-01-31 23:00:00.000000)
datetime.date(2024,1,31) + relativedelta(minute=0) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.date(2024,1,31) - relativedelta(minute=0) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.date(2024,1,31) + relativedelta(minute=30) :: ok :: DT(2024-01-31 00:30:00.000000)
datetime.date(2024,1,31) - relativedelta(minute=30) :: ok :: DT(2024-01-31 00:30:00.000000)
datetime.date(2024,1,31) + relativedelta(second=0) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.date(2024,1,31) - relativedelta(second=0) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.date(2024,1,31) + relativedelta(second=59) :: ok :: DT(2024-01-31 00:00:59.000000)
datetime.date(2024,1,31) - relativedelta(second=59) :: ok :: DT(2024-01-31 00:00:59.000000)
datetime.date(2024,1,31) + relativedelta(microsecond=0) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.date(2024,1,31) - relativedelta(microsecond=0) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.date(2024,1,31) + relativedelta(microsecond=500000) :: ok :: DT(2024-01-31 00:00:00.500000)
datetime.date(2024,1,31) - relativedelta(microsecond=500000) :: ok :: DT(2024-01-31 00:00:00.500000)
datetime.date(2024,1,31) + relativedelta(weekday=0) :: ok :: D(2024-02-05)
datetime.date(2024,1,31) - relativedelta(weekday=0) :: ok :: D(2024-02-05)
datetime.date(2024,1,31) + relativedelta(weekday=4) :: ok :: D(2024-02-02)
datetime.date(2024,1,31) - relativedelta(weekday=4) :: ok :: D(2024-02-02)
datetime.date(2024,1,31) + relativedelta(weekday=6) :: ok :: D(2024-02-04)
datetime.date(2024,1,31) - relativedelta(weekday=6) :: ok :: D(2024-02-04)
datetime.date(2024,1,31) + relativedelta(weekday=-1) :: ok :: D(2024-02-04)
datetime.date(2024,1,31) - relativedelta(weekday=-1) :: ok :: D(2024-02-04)
datetime.date(2024,1,31) + relativedelta(weekday=-2) :: ok :: D(2024-02-03)
datetime.date(2024,1,31) - relativedelta(weekday=-2) :: ok :: D(2024-02-03)
datetime.date(2024,1,31) + relativedelta(weekday=-6) :: ok :: D(2024-02-06)
datetime.date(2024,1,31) - relativedelta(weekday=-6) :: ok :: D(2024-02-06)
datetime.date(2024,1,31) + relativedelta(weekday=-7) :: ok :: D(2024-02-05)
datetime.date(2024,1,31) - relativedelta(weekday=-7) :: ok :: D(2024-02-05)
datetime.date(2024,1,31) + relativedelta(weekday=-1,weeks=-1) :: ok :: D(2024-01-28)
datetime.date(2024,1,31) - relativedelta(weekday=-1,weeks=-1) :: ok :: D(2024-02-11)
datetime.date(2024,1,31) + relativedelta(weekday=-3,months=1) :: ok :: D(2024-03-01)
datetime.date(2024,1,31) - relativedelta(weekday=-3,months=1) :: ok :: D(2024-01-05)
datetime.date(2024,1,31) + relativedelta(leapdays=1) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) - relativedelta(leapdays=1) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) + relativedelta(leapdays=-1) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) - relativedelta(leapdays=-1) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) + relativedelta(yearday=60) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) - relativedelta(yearday=60) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) + relativedelta(yearday=1) :: ok :: D(2024-01-01)
datetime.date(2024,1,31) - relativedelta(yearday=1) :: ok :: D(2024-01-01)
datetime.date(2024,1,31) + relativedelta(yearday=366) :: ok :: D(2024-12-30)
datetime.date(2024,1,31) - relativedelta(yearday=366) :: ok :: D(2024-12-30)
datetime.date(2024,1,31) + relativedelta(nlyearday=60) :: ok :: D(2024-03-01)
datetime.date(2024,1,31) - relativedelta(nlyearday=60) :: ok :: D(2024-03-01)
datetime.date(2024,1,31) + relativedelta(nlyearday=200) :: ok :: D(2024-07-19)
datetime.date(2024,1,31) - relativedelta(nlyearday=200) :: ok :: D(2024-07-19)
datetime.date(2024,1,31) + relativedelta(months=1,days=-1) :: ok :: D(2024-02-28)
datetime.date(2024,1,31) - relativedelta(months=1,days=-1) :: ok :: D(2024-01-01)
datetime.date(2024,1,31) + relativedelta(years=1,months=-1) :: ok :: D(2024-12-31)
datetime.date(2024,1,31) - relativedelta(years=1,months=-1) :: ok :: D(2023-02-28)
datetime.date(2024,1,31) + relativedelta(day=1,months=1) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - relativedelta(day=1,months=1) :: ok :: D(2023-12-01)
datetime.date(2024,1,31) + relativedelta(day=31,months=-1) :: ok :: D(2023-12-31)
datetime.date(2024,1,31) - relativedelta(day=31,months=-1) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) + relativedelta(months=1,day=1,days=-1) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) - relativedelta(months=1,day=1,days=-1) :: ok :: D(2023-12-02)
datetime.date(2024,1,31) + relativedelta(hours=1,minutes=30) :: ok :: DT(2024-01-31 01:30:00.000000)
datetime.date(2024,1,31) - relativedelta(hours=1,minutes=30) :: ok :: DT(2024-01-30 22:30:00.000000)
datetime.date(2024,1,31) + relativedelta(days=1,hours=-25) :: ok :: DT(2024-01-30 23:00:00.000000)
datetime.date(2024,1,31) - relativedelta(days=1,hours=-25) :: ok :: DT(2024-01-31 01:00:00.000000)
datetime.date(2024,1,31) + relativedelta(weekday=0,days=1) :: ok :: D(2024-02-05)
datetime.date(2024,1,31) - relativedelta(weekday=0,days=1) :: ok :: D(2024-02-05)
datetime.date(2024,1,31) + relativedelta(weekday=6,months=1) :: ok :: D(2024-03-03)
datetime.date(2024,1,31) - relativedelta(weekday=6,months=1) :: ok :: D(2023-12-31)
datetime.date(2024,1,31) + relativedelta(leapdays=1,months=2) :: ok :: D(2024-04-01)
datetime.date(2024,1,31) - relativedelta(leapdays=1,months=2) :: ok :: D(2023-11-30)
datetime.date(2024,1,31) + relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) - relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2024,1,31) + relativedelta(days=1.5) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - relativedelta(days=1.5) :: ok :: D(2024-01-29)
datetime.date(2024,1,31) + relativedelta(hours=1.5) :: ok :: DT(2024-01-31 01:30:00.000000)
datetime.date(2024,1,31) - relativedelta(hours=1.5) :: ok :: DT(2024-01-30 22:30:00.000000)
datetime.date(2024,1,31) + relativedelta(months=1.5) :: err
datetime.date(2024,1,31) - relativedelta(months=1.5) :: err
datetime.date(2024,1,31) + relativedelta(seconds=0.5) :: ok :: DT(2024-01-31 00:00:00.500000)
datetime.date(2024,1,31) - relativedelta(seconds=0.5) :: ok :: DT(2024-01-30 23:59:59.500000)
datetime.date(2024,1,31) + datetime.timedelta(days=1) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - datetime.timedelta(days=1) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) + datetime.timedelta(days=-1) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) - datetime.timedelta(days=-1) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) + datetime.timedelta(hours=25) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - datetime.timedelta(hours=25) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) + datetime.timedelta(hours=-25) :: ok :: D(2024-01-29)
datetime.date(2024,1,31) - datetime.timedelta(hours=-25) :: ok :: D(2024-02-02)
datetime.date(2024,1,31) + datetime.timedelta(seconds=90061) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) - datetime.timedelta(seconds=90061) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) + datetime.timedelta(microseconds=-1) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) - datetime.timedelta(microseconds=-1) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) + datetime.timedelta(days=1,hours=-25) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) - datetime.timedelta(days=1,hours=-25) :: ok :: D(2024-02-01)
datetime.date(2024,1,31) + datetime.timedelta(weeks=1) :: ok :: D(2024-02-07)
datetime.date(2024,1,31) - datetime.timedelta(weeks=1) :: ok :: D(2024-01-24)
datetime.date(2024,1,31) + datetime.timedelta(milliseconds=1500) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) - datetime.timedelta(milliseconds=1500) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) + datetime.timedelta(days=0.5) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) - datetime.timedelta(days=0.5) :: ok :: D(2024-01-31)
datetime.date(2024,1,31) + datetime.timedelta(seconds=-0.5) :: ok :: D(2024-01-30)
datetime.date(2024,1,31) - datetime.timedelta(seconds=-0.5) :: ok :: D(2024-02-01)
datetime.date(2024,1,31).strftime('%Y-%m-%d') :: ok :: s:2024-01-31
datetime.date(2024,1,31).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-01-31 00:00:00
datetime.date(2024,1,31).strftime('%d/%m/%Y') :: ok :: s:31/01/2024
datetime.date(2024,1,31).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.date(2024,1,31).strftime('%j') :: ok :: s:031
datetime.date(2024,1,31).strftime('%U') :: ok :: s:04
datetime.date(2024,1,31).strftime('%W') :: ok :: s:05
datetime.date(2024,1,31).strftime('%w') :: ok :: s:3
datetime.date(2024,1,31).strftime('%a') :: ok :: s:Wed
datetime.date(2024,1,31).strftime('%A') :: ok :: s:Wednesday
datetime.date(2024,1,31).strftime('%b') :: ok :: s:Jan
datetime.date(2024,1,31).strftime('%B') :: ok :: s:January
datetime.date(2024,1,31).strftime('%p') :: ok :: s:AM
datetime.date(2024,1,31).strftime('%I') :: ok :: s:12
datetime.date(2024,1,31).strftime('%y') :: ok :: s:24
datetime.date(2024,1,31).strftime('%m') :: ok :: s:01
datetime.date(2024,1,31).strftime('%d') :: ok :: s:31
datetime.date(2024,1,31).strftime('%f') :: ok :: s:000000
datetime.date(2024,1,31).strftime('%%') :: ok :: s:%
datetime.date(2024,1,31).strftime('%Y-%j') :: ok :: s:2024-031
datetime.date(2024,1,31).strftime('%c') :: ok :: s:Wed Jan 31 00:00:00 2024
datetime.date(2024,1,31).strftime('%x') :: ok :: s:01/31/24
datetime.date(2024,1,31).strftime('%X') :: ok :: s:00:00:00
datetime.date(2024,1,31).year :: ok :: 2024
datetime.date(2024,1,31).month :: ok :: 1
datetime.date(2024,1,31).day :: ok :: 31
datetime.date(2024,1,31).toordinal() :: ok :: 738916
str(datetime.date(2024,1,31)) :: ok :: s:2024-01-31
bool(datetime.date(2024,1,31)) :: ok :: True
datetime.date(2024,2,29) + relativedelta(days=1) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - relativedelta(days=1) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) + relativedelta(days=-1) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) - relativedelta(days=-1) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) + relativedelta(days=0) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - relativedelta(days=0) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + relativedelta(days=45) :: ok :: D(2024-04-14)
datetime.date(2024,2,29) - relativedelta(days=45) :: ok :: D(2024-01-15)
datetime.date(2024,2,29) + relativedelta(days=-45) :: ok :: D(2024-01-15)
datetime.date(2024,2,29) - relativedelta(days=-45) :: ok :: D(2024-04-14)
datetime.date(2024,2,29) + relativedelta(weeks=2) :: ok :: D(2024-03-14)
datetime.date(2024,2,29) - relativedelta(weeks=2) :: ok :: D(2024-02-15)
datetime.date(2024,2,29) + relativedelta(weeks=-3) :: ok :: D(2024-02-08)
datetime.date(2024,2,29) - relativedelta(weeks=-3) :: ok :: D(2024-03-21)
datetime.date(2024,2,29) + relativedelta(months=1) :: ok :: D(2024-03-29)
datetime.date(2024,2,29) - relativedelta(months=1) :: ok :: D(2024-01-29)
datetime.date(2024,2,29) + relativedelta(months=-1) :: ok :: D(2024-01-29)
datetime.date(2024,2,29) - relativedelta(months=-1) :: ok :: D(2024-03-29)
datetime.date(2024,2,29) + relativedelta(months=13) :: ok :: D(2025-03-29)
datetime.date(2024,2,29) - relativedelta(months=13) :: ok :: D(2023-01-29)
datetime.date(2024,2,29) + relativedelta(months=-13) :: ok :: D(2023-01-29)
datetime.date(2024,2,29) - relativedelta(months=-13) :: ok :: D(2025-03-29)
datetime.date(2024,2,29) + relativedelta(months=12) :: ok :: D(2025-02-28)
datetime.date(2024,2,29) - relativedelta(months=12) :: ok :: D(2023-02-28)
datetime.date(2024,2,29) + relativedelta(years=1) :: ok :: D(2025-02-28)
datetime.date(2024,2,29) - relativedelta(years=1) :: ok :: D(2023-02-28)
datetime.date(2024,2,29) + relativedelta(years=-1) :: ok :: D(2023-02-28)
datetime.date(2024,2,29) - relativedelta(years=-1) :: ok :: D(2025-02-28)
datetime.date(2024,2,29) + relativedelta(years=100) :: ok :: D(2124-02-29)
datetime.date(2024,2,29) - relativedelta(years=100) :: ok :: D(1924-02-29)
datetime.date(2024,2,29) + relativedelta(hours=1) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.date(2024,2,29) - relativedelta(hours=1) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.date(2024,2,29) + relativedelta(hours=24) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - relativedelta(hours=24) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) + relativedelta(hours=-1) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.date(2024,2,29) - relativedelta(hours=-1) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.date(2024,2,29) + relativedelta(hours=-24) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) - relativedelta(hours=-24) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) + relativedelta(hours=48) :: ok :: D(2024-03-02)
datetime.date(2024,2,29) - relativedelta(hours=48) :: ok :: D(2024-02-27)
datetime.date(2024,2,29) + relativedelta(minutes=1) :: ok :: DT(2024-02-29 00:01:00.000000)
datetime.date(2024,2,29) - relativedelta(minutes=1) :: ok :: DT(2024-02-28 23:59:00.000000)
datetime.date(2024,2,29) + relativedelta(minutes=1440) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - relativedelta(minutes=1440) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) + relativedelta(minutes=-90) :: ok :: DT(2024-02-28 22:30:00.000000)
datetime.date(2024,2,29) - relativedelta(minutes=-90) :: ok :: DT(2024-02-29 01:30:00.000000)
datetime.date(2024,2,29) + relativedelta(seconds=1) :: ok :: DT(2024-02-29 00:00:01.000000)
datetime.date(2024,2,29) - relativedelta(seconds=1) :: ok :: DT(2024-02-28 23:59:59.000000)
datetime.date(2024,2,29) + relativedelta(seconds=86400) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - relativedelta(seconds=86400) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) + relativedelta(seconds=-3600) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.date(2024,2,29) - relativedelta(seconds=-3600) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.date(2024,2,29) + relativedelta(microseconds=1) :: ok :: DT(2024-02-29 00:00:00.000001)
datetime.date(2024,2,29) - relativedelta(microseconds=1) :: ok :: DT(2024-02-28 23:59:59.999999)
datetime.date(2024,2,29) + relativedelta(microseconds=1000000) :: ok :: DT(2024-02-29 00:00:01.000000)
datetime.date(2024,2,29) - relativedelta(microseconds=1000000) :: ok :: DT(2024-02-28 23:59:59.000000)
datetime.date(2024,2,29) + relativedelta(microseconds=-1) :: ok :: DT(2024-02-28 23:59:59.999999)
datetime.date(2024,2,29) - relativedelta(microseconds=-1) :: ok :: DT(2024-02-29 00:00:00.000001)
datetime.date(2024,2,29) + relativedelta(day=1) :: ok :: D(2024-02-01)
datetime.date(2024,2,29) - relativedelta(day=1) :: ok :: D(2024-02-01)
datetime.date(2024,2,29) + relativedelta(day=15) :: ok :: D(2024-02-15)
datetime.date(2024,2,29) - relativedelta(day=15) :: ok :: D(2024-02-15)
datetime.date(2024,2,29) + relativedelta(day=31) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - relativedelta(day=31) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + relativedelta(month=1) :: ok :: D(2024-01-29)
datetime.date(2024,2,29) - relativedelta(month=1) :: ok :: D(2024-01-29)
datetime.date(2024,2,29) + relativedelta(month=2) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - relativedelta(month=2) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + relativedelta(month=12) :: ok :: D(2024-12-29)
datetime.date(2024,2,29) - relativedelta(month=12) :: ok :: D(2024-12-29)
datetime.date(2024,2,29) + relativedelta(year=2000) :: ok :: D(2000-02-29)
datetime.date(2024,2,29) - relativedelta(year=2000) :: ok :: D(2000-02-29)
datetime.date(2024,2,29) + relativedelta(year=1999) :: ok :: D(1999-02-28)
datetime.date(2024,2,29) - relativedelta(year=1999) :: ok :: D(1999-02-28)
datetime.date(2024,2,29) + relativedelta(hour=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.date(2024,2,29) - relativedelta(hour=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.date(2024,2,29) + relativedelta(hour=5) :: ok :: DT(2024-02-29 05:00:00.000000)
datetime.date(2024,2,29) - relativedelta(hour=5) :: ok :: DT(2024-02-29 05:00:00.000000)
datetime.date(2024,2,29) + relativedelta(hour=23) :: ok :: DT(2024-02-29 23:00:00.000000)
datetime.date(2024,2,29) - relativedelta(hour=23) :: ok :: DT(2024-02-29 23:00:00.000000)
datetime.date(2024,2,29) + relativedelta(minute=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.date(2024,2,29) - relativedelta(minute=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.date(2024,2,29) + relativedelta(minute=30) :: ok :: DT(2024-02-29 00:30:00.000000)
datetime.date(2024,2,29) - relativedelta(minute=30) :: ok :: DT(2024-02-29 00:30:00.000000)
datetime.date(2024,2,29) + relativedelta(second=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.date(2024,2,29) - relativedelta(second=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.date(2024,2,29) + relativedelta(second=59) :: ok :: DT(2024-02-29 00:00:59.000000)
datetime.date(2024,2,29) - relativedelta(second=59) :: ok :: DT(2024-02-29 00:00:59.000000)
datetime.date(2024,2,29) + relativedelta(microsecond=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.date(2024,2,29) - relativedelta(microsecond=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.date(2024,2,29) + relativedelta(microsecond=500000) :: ok :: DT(2024-02-29 00:00:00.500000)
datetime.date(2024,2,29) - relativedelta(microsecond=500000) :: ok :: DT(2024-02-29 00:00:00.500000)
datetime.date(2024,2,29) + relativedelta(weekday=0) :: ok :: D(2024-03-04)
datetime.date(2024,2,29) - relativedelta(weekday=0) :: ok :: D(2024-03-04)
datetime.date(2024,2,29) + relativedelta(weekday=4) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - relativedelta(weekday=4) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) + relativedelta(weekday=6) :: ok :: D(2024-03-03)
datetime.date(2024,2,29) - relativedelta(weekday=6) :: ok :: D(2024-03-03)
datetime.date(2024,2,29) + relativedelta(weekday=-1) :: ok :: D(2024-03-03)
datetime.date(2024,2,29) - relativedelta(weekday=-1) :: ok :: D(2024-03-03)
datetime.date(2024,2,29) + relativedelta(weekday=-2) :: ok :: D(2024-03-02)
datetime.date(2024,2,29) - relativedelta(weekday=-2) :: ok :: D(2024-03-02)
datetime.date(2024,2,29) + relativedelta(weekday=-6) :: ok :: D(2024-03-05)
datetime.date(2024,2,29) - relativedelta(weekday=-6) :: ok :: D(2024-03-05)
datetime.date(2024,2,29) + relativedelta(weekday=-7) :: ok :: D(2024-03-04)
datetime.date(2024,2,29) - relativedelta(weekday=-7) :: ok :: D(2024-03-04)
datetime.date(2024,2,29) + relativedelta(weekday=-1,weeks=-1) :: ok :: D(2024-02-25)
datetime.date(2024,2,29) - relativedelta(weekday=-1,weeks=-1) :: ok :: D(2024-03-10)
datetime.date(2024,2,29) + relativedelta(weekday=-3,months=1) :: ok :: D(2024-03-29)
datetime.date(2024,2,29) - relativedelta(weekday=-3,months=1) :: ok :: D(2024-02-02)
datetime.date(2024,2,29) + relativedelta(leapdays=1) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - relativedelta(leapdays=1) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + relativedelta(leapdays=-1) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - relativedelta(leapdays=-1) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + relativedelta(yearday=60) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - relativedelta(yearday=60) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + relativedelta(yearday=1) :: ok :: D(2024-01-01)
datetime.date(2024,2,29) - relativedelta(yearday=1) :: ok :: D(2024-01-01)
datetime.date(2024,2,29) + relativedelta(yearday=366) :: ok :: D(2024-12-30)
datetime.date(2024,2,29) - relativedelta(yearday=366) :: ok :: D(2024-12-30)
datetime.date(2024,2,29) + relativedelta(nlyearday=60) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - relativedelta(nlyearday=60) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) + relativedelta(nlyearday=200) :: ok :: D(2024-07-19)
datetime.date(2024,2,29) - relativedelta(nlyearday=200) :: ok :: D(2024-07-19)
datetime.date(2024,2,29) + relativedelta(months=1,days=-1) :: ok :: D(2024-03-28)
datetime.date(2024,2,29) - relativedelta(months=1,days=-1) :: ok :: D(2024-01-30)
datetime.date(2024,2,29) + relativedelta(years=1,months=-1) :: ok :: D(2025-01-29)
datetime.date(2024,2,29) - relativedelta(years=1,months=-1) :: ok :: D(2023-03-29)
datetime.date(2024,2,29) + relativedelta(day=1,months=1) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - relativedelta(day=1,months=1) :: ok :: D(2024-01-01)
datetime.date(2024,2,29) + relativedelta(day=31,months=-1) :: ok :: D(2024-01-31)
datetime.date(2024,2,29) - relativedelta(day=31,months=-1) :: ok :: D(2024-03-31)
datetime.date(2024,2,29) + relativedelta(months=1,day=1,days=-1) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - relativedelta(months=1,day=1,days=-1) :: ok :: D(2024-01-02)
datetime.date(2024,2,29) + relativedelta(hours=1,minutes=30) :: ok :: DT(2024-02-29 01:30:00.000000)
datetime.date(2024,2,29) - relativedelta(hours=1,minutes=30) :: ok :: DT(2024-02-28 22:30:00.000000)
datetime.date(2024,2,29) + relativedelta(days=1,hours=-25) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.date(2024,2,29) - relativedelta(days=1,hours=-25) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.date(2024,2,29) + relativedelta(weekday=0,days=1) :: ok :: D(2024-03-04)
datetime.date(2024,2,29) - relativedelta(weekday=0,days=1) :: ok :: D(2024-03-04)
datetime.date(2024,2,29) + relativedelta(weekday=6,months=1) :: ok :: D(2024-03-31)
datetime.date(2024,2,29) - relativedelta(weekday=6,months=1) :: ok :: D(2024-02-04)
datetime.date(2024,2,29) + relativedelta(leapdays=1,months=2) :: ok :: D(2024-04-30)
datetime.date(2024,2,29) - relativedelta(leapdays=1,months=2) :: ok :: D(2023-12-29)
datetime.date(2024,2,29) + relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + relativedelta(days=1.5) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - relativedelta(days=1.5) :: ok :: D(2024-02-27)
datetime.date(2024,2,29) + relativedelta(hours=1.5) :: ok :: DT(2024-02-29 01:30:00.000000)
datetime.date(2024,2,29) - relativedelta(hours=1.5) :: ok :: DT(2024-02-28 22:30:00.000000)
datetime.date(2024,2,29) + relativedelta(months=1.5) :: err
datetime.date(2024,2,29) - relativedelta(months=1.5) :: err
datetime.date(2024,2,29) + relativedelta(seconds=0.5) :: ok :: DT(2024-02-29 00:00:00.500000)
datetime.date(2024,2,29) - relativedelta(seconds=0.5) :: ok :: DT(2024-02-28 23:59:59.500000)
datetime.date(2024,2,29) + datetime.timedelta(days=1) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - datetime.timedelta(days=1) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) + datetime.timedelta(days=-1) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) - datetime.timedelta(days=-1) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) + datetime.timedelta(hours=25) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - datetime.timedelta(hours=25) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) + datetime.timedelta(hours=-25) :: ok :: D(2024-02-27)
datetime.date(2024,2,29) - datetime.timedelta(hours=-25) :: ok :: D(2024-03-02)
datetime.date(2024,2,29) + datetime.timedelta(seconds=90061) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) - datetime.timedelta(seconds=90061) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) + datetime.timedelta(microseconds=-1) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) - datetime.timedelta(microseconds=-1) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) + datetime.timedelta(days=1,hours=-25) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) - datetime.timedelta(days=1,hours=-25) :: ok :: D(2024-03-01)
datetime.date(2024,2,29) + datetime.timedelta(weeks=1) :: ok :: D(2024-03-07)
datetime.date(2024,2,29) - datetime.timedelta(weeks=1) :: ok :: D(2024-02-22)
datetime.date(2024,2,29) + datetime.timedelta(milliseconds=1500) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - datetime.timedelta(milliseconds=1500) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + datetime.timedelta(days=0.5) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) - datetime.timedelta(days=0.5) :: ok :: D(2024-02-29)
datetime.date(2024,2,29) + datetime.timedelta(seconds=-0.5) :: ok :: D(2024-02-28)
datetime.date(2024,2,29) - datetime.timedelta(seconds=-0.5) :: ok :: D(2024-03-01)
datetime.date(2024,2,29).strftime('%Y-%m-%d') :: ok :: s:2024-02-29
datetime.date(2024,2,29).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-29 00:00:00
datetime.date(2024,2,29).strftime('%d/%m/%Y') :: ok :: s:29/02/2024
datetime.date(2024,2,29).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.date(2024,2,29).strftime('%j') :: ok :: s:060
datetime.date(2024,2,29).strftime('%U') :: ok :: s:08
datetime.date(2024,2,29).strftime('%W') :: ok :: s:09
datetime.date(2024,2,29).strftime('%w') :: ok :: s:4
datetime.date(2024,2,29).strftime('%a') :: ok :: s:Thu
datetime.date(2024,2,29).strftime('%A') :: ok :: s:Thursday
datetime.date(2024,2,29).strftime('%b') :: ok :: s:Feb
datetime.date(2024,2,29).strftime('%B') :: ok :: s:February
datetime.date(2024,2,29).strftime('%p') :: ok :: s:AM
datetime.date(2024,2,29).strftime('%I') :: ok :: s:12
datetime.date(2024,2,29).strftime('%y') :: ok :: s:24
datetime.date(2024,2,29).strftime('%m') :: ok :: s:02
datetime.date(2024,2,29).strftime('%d') :: ok :: s:29
datetime.date(2024,2,29).strftime('%f') :: ok :: s:000000
datetime.date(2024,2,29).strftime('%%') :: ok :: s:%
datetime.date(2024,2,29).strftime('%Y-%j') :: ok :: s:2024-060
datetime.date(2024,2,29).strftime('%c') :: ok :: s:Thu Feb 29 00:00:00 2024
datetime.date(2024,2,29).strftime('%x') :: ok :: s:02/29/24
datetime.date(2024,2,29).strftime('%X') :: ok :: s:00:00:00
datetime.date(2024,2,29).year :: ok :: 2024
datetime.date(2024,2,29).month :: ok :: 2
datetime.date(2024,2,29).day :: ok :: 29
datetime.date(2024,2,29).toordinal() :: ok :: 738945
str(datetime.date(2024,2,29)) :: ok :: s:2024-02-29
bool(datetime.date(2024,2,29)) :: ok :: True
datetime.date(2023,3,1) + relativedelta(days=1) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) - relativedelta(days=1) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) + relativedelta(days=-1) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) - relativedelta(days=-1) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) + relativedelta(days=0) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) - relativedelta(days=0) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) + relativedelta(days=45) :: ok :: D(2023-04-15)
datetime.date(2023,3,1) - relativedelta(days=45) :: ok :: D(2023-01-15)
datetime.date(2023,3,1) + relativedelta(days=-45) :: ok :: D(2023-01-15)
datetime.date(2023,3,1) - relativedelta(days=-45) :: ok :: D(2023-04-15)
datetime.date(2023,3,1) + relativedelta(weeks=2) :: ok :: D(2023-03-15)
datetime.date(2023,3,1) - relativedelta(weeks=2) :: ok :: D(2023-02-15)
datetime.date(2023,3,1) + relativedelta(weeks=-3) :: ok :: D(2023-02-08)
datetime.date(2023,3,1) - relativedelta(weeks=-3) :: ok :: D(2023-03-22)
datetime.date(2023,3,1) + relativedelta(months=1) :: ok :: D(2023-04-01)
datetime.date(2023,3,1) - relativedelta(months=1) :: ok :: D(2023-02-01)
datetime.date(2023,3,1) + relativedelta(months=-1) :: ok :: D(2023-02-01)
datetime.date(2023,3,1) - relativedelta(months=-1) :: ok :: D(2023-04-01)
datetime.date(2023,3,1) + relativedelta(months=13) :: ok :: D(2024-04-01)
datetime.date(2023,3,1) - relativedelta(months=13) :: ok :: D(2022-02-01)
datetime.date(2023,3,1) + relativedelta(months=-13) :: ok :: D(2022-02-01)
datetime.date(2023,3,1) - relativedelta(months=-13) :: ok :: D(2024-04-01)
datetime.date(2023,3,1) + relativedelta(months=12) :: ok :: D(2024-03-01)
datetime.date(2023,3,1) - relativedelta(months=12) :: ok :: D(2022-03-01)
datetime.date(2023,3,1) + relativedelta(years=1) :: ok :: D(2024-03-01)
datetime.date(2023,3,1) - relativedelta(years=1) :: ok :: D(2022-03-01)
datetime.date(2023,3,1) + relativedelta(years=-1) :: ok :: D(2022-03-01)
datetime.date(2023,3,1) - relativedelta(years=-1) :: ok :: D(2024-03-01)
datetime.date(2023,3,1) + relativedelta(years=100) :: ok :: D(2123-03-01)
datetime.date(2023,3,1) - relativedelta(years=100) :: ok :: D(1923-03-01)
datetime.date(2023,3,1) + relativedelta(hours=1) :: ok :: DT(2023-03-01 01:00:00.000000)
datetime.date(2023,3,1) - relativedelta(hours=1) :: ok :: DT(2023-02-28 23:00:00.000000)
datetime.date(2023,3,1) + relativedelta(hours=24) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) - relativedelta(hours=24) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) + relativedelta(hours=-1) :: ok :: DT(2023-02-28 23:00:00.000000)
datetime.date(2023,3,1) - relativedelta(hours=-1) :: ok :: DT(2023-03-01 01:00:00.000000)
datetime.date(2023,3,1) + relativedelta(hours=-24) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) - relativedelta(hours=-24) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) + relativedelta(hours=48) :: ok :: D(2023-03-03)
datetime.date(2023,3,1) - relativedelta(hours=48) :: ok :: D(2023-02-27)
datetime.date(2023,3,1) + relativedelta(minutes=1) :: ok :: DT(2023-03-01 00:01:00.000000)
datetime.date(2023,3,1) - relativedelta(minutes=1) :: ok :: DT(2023-02-28 23:59:00.000000)
datetime.date(2023,3,1) + relativedelta(minutes=1440) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) - relativedelta(minutes=1440) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) + relativedelta(minutes=-90) :: ok :: DT(2023-02-28 22:30:00.000000)
datetime.date(2023,3,1) - relativedelta(minutes=-90) :: ok :: DT(2023-03-01 01:30:00.000000)
datetime.date(2023,3,1) + relativedelta(seconds=1) :: ok :: DT(2023-03-01 00:00:01.000000)
datetime.date(2023,3,1) - relativedelta(seconds=1) :: ok :: DT(2023-02-28 23:59:59.000000)
datetime.date(2023,3,1) + relativedelta(seconds=86400) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) - relativedelta(seconds=86400) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) + relativedelta(seconds=-3600) :: ok :: DT(2023-02-28 23:00:00.000000)
datetime.date(2023,3,1) - relativedelta(seconds=-3600) :: ok :: DT(2023-03-01 01:00:00.000000)
datetime.date(2023,3,1) + relativedelta(microseconds=1) :: ok :: DT(2023-03-01 00:00:00.000001)
datetime.date(2023,3,1) - relativedelta(microseconds=1) :: ok :: DT(2023-02-28 23:59:59.999999)
datetime.date(2023,3,1) + relativedelta(microseconds=1000000) :: ok :: DT(2023-03-01 00:00:01.000000)
datetime.date(2023,3,1) - relativedelta(microseconds=1000000) :: ok :: DT(2023-02-28 23:59:59.000000)
datetime.date(2023,3,1) + relativedelta(microseconds=-1) :: ok :: DT(2023-02-28 23:59:59.999999)
datetime.date(2023,3,1) - relativedelta(microseconds=-1) :: ok :: DT(2023-03-01 00:00:00.000001)
datetime.date(2023,3,1) + relativedelta(day=1) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) - relativedelta(day=1) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) + relativedelta(day=15) :: ok :: D(2023-03-15)
datetime.date(2023,3,1) - relativedelta(day=15) :: ok :: D(2023-03-15)
datetime.date(2023,3,1) + relativedelta(day=31) :: ok :: D(2023-03-31)
datetime.date(2023,3,1) - relativedelta(day=31) :: ok :: D(2023-03-31)
datetime.date(2023,3,1) + relativedelta(month=1) :: ok :: D(2023-01-01)
datetime.date(2023,3,1) - relativedelta(month=1) :: ok :: D(2023-01-01)
datetime.date(2023,3,1) + relativedelta(month=2) :: ok :: D(2023-02-01)
datetime.date(2023,3,1) - relativedelta(month=2) :: ok :: D(2023-02-01)
datetime.date(2023,3,1) + relativedelta(month=12) :: ok :: D(2023-12-01)
datetime.date(2023,3,1) - relativedelta(month=12) :: ok :: D(2023-12-01)
datetime.date(2023,3,1) + relativedelta(year=2000) :: ok :: D(2000-03-01)
datetime.date(2023,3,1) - relativedelta(year=2000) :: ok :: D(2000-03-01)
datetime.date(2023,3,1) + relativedelta(year=1999) :: ok :: D(1999-03-01)
datetime.date(2023,3,1) - relativedelta(year=1999) :: ok :: D(1999-03-01)
datetime.date(2023,3,1) + relativedelta(hour=0) :: ok :: DT(2023-03-01 00:00:00.000000)
datetime.date(2023,3,1) - relativedelta(hour=0) :: ok :: DT(2023-03-01 00:00:00.000000)
datetime.date(2023,3,1) + relativedelta(hour=5) :: ok :: DT(2023-03-01 05:00:00.000000)
datetime.date(2023,3,1) - relativedelta(hour=5) :: ok :: DT(2023-03-01 05:00:00.000000)
datetime.date(2023,3,1) + relativedelta(hour=23) :: ok :: DT(2023-03-01 23:00:00.000000)
datetime.date(2023,3,1) - relativedelta(hour=23) :: ok :: DT(2023-03-01 23:00:00.000000)
datetime.date(2023,3,1) + relativedelta(minute=0) :: ok :: DT(2023-03-01 00:00:00.000000)
datetime.date(2023,3,1) - relativedelta(minute=0) :: ok :: DT(2023-03-01 00:00:00.000000)
datetime.date(2023,3,1) + relativedelta(minute=30) :: ok :: DT(2023-03-01 00:30:00.000000)
datetime.date(2023,3,1) - relativedelta(minute=30) :: ok :: DT(2023-03-01 00:30:00.000000)
datetime.date(2023,3,1) + relativedelta(second=0) :: ok :: DT(2023-03-01 00:00:00.000000)
datetime.date(2023,3,1) - relativedelta(second=0) :: ok :: DT(2023-03-01 00:00:00.000000)
datetime.date(2023,3,1) + relativedelta(second=59) :: ok :: DT(2023-03-01 00:00:59.000000)
datetime.date(2023,3,1) - relativedelta(second=59) :: ok :: DT(2023-03-01 00:00:59.000000)
datetime.date(2023,3,1) + relativedelta(microsecond=0) :: ok :: DT(2023-03-01 00:00:00.000000)
datetime.date(2023,3,1) - relativedelta(microsecond=0) :: ok :: DT(2023-03-01 00:00:00.000000)
datetime.date(2023,3,1) + relativedelta(microsecond=500000) :: ok :: DT(2023-03-01 00:00:00.500000)
datetime.date(2023,3,1) - relativedelta(microsecond=500000) :: ok :: DT(2023-03-01 00:00:00.500000)
datetime.date(2023,3,1) + relativedelta(weekday=0) :: ok :: D(2023-03-06)
datetime.date(2023,3,1) - relativedelta(weekday=0) :: ok :: D(2023-03-06)
datetime.date(2023,3,1) + relativedelta(weekday=4) :: ok :: D(2023-03-03)
datetime.date(2023,3,1) - relativedelta(weekday=4) :: ok :: D(2023-03-03)
datetime.date(2023,3,1) + relativedelta(weekday=6) :: ok :: D(2023-03-05)
datetime.date(2023,3,1) - relativedelta(weekday=6) :: ok :: D(2023-03-05)
datetime.date(2023,3,1) + relativedelta(weekday=-1) :: ok :: D(2023-03-05)
datetime.date(2023,3,1) - relativedelta(weekday=-1) :: ok :: D(2023-03-05)
datetime.date(2023,3,1) + relativedelta(weekday=-2) :: ok :: D(2023-03-04)
datetime.date(2023,3,1) - relativedelta(weekday=-2) :: ok :: D(2023-03-04)
datetime.date(2023,3,1) + relativedelta(weekday=-6) :: ok :: D(2023-03-07)
datetime.date(2023,3,1) - relativedelta(weekday=-6) :: ok :: D(2023-03-07)
datetime.date(2023,3,1) + relativedelta(weekday=-7) :: ok :: D(2023-03-06)
datetime.date(2023,3,1) - relativedelta(weekday=-7) :: ok :: D(2023-03-06)
datetime.date(2023,3,1) + relativedelta(weekday=-1,weeks=-1) :: ok :: D(2023-02-26)
datetime.date(2023,3,1) - relativedelta(weekday=-1,weeks=-1) :: ok :: D(2023-03-12)
datetime.date(2023,3,1) + relativedelta(weekday=-3,months=1) :: ok :: D(2023-04-07)
datetime.date(2023,3,1) - relativedelta(weekday=-3,months=1) :: ok :: D(2023-02-03)
datetime.date(2023,3,1) + relativedelta(leapdays=1) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) - relativedelta(leapdays=1) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) + relativedelta(leapdays=-1) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) - relativedelta(leapdays=-1) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) + relativedelta(yearday=60) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) - relativedelta(yearday=60) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) + relativedelta(yearday=1) :: ok :: D(2023-01-01)
datetime.date(2023,3,1) - relativedelta(yearday=1) :: ok :: D(2023-01-01)
datetime.date(2023,3,1) + relativedelta(yearday=366) :: ok :: D(2023-12-31)
datetime.date(2023,3,1) - relativedelta(yearday=366) :: ok :: D(2023-12-31)
datetime.date(2023,3,1) + relativedelta(nlyearday=60) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) - relativedelta(nlyearday=60) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) + relativedelta(nlyearday=200) :: ok :: D(2023-07-19)
datetime.date(2023,3,1) - relativedelta(nlyearday=200) :: ok :: D(2023-07-19)
datetime.date(2023,3,1) + relativedelta(months=1,days=-1) :: ok :: D(2023-03-31)
datetime.date(2023,3,1) - relativedelta(months=1,days=-1) :: ok :: D(2023-02-02)
datetime.date(2023,3,1) + relativedelta(years=1,months=-1) :: ok :: D(2024-02-01)
datetime.date(2023,3,1) - relativedelta(years=1,months=-1) :: ok :: D(2022-04-01)
datetime.date(2023,3,1) + relativedelta(day=1,months=1) :: ok :: D(2023-04-01)
datetime.date(2023,3,1) - relativedelta(day=1,months=1) :: ok :: D(2023-02-01)
datetime.date(2023,3,1) + relativedelta(day=31,months=-1) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) - relativedelta(day=31,months=-1) :: ok :: D(2023-04-30)
datetime.date(2023,3,1) + relativedelta(months=1,day=1,days=-1) :: ok :: D(2023-03-31)
datetime.date(2023,3,1) - relativedelta(months=1,day=1,days=-1) :: ok :: D(2023-02-02)
datetime.date(2023,3,1) + relativedelta(hours=1,minutes=30) :: ok :: DT(2023-03-01 01:30:00.000000)
datetime.date(2023,3,1) - relativedelta(hours=1,minutes=30) :: ok :: DT(2023-02-28 22:30:00.000000)
datetime.date(2023,3,1) + relativedelta(days=1,hours=-25) :: ok :: DT(2023-02-28 23:00:00.000000)
datetime.date(2023,3,1) - relativedelta(days=1,hours=-25) :: ok :: DT(2023-03-01 01:00:00.000000)
datetime.date(2023,3,1) + relativedelta(weekday=0,days=1) :: ok :: D(2023-03-06)
datetime.date(2023,3,1) - relativedelta(weekday=0,days=1) :: ok :: D(2023-03-06)
datetime.date(2023,3,1) + relativedelta(weekday=6,months=1) :: ok :: D(2023-04-02)
datetime.date(2023,3,1) - relativedelta(weekday=6,months=1) :: ok :: D(2023-02-05)
datetime.date(2023,3,1) + relativedelta(leapdays=1,months=2) :: ok :: D(2023-05-01)
datetime.date(2023,3,1) - relativedelta(leapdays=1,months=2) :: ok :: D(2023-01-01)
datetime.date(2023,3,1) + relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2023,3,1) - relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2023,3,1) + relativedelta(days=1.5) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) - relativedelta(days=1.5) :: ok :: D(2023-02-27)
datetime.date(2023,3,1) + relativedelta(hours=1.5) :: ok :: DT(2023-03-01 01:30:00.000000)
datetime.date(2023,3,1) - relativedelta(hours=1.5) :: ok :: DT(2023-02-28 22:30:00.000000)
datetime.date(2023,3,1) + relativedelta(months=1.5) :: err
datetime.date(2023,3,1) - relativedelta(months=1.5) :: err
datetime.date(2023,3,1) + relativedelta(seconds=0.5) :: ok :: DT(2023-03-01 00:00:00.500000)
datetime.date(2023,3,1) - relativedelta(seconds=0.5) :: ok :: DT(2023-02-28 23:59:59.500000)
datetime.date(2023,3,1) + datetime.timedelta(days=1) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) - datetime.timedelta(days=1) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) + datetime.timedelta(days=-1) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) - datetime.timedelta(days=-1) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) + datetime.timedelta(hours=25) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) - datetime.timedelta(hours=25) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) + datetime.timedelta(hours=-25) :: ok :: D(2023-02-27)
datetime.date(2023,3,1) - datetime.timedelta(hours=-25) :: ok :: D(2023-03-03)
datetime.date(2023,3,1) + datetime.timedelta(seconds=90061) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) - datetime.timedelta(seconds=90061) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) + datetime.timedelta(microseconds=-1) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) - datetime.timedelta(microseconds=-1) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) + datetime.timedelta(days=1,hours=-25) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) - datetime.timedelta(days=1,hours=-25) :: ok :: D(2023-03-02)
datetime.date(2023,3,1) + datetime.timedelta(weeks=1) :: ok :: D(2023-03-08)
datetime.date(2023,3,1) - datetime.timedelta(weeks=1) :: ok :: D(2023-02-22)
datetime.date(2023,3,1) + datetime.timedelta(milliseconds=1500) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) - datetime.timedelta(milliseconds=1500) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) + datetime.timedelta(days=0.5) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) - datetime.timedelta(days=0.5) :: ok :: D(2023-03-01)
datetime.date(2023,3,1) + datetime.timedelta(seconds=-0.5) :: ok :: D(2023-02-28)
datetime.date(2023,3,1) - datetime.timedelta(seconds=-0.5) :: ok :: D(2023-03-02)
datetime.date(2023,3,1).strftime('%Y-%m-%d') :: ok :: s:2023-03-01
datetime.date(2023,3,1).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2023-03-01 00:00:00
datetime.date(2023,3,1).strftime('%d/%m/%Y') :: ok :: s:01/03/2023
datetime.date(2023,3,1).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.date(2023,3,1).strftime('%j') :: ok :: s:060
datetime.date(2023,3,1).strftime('%U') :: ok :: s:09
datetime.date(2023,3,1).strftime('%W') :: ok :: s:09
datetime.date(2023,3,1).strftime('%w') :: ok :: s:3
datetime.date(2023,3,1).strftime('%a') :: ok :: s:Wed
datetime.date(2023,3,1).strftime('%A') :: ok :: s:Wednesday
datetime.date(2023,3,1).strftime('%b') :: ok :: s:Mar
datetime.date(2023,3,1).strftime('%B') :: ok :: s:March
datetime.date(2023,3,1).strftime('%p') :: ok :: s:AM
datetime.date(2023,3,1).strftime('%I') :: ok :: s:12
datetime.date(2023,3,1).strftime('%y') :: ok :: s:23
datetime.date(2023,3,1).strftime('%m') :: ok :: s:03
datetime.date(2023,3,1).strftime('%d') :: ok :: s:01
datetime.date(2023,3,1).strftime('%f') :: ok :: s:000000
datetime.date(2023,3,1).strftime('%%') :: ok :: s:%
datetime.date(2023,3,1).strftime('%Y-%j') :: ok :: s:2023-060
datetime.date(2023,3,1).strftime('%c') :: ok :: s:Wed Mar  1 00:00:00 2023
datetime.date(2023,3,1).strftime('%x') :: ok :: s:03/01/23
datetime.date(2023,3,1).strftime('%X') :: ok :: s:00:00:00
datetime.date(2023,3,1).year :: ok :: 2023
datetime.date(2023,3,1).month :: ok :: 3
datetime.date(2023,3,1).day :: ok :: 1
datetime.date(2023,3,1).toordinal() :: ok :: 738580
str(datetime.date(2023,3,1)) :: ok :: s:2023-03-01
bool(datetime.date(2023,3,1)) :: ok :: True
datetime.date(2024,12,31) + relativedelta(days=1) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - relativedelta(days=1) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + relativedelta(days=-1) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) - relativedelta(days=-1) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) + relativedelta(days=0) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) - relativedelta(days=0) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) + relativedelta(days=45) :: ok :: D(2025-02-14)
datetime.date(2024,12,31) - relativedelta(days=45) :: ok :: D(2024-11-16)
datetime.date(2024,12,31) + relativedelta(days=-45) :: ok :: D(2024-11-16)
datetime.date(2024,12,31) - relativedelta(days=-45) :: ok :: D(2025-02-14)
datetime.date(2024,12,31) + relativedelta(weeks=2) :: ok :: D(2025-01-14)
datetime.date(2024,12,31) - relativedelta(weeks=2) :: ok :: D(2024-12-17)
datetime.date(2024,12,31) + relativedelta(weeks=-3) :: ok :: D(2024-12-10)
datetime.date(2024,12,31) - relativedelta(weeks=-3) :: ok :: D(2025-01-21)
datetime.date(2024,12,31) + relativedelta(months=1) :: ok :: D(2025-01-31)
datetime.date(2024,12,31) - relativedelta(months=1) :: ok :: D(2024-11-30)
datetime.date(2024,12,31) + relativedelta(months=-1) :: ok :: D(2024-11-30)
datetime.date(2024,12,31) - relativedelta(months=-1) :: ok :: D(2025-01-31)
datetime.date(2024,12,31) + relativedelta(months=13) :: ok :: D(2026-01-31)
datetime.date(2024,12,31) - relativedelta(months=13) :: ok :: D(2023-11-30)
datetime.date(2024,12,31) + relativedelta(months=-13) :: ok :: D(2023-11-30)
datetime.date(2024,12,31) - relativedelta(months=-13) :: ok :: D(2026-01-31)
datetime.date(2024,12,31) + relativedelta(months=12) :: ok :: D(2025-12-31)
datetime.date(2024,12,31) - relativedelta(months=12) :: ok :: D(2023-12-31)
datetime.date(2024,12,31) + relativedelta(years=1) :: ok :: D(2025-12-31)
datetime.date(2024,12,31) - relativedelta(years=1) :: ok :: D(2023-12-31)
datetime.date(2024,12,31) + relativedelta(years=-1) :: ok :: D(2023-12-31)
datetime.date(2024,12,31) - relativedelta(years=-1) :: ok :: D(2025-12-31)
datetime.date(2024,12,31) + relativedelta(years=100) :: ok :: D(2124-12-31)
datetime.date(2024,12,31) - relativedelta(years=100) :: ok :: D(1924-12-31)
datetime.date(2024,12,31) + relativedelta(hours=1) :: ok :: DT(2024-12-31 01:00:00.000000)
datetime.date(2024,12,31) - relativedelta(hours=1) :: ok :: DT(2024-12-30 23:00:00.000000)
datetime.date(2024,12,31) + relativedelta(hours=24) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - relativedelta(hours=24) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + relativedelta(hours=-1) :: ok :: DT(2024-12-30 23:00:00.000000)
datetime.date(2024,12,31) - relativedelta(hours=-1) :: ok :: DT(2024-12-31 01:00:00.000000)
datetime.date(2024,12,31) + relativedelta(hours=-24) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) - relativedelta(hours=-24) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) + relativedelta(hours=48) :: ok :: D(2025-01-02)
datetime.date(2024,12,31) - relativedelta(hours=48) :: ok :: D(2024-12-29)
datetime.date(2024,12,31) + relativedelta(minutes=1) :: ok :: DT(2024-12-31 00:01:00.000000)
datetime.date(2024,12,31) - relativedelta(minutes=1) :: ok :: DT(2024-12-30 23:59:00.000000)
datetime.date(2024,12,31) + relativedelta(minutes=1440) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - relativedelta(minutes=1440) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + relativedelta(minutes=-90) :: ok :: DT(2024-12-30 22:30:00.000000)
datetime.date(2024,12,31) - relativedelta(minutes=-90) :: ok :: DT(2024-12-31 01:30:00.000000)
datetime.date(2024,12,31) + relativedelta(seconds=1) :: ok :: DT(2024-12-31 00:00:01.000000)
datetime.date(2024,12,31) - relativedelta(seconds=1) :: ok :: DT(2024-12-30 23:59:59.000000)
datetime.date(2024,12,31) + relativedelta(seconds=86400) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - relativedelta(seconds=86400) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + relativedelta(seconds=-3600) :: ok :: DT(2024-12-30 23:00:00.000000)
datetime.date(2024,12,31) - relativedelta(seconds=-3600) :: ok :: DT(2024-12-31 01:00:00.000000)
datetime.date(2024,12,31) + relativedelta(microseconds=1) :: ok :: DT(2024-12-31 00:00:00.000001)
datetime.date(2024,12,31) - relativedelta(microseconds=1) :: ok :: DT(2024-12-30 23:59:59.999999)
datetime.date(2024,12,31) + relativedelta(microseconds=1000000) :: ok :: DT(2024-12-31 00:00:01.000000)
datetime.date(2024,12,31) - relativedelta(microseconds=1000000) :: ok :: DT(2024-12-30 23:59:59.000000)
datetime.date(2024,12,31) + relativedelta(microseconds=-1) :: ok :: DT(2024-12-30 23:59:59.999999)
datetime.date(2024,12,31) - relativedelta(microseconds=-1) :: ok :: DT(2024-12-31 00:00:00.000001)
datetime.date(2024,12,31) + relativedelta(day=1) :: ok :: D(2024-12-01)
datetime.date(2024,12,31) - relativedelta(day=1) :: ok :: D(2024-12-01)
datetime.date(2024,12,31) + relativedelta(day=15) :: ok :: D(2024-12-15)
datetime.date(2024,12,31) - relativedelta(day=15) :: ok :: D(2024-12-15)
datetime.date(2024,12,31) + relativedelta(day=31) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) - relativedelta(day=31) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) + relativedelta(month=1) :: ok :: D(2024-01-31)
datetime.date(2024,12,31) - relativedelta(month=1) :: ok :: D(2024-01-31)
datetime.date(2024,12,31) + relativedelta(month=2) :: ok :: D(2024-02-29)
datetime.date(2024,12,31) - relativedelta(month=2) :: ok :: D(2024-02-29)
datetime.date(2024,12,31) + relativedelta(month=12) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) - relativedelta(month=12) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) + relativedelta(year=2000) :: ok :: D(2000-12-31)
datetime.date(2024,12,31) - relativedelta(year=2000) :: ok :: D(2000-12-31)
datetime.date(2024,12,31) + relativedelta(year=1999) :: ok :: D(1999-12-31)
datetime.date(2024,12,31) - relativedelta(year=1999) :: ok :: D(1999-12-31)
datetime.date(2024,12,31) + relativedelta(hour=0) :: ok :: DT(2024-12-31 00:00:00.000000)
datetime.date(2024,12,31) - relativedelta(hour=0) :: ok :: DT(2024-12-31 00:00:00.000000)
datetime.date(2024,12,31) + relativedelta(hour=5) :: ok :: DT(2024-12-31 05:00:00.000000)
datetime.date(2024,12,31) - relativedelta(hour=5) :: ok :: DT(2024-12-31 05:00:00.000000)
datetime.date(2024,12,31) + relativedelta(hour=23) :: ok :: DT(2024-12-31 23:00:00.000000)
datetime.date(2024,12,31) - relativedelta(hour=23) :: ok :: DT(2024-12-31 23:00:00.000000)
datetime.date(2024,12,31) + relativedelta(minute=0) :: ok :: DT(2024-12-31 00:00:00.000000)
datetime.date(2024,12,31) - relativedelta(minute=0) :: ok :: DT(2024-12-31 00:00:00.000000)
datetime.date(2024,12,31) + relativedelta(minute=30) :: ok :: DT(2024-12-31 00:30:00.000000)
datetime.date(2024,12,31) - relativedelta(minute=30) :: ok :: DT(2024-12-31 00:30:00.000000)
datetime.date(2024,12,31) + relativedelta(second=0) :: ok :: DT(2024-12-31 00:00:00.000000)
datetime.date(2024,12,31) - relativedelta(second=0) :: ok :: DT(2024-12-31 00:00:00.000000)
datetime.date(2024,12,31) + relativedelta(second=59) :: ok :: DT(2024-12-31 00:00:59.000000)
datetime.date(2024,12,31) - relativedelta(second=59) :: ok :: DT(2024-12-31 00:00:59.000000)
datetime.date(2024,12,31) + relativedelta(microsecond=0) :: ok :: DT(2024-12-31 00:00:00.000000)
datetime.date(2024,12,31) - relativedelta(microsecond=0) :: ok :: DT(2024-12-31 00:00:00.000000)
datetime.date(2024,12,31) + relativedelta(microsecond=500000) :: ok :: DT(2024-12-31 00:00:00.500000)
datetime.date(2024,12,31) - relativedelta(microsecond=500000) :: ok :: DT(2024-12-31 00:00:00.500000)
datetime.date(2024,12,31) + relativedelta(weekday=0) :: ok :: D(2025-01-06)
datetime.date(2024,12,31) - relativedelta(weekday=0) :: ok :: D(2025-01-06)
datetime.date(2024,12,31) + relativedelta(weekday=4) :: ok :: D(2025-01-03)
datetime.date(2024,12,31) - relativedelta(weekday=4) :: ok :: D(2025-01-03)
datetime.date(2024,12,31) + relativedelta(weekday=6) :: ok :: D(2025-01-05)
datetime.date(2024,12,31) - relativedelta(weekday=6) :: ok :: D(2025-01-05)
datetime.date(2024,12,31) + relativedelta(weekday=-1) :: ok :: D(2025-01-05)
datetime.date(2024,12,31) - relativedelta(weekday=-1) :: ok :: D(2025-01-05)
datetime.date(2024,12,31) + relativedelta(weekday=-2) :: ok :: D(2025-01-04)
datetime.date(2024,12,31) - relativedelta(weekday=-2) :: ok :: D(2025-01-04)
datetime.date(2024,12,31) + relativedelta(weekday=-6) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) - relativedelta(weekday=-6) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) + relativedelta(weekday=-7) :: ok :: D(2025-01-06)
datetime.date(2024,12,31) - relativedelta(weekday=-7) :: ok :: D(2025-01-06)
datetime.date(2024,12,31) + relativedelta(weekday=-1,weeks=-1) :: ok :: D(2024-12-29)
datetime.date(2024,12,31) - relativedelta(weekday=-1,weeks=-1) :: ok :: D(2025-01-12)
datetime.date(2024,12,31) + relativedelta(weekday=-3,months=1) :: ok :: D(2025-01-31)
datetime.date(2024,12,31) - relativedelta(weekday=-3,months=1) :: ok :: D(2024-12-06)
datetime.date(2024,12,31) + relativedelta(leapdays=1) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - relativedelta(leapdays=1) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) + relativedelta(leapdays=-1) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) - relativedelta(leapdays=-1) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + relativedelta(yearday=60) :: ok :: D(2024-02-29)
datetime.date(2024,12,31) - relativedelta(yearday=60) :: ok :: D(2024-02-29)
datetime.date(2024,12,31) + relativedelta(yearday=1) :: ok :: D(2024-01-01)
datetime.date(2024,12,31) - relativedelta(yearday=1) :: ok :: D(2024-01-01)
datetime.date(2024,12,31) + relativedelta(yearday=366) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) - relativedelta(yearday=366) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + relativedelta(nlyearday=60) :: ok :: D(2024-03-01)
datetime.date(2024,12,31) - relativedelta(nlyearday=60) :: ok :: D(2024-03-01)
datetime.date(2024,12,31) + relativedelta(nlyearday=200) :: ok :: D(2024-07-19)
datetime.date(2024,12,31) - relativedelta(nlyearday=200) :: ok :: D(2024-07-19)
datetime.date(2024,12,31) + relativedelta(months=1,days=-1) :: ok :: D(2025-01-30)
datetime.date(2024,12,31) - relativedelta(months=1,days=-1) :: ok :: D(2024-12-01)
datetime.date(2024,12,31) + relativedelta(years=1,months=-1) :: ok :: D(2025-11-30)
datetime.date(2024,12,31) - relativedelta(years=1,months=-1) :: ok :: D(2024-01-31)
datetime.date(2024,12,31) + relativedelta(day=1,months=1) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - relativedelta(day=1,months=1) :: ok :: D(2024-11-01)
datetime.date(2024,12,31) + relativedelta(day=31,months=-1) :: ok :: D(2024-11-30)
datetime.date(2024,12,31) - relativedelta(day=31,months=-1) :: ok :: D(2025-01-31)
datetime.date(2024,12,31) + relativedelta(months=1,day=1,days=-1) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) - relativedelta(months=1,day=1,days=-1) :: ok :: D(2024-11-02)
datetime.date(2024,12,31) + relativedelta(hours=1,minutes=30) :: ok :: DT(2024-12-31 01:30:00.000000)
datetime.date(2024,12,31) - relativedelta(hours=1,minutes=30) :: ok :: DT(2024-12-30 22:30:00.000000)
datetime.date(2024,12,31) + relativedelta(days=1,hours=-25) :: ok :: DT(2024-12-30 23:00:00.000000)
datetime.date(2024,12,31) - relativedelta(days=1,hours=-25) :: ok :: DT(2024-12-31 01:00:00.000000)
datetime.date(2024,12,31) + relativedelta(weekday=0,days=1) :: ok :: D(2025-01-06)
datetime.date(2024,12,31) - relativedelta(weekday=0,days=1) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + relativedelta(weekday=6,months=1) :: ok :: D(2025-02-02)
datetime.date(2024,12,31) - relativedelta(weekday=6,months=1) :: ok :: D(2024-12-01)
datetime.date(2024,12,31) + relativedelta(leapdays=1,months=2) :: ok :: D(2025-02-28)
datetime.date(2024,12,31) - relativedelta(leapdays=1,months=2) :: ok :: D(2024-11-01)
datetime.date(2024,12,31) + relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2024,12,31) - relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2024,12,31) + relativedelta(days=1.5) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - relativedelta(days=1.5) :: ok :: D(2024-12-29)
datetime.date(2024,12,31) + relativedelta(hours=1.5) :: ok :: DT(2024-12-31 01:30:00.000000)
datetime.date(2024,12,31) - relativedelta(hours=1.5) :: ok :: DT(2024-12-30 22:30:00.000000)
datetime.date(2024,12,31) + relativedelta(months=1.5) :: err
datetime.date(2024,12,31) - relativedelta(months=1.5) :: err
datetime.date(2024,12,31) + relativedelta(seconds=0.5) :: ok :: DT(2024-12-31 00:00:00.500000)
datetime.date(2024,12,31) - relativedelta(seconds=0.5) :: ok :: DT(2024-12-30 23:59:59.500000)
datetime.date(2024,12,31) + datetime.timedelta(days=1) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - datetime.timedelta(days=1) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + datetime.timedelta(days=-1) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) - datetime.timedelta(days=-1) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) + datetime.timedelta(hours=25) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - datetime.timedelta(hours=25) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + datetime.timedelta(hours=-25) :: ok :: D(2024-12-29)
datetime.date(2024,12,31) - datetime.timedelta(hours=-25) :: ok :: D(2025-01-02)
datetime.date(2024,12,31) + datetime.timedelta(seconds=90061) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) - datetime.timedelta(seconds=90061) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) + datetime.timedelta(microseconds=-1) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) - datetime.timedelta(microseconds=-1) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) + datetime.timedelta(days=1,hours=-25) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) - datetime.timedelta(days=1,hours=-25) :: ok :: D(2025-01-01)
datetime.date(2024,12,31) + datetime.timedelta(weeks=1) :: ok :: D(2025-01-07)
datetime.date(2024,12,31) - datetime.timedelta(weeks=1) :: ok :: D(2024-12-24)
datetime.date(2024,12,31) + datetime.timedelta(milliseconds=1500) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) - datetime.timedelta(milliseconds=1500) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) + datetime.timedelta(days=0.5) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) - datetime.timedelta(days=0.5) :: ok :: D(2024-12-31)
datetime.date(2024,12,31) + datetime.timedelta(seconds=-0.5) :: ok :: D(2024-12-30)
datetime.date(2024,12,31) - datetime.timedelta(seconds=-0.5) :: ok :: D(2025-01-01)
datetime.date(2024,12,31).strftime('%Y-%m-%d') :: ok :: s:2024-12-31
datetime.date(2024,12,31).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-12-31 00:00:00
datetime.date(2024,12,31).strftime('%d/%m/%Y') :: ok :: s:31/12/2024
datetime.date(2024,12,31).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.date(2024,12,31).strftime('%j') :: ok :: s:366
datetime.date(2024,12,31).strftime('%U') :: ok :: s:52
datetime.date(2024,12,31).strftime('%W') :: ok :: s:53
datetime.date(2024,12,31).strftime('%w') :: ok :: s:2
datetime.date(2024,12,31).strftime('%a') :: ok :: s:Tue
datetime.date(2024,12,31).strftime('%A') :: ok :: s:Tuesday
datetime.date(2024,12,31).strftime('%b') :: ok :: s:Dec
datetime.date(2024,12,31).strftime('%B') :: ok :: s:December
datetime.date(2024,12,31).strftime('%p') :: ok :: s:AM
datetime.date(2024,12,31).strftime('%I') :: ok :: s:12
datetime.date(2024,12,31).strftime('%y') :: ok :: s:24
datetime.date(2024,12,31).strftime('%m') :: ok :: s:12
datetime.date(2024,12,31).strftime('%d') :: ok :: s:31
datetime.date(2024,12,31).strftime('%f') :: ok :: s:000000
datetime.date(2024,12,31).strftime('%%') :: ok :: s:%
datetime.date(2024,12,31).strftime('%Y-%j') :: ok :: s:2024-366
datetime.date(2024,12,31).strftime('%c') :: ok :: s:Tue Dec 31 00:00:00 2024
datetime.date(2024,12,31).strftime('%x') :: ok :: s:12/31/24
datetime.date(2024,12,31).strftime('%X') :: ok :: s:00:00:00
datetime.date(2024,12,31).year :: ok :: 2024
datetime.date(2024,12,31).month :: ok :: 12
datetime.date(2024,12,31).day :: ok :: 31
datetime.date(2024,12,31).toordinal() :: ok :: 739251
str(datetime.date(2024,12,31)) :: ok :: s:2024-12-31
bool(datetime.date(2024,12,31)) :: ok :: True
datetime.date(2000,2,29) + relativedelta(days=1) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - relativedelta(days=1) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) + relativedelta(days=-1) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) - relativedelta(days=-1) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) + relativedelta(days=0) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(days=0) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + relativedelta(days=45) :: ok :: D(2000-04-14)
datetime.date(2000,2,29) - relativedelta(days=45) :: ok :: D(2000-01-15)
datetime.date(2000,2,29) + relativedelta(days=-45) :: ok :: D(2000-01-15)
datetime.date(2000,2,29) - relativedelta(days=-45) :: ok :: D(2000-04-14)
datetime.date(2000,2,29) + relativedelta(weeks=2) :: ok :: D(2000-03-14)
datetime.date(2000,2,29) - relativedelta(weeks=2) :: ok :: D(2000-02-15)
datetime.date(2000,2,29) + relativedelta(weeks=-3) :: ok :: D(2000-02-08)
datetime.date(2000,2,29) - relativedelta(weeks=-3) :: ok :: D(2000-03-21)
datetime.date(2000,2,29) + relativedelta(months=1) :: ok :: D(2000-03-29)
datetime.date(2000,2,29) - relativedelta(months=1) :: ok :: D(2000-01-29)
datetime.date(2000,2,29) + relativedelta(months=-1) :: ok :: D(2000-01-29)
datetime.date(2000,2,29) - relativedelta(months=-1) :: ok :: D(2000-03-29)
datetime.date(2000,2,29) + relativedelta(months=13) :: ok :: D(2001-03-29)
datetime.date(2000,2,29) - relativedelta(months=13) :: ok :: D(1999-01-29)
datetime.date(2000,2,29) + relativedelta(months=-13) :: ok :: D(1999-01-29)
datetime.date(2000,2,29) - relativedelta(months=-13) :: ok :: D(2001-03-29)
datetime.date(2000,2,29) + relativedelta(months=12) :: ok :: D(2001-02-28)
datetime.date(2000,2,29) - relativedelta(months=12) :: ok :: D(1999-02-28)
datetime.date(2000,2,29) + relativedelta(years=1) :: ok :: D(2001-02-28)
datetime.date(2000,2,29) - relativedelta(years=1) :: ok :: D(1999-02-28)
datetime.date(2000,2,29) + relativedelta(years=-1) :: ok :: D(1999-02-28)
datetime.date(2000,2,29) - relativedelta(years=-1) :: ok :: D(2001-02-28)
datetime.date(2000,2,29) + relativedelta(years=100) :: ok :: D(2100-02-28)
datetime.date(2000,2,29) - relativedelta(years=100) :: ok :: D(1900-02-28)
datetime.date(2000,2,29) + relativedelta(hours=1) :: ok :: DT(2000-02-29 01:00:00.000000)
datetime.date(2000,2,29) - relativedelta(hours=1) :: ok :: DT(2000-02-28 23:00:00.000000)
datetime.date(2000,2,29) + relativedelta(hours=24) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - relativedelta(hours=24) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) + relativedelta(hours=-1) :: ok :: DT(2000-02-28 23:00:00.000000)
datetime.date(2000,2,29) - relativedelta(hours=-1) :: ok :: DT(2000-02-29 01:00:00.000000)
datetime.date(2000,2,29) + relativedelta(hours=-24) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) - relativedelta(hours=-24) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) + relativedelta(hours=48) :: ok :: D(2000-03-02)
datetime.date(2000,2,29) - relativedelta(hours=48) :: ok :: D(2000-02-27)
datetime.date(2000,2,29) + relativedelta(minutes=1) :: ok :: DT(2000-02-29 00:01:00.000000)
datetime.date(2000,2,29) - relativedelta(minutes=1) :: ok :: DT(2000-02-28 23:59:00.000000)
datetime.date(2000,2,29) + relativedelta(minutes=1440) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - relativedelta(minutes=1440) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) + relativedelta(minutes=-90) :: ok :: DT(2000-02-28 22:30:00.000000)
datetime.date(2000,2,29) - relativedelta(minutes=-90) :: ok :: DT(2000-02-29 01:30:00.000000)
datetime.date(2000,2,29) + relativedelta(seconds=1) :: ok :: DT(2000-02-29 00:00:01.000000)
datetime.date(2000,2,29) - relativedelta(seconds=1) :: ok :: DT(2000-02-28 23:59:59.000000)
datetime.date(2000,2,29) + relativedelta(seconds=86400) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - relativedelta(seconds=86400) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) + relativedelta(seconds=-3600) :: ok :: DT(2000-02-28 23:00:00.000000)
datetime.date(2000,2,29) - relativedelta(seconds=-3600) :: ok :: DT(2000-02-29 01:00:00.000000)
datetime.date(2000,2,29) + relativedelta(microseconds=1) :: ok :: DT(2000-02-29 00:00:00.000001)
datetime.date(2000,2,29) - relativedelta(microseconds=1) :: ok :: DT(2000-02-28 23:59:59.999999)
datetime.date(2000,2,29) + relativedelta(microseconds=1000000) :: ok :: DT(2000-02-29 00:00:01.000000)
datetime.date(2000,2,29) - relativedelta(microseconds=1000000) :: ok :: DT(2000-02-28 23:59:59.000000)
datetime.date(2000,2,29) + relativedelta(microseconds=-1) :: ok :: DT(2000-02-28 23:59:59.999999)
datetime.date(2000,2,29) - relativedelta(microseconds=-1) :: ok :: DT(2000-02-29 00:00:00.000001)
datetime.date(2000,2,29) + relativedelta(day=1) :: ok :: D(2000-02-01)
datetime.date(2000,2,29) - relativedelta(day=1) :: ok :: D(2000-02-01)
datetime.date(2000,2,29) + relativedelta(day=15) :: ok :: D(2000-02-15)
datetime.date(2000,2,29) - relativedelta(day=15) :: ok :: D(2000-02-15)
datetime.date(2000,2,29) + relativedelta(day=31) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(day=31) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + relativedelta(month=1) :: ok :: D(2000-01-29)
datetime.date(2000,2,29) - relativedelta(month=1) :: ok :: D(2000-01-29)
datetime.date(2000,2,29) + relativedelta(month=2) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(month=2) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + relativedelta(month=12) :: ok :: D(2000-12-29)
datetime.date(2000,2,29) - relativedelta(month=12) :: ok :: D(2000-12-29)
datetime.date(2000,2,29) + relativedelta(year=2000) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(year=2000) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + relativedelta(year=1999) :: ok :: D(1999-02-28)
datetime.date(2000,2,29) - relativedelta(year=1999) :: ok :: D(1999-02-28)
datetime.date(2000,2,29) + relativedelta(hour=0) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.date(2000,2,29) - relativedelta(hour=0) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.date(2000,2,29) + relativedelta(hour=5) :: ok :: DT(2000-02-29 05:00:00.000000)
datetime.date(2000,2,29) - relativedelta(hour=5) :: ok :: DT(2000-02-29 05:00:00.000000)
datetime.date(2000,2,29) + relativedelta(hour=23) :: ok :: DT(2000-02-29 23:00:00.000000)
datetime.date(2000,2,29) - relativedelta(hour=23) :: ok :: DT(2000-02-29 23:00:00.000000)
datetime.date(2000,2,29) + relativedelta(minute=0) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.date(2000,2,29) - relativedelta(minute=0) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.date(2000,2,29) + relativedelta(minute=30) :: ok :: DT(2000-02-29 00:30:00.000000)
datetime.date(2000,2,29) - relativedelta(minute=30) :: ok :: DT(2000-02-29 00:30:00.000000)
datetime.date(2000,2,29) + relativedelta(second=0) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.date(2000,2,29) - relativedelta(second=0) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.date(2000,2,29) + relativedelta(second=59) :: ok :: DT(2000-02-29 00:00:59.000000)
datetime.date(2000,2,29) - relativedelta(second=59) :: ok :: DT(2000-02-29 00:00:59.000000)
datetime.date(2000,2,29) + relativedelta(microsecond=0) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.date(2000,2,29) - relativedelta(microsecond=0) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.date(2000,2,29) + relativedelta(microsecond=500000) :: ok :: DT(2000-02-29 00:00:00.500000)
datetime.date(2000,2,29) - relativedelta(microsecond=500000) :: ok :: DT(2000-02-29 00:00:00.500000)
datetime.date(2000,2,29) + relativedelta(weekday=0) :: ok :: D(2000-03-06)
datetime.date(2000,2,29) - relativedelta(weekday=0) :: ok :: D(2000-03-06)
datetime.date(2000,2,29) + relativedelta(weekday=4) :: ok :: D(2000-03-03)
datetime.date(2000,2,29) - relativedelta(weekday=4) :: ok :: D(2000-03-03)
datetime.date(2000,2,29) + relativedelta(weekday=6) :: ok :: D(2000-03-05)
datetime.date(2000,2,29) - relativedelta(weekday=6) :: ok :: D(2000-03-05)
datetime.date(2000,2,29) + relativedelta(weekday=-1) :: ok :: D(2000-03-05)
datetime.date(2000,2,29) - relativedelta(weekday=-1) :: ok :: D(2000-03-05)
datetime.date(2000,2,29) + relativedelta(weekday=-2) :: ok :: D(2000-03-04)
datetime.date(2000,2,29) - relativedelta(weekday=-2) :: ok :: D(2000-03-04)
datetime.date(2000,2,29) + relativedelta(weekday=-6) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(weekday=-6) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + relativedelta(weekday=-7) :: ok :: D(2000-03-06)
datetime.date(2000,2,29) - relativedelta(weekday=-7) :: ok :: D(2000-03-06)
datetime.date(2000,2,29) + relativedelta(weekday=-1,weeks=-1) :: ok :: D(2000-02-27)
datetime.date(2000,2,29) - relativedelta(weekday=-1,weeks=-1) :: ok :: D(2000-03-12)
datetime.date(2000,2,29) + relativedelta(weekday=-3,months=1) :: ok :: D(2000-03-31)
datetime.date(2000,2,29) - relativedelta(weekday=-3,months=1) :: ok :: D(2000-02-04)
datetime.date(2000,2,29) + relativedelta(leapdays=1) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(leapdays=1) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + relativedelta(leapdays=-1) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(leapdays=-1) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + relativedelta(yearday=60) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(yearday=60) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + relativedelta(yearday=1) :: ok :: D(2000-01-01)
datetime.date(2000,2,29) - relativedelta(yearday=1) :: ok :: D(2000-01-01)
datetime.date(2000,2,29) + relativedelta(yearday=366) :: ok :: D(2000-12-30)
datetime.date(2000,2,29) - relativedelta(yearday=366) :: ok :: D(2000-12-30)
datetime.date(2000,2,29) + relativedelta(nlyearday=60) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - relativedelta(nlyearday=60) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) + relativedelta(nlyearday=200) :: ok :: D(2000-07-19)
datetime.date(2000,2,29) - relativedelta(nlyearday=200) :: ok :: D(2000-07-19)
datetime.date(2000,2,29) + relativedelta(months=1,days=-1) :: ok :: D(2000-03-28)
datetime.date(2000,2,29) - relativedelta(months=1,days=-1) :: ok :: D(2000-01-30)
datetime.date(2000,2,29) + relativedelta(years=1,months=-1) :: ok :: D(2001-01-29)
datetime.date(2000,2,29) - relativedelta(years=1,months=-1) :: ok :: D(1999-03-29)
datetime.date(2000,2,29) + relativedelta(day=1,months=1) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - relativedelta(day=1,months=1) :: ok :: D(2000-01-01)
datetime.date(2000,2,29) + relativedelta(day=31,months=-1) :: ok :: D(2000-01-31)
datetime.date(2000,2,29) - relativedelta(day=31,months=-1) :: ok :: D(2000-03-31)
datetime.date(2000,2,29) + relativedelta(months=1,day=1,days=-1) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - relativedelta(months=1,day=1,days=-1) :: ok :: D(2000-01-02)
datetime.date(2000,2,29) + relativedelta(hours=1,minutes=30) :: ok :: DT(2000-02-29 01:30:00.000000)
datetime.date(2000,2,29) - relativedelta(hours=1,minutes=30) :: ok :: DT(2000-02-28 22:30:00.000000)
datetime.date(2000,2,29) + relativedelta(days=1,hours=-25) :: ok :: DT(2000-02-28 23:00:00.000000)
datetime.date(2000,2,29) - relativedelta(days=1,hours=-25) :: ok :: DT(2000-02-29 01:00:00.000000)
datetime.date(2000,2,29) + relativedelta(weekday=0,days=1) :: ok :: D(2000-03-06)
datetime.date(2000,2,29) - relativedelta(weekday=0,days=1) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) + relativedelta(weekday=6,months=1) :: ok :: D(2000-04-02)
datetime.date(2000,2,29) - relativedelta(weekday=6,months=1) :: ok :: D(2000-01-30)
datetime.date(2000,2,29) + relativedelta(leapdays=1,months=2) :: ok :: D(2000-04-30)
datetime.date(2000,2,29) - relativedelta(leapdays=1,months=2) :: ok :: D(1999-12-29)
datetime.date(2000,2,29) + relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2000,2,29) - relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2000,2,29) + relativedelta(days=1.5) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - relativedelta(days=1.5) :: ok :: D(2000-02-27)
datetime.date(2000,2,29) + relativedelta(hours=1.5) :: ok :: DT(2000-02-29 01:30:00.000000)
datetime.date(2000,2,29) - relativedelta(hours=1.5) :: ok :: DT(2000-02-28 22:30:00.000000)
datetime.date(2000,2,29) + relativedelta(months=1.5) :: err
datetime.date(2000,2,29) - relativedelta(months=1.5) :: err
datetime.date(2000,2,29) + relativedelta(seconds=0.5) :: ok :: DT(2000-02-29 00:00:00.500000)
datetime.date(2000,2,29) - relativedelta(seconds=0.5) :: ok :: DT(2000-02-28 23:59:59.500000)
datetime.date(2000,2,29) + datetime.timedelta(days=1) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - datetime.timedelta(days=1) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) + datetime.timedelta(days=-1) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) - datetime.timedelta(days=-1) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) + datetime.timedelta(hours=25) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - datetime.timedelta(hours=25) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) + datetime.timedelta(hours=-25) :: ok :: D(2000-02-27)
datetime.date(2000,2,29) - datetime.timedelta(hours=-25) :: ok :: D(2000-03-02)
datetime.date(2000,2,29) + datetime.timedelta(seconds=90061) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) - datetime.timedelta(seconds=90061) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) + datetime.timedelta(microseconds=-1) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) - datetime.timedelta(microseconds=-1) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) + datetime.timedelta(days=1,hours=-25) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) - datetime.timedelta(days=1,hours=-25) :: ok :: D(2000-03-01)
datetime.date(2000,2,29) + datetime.timedelta(weeks=1) :: ok :: D(2000-03-07)
datetime.date(2000,2,29) - datetime.timedelta(weeks=1) :: ok :: D(2000-02-22)
datetime.date(2000,2,29) + datetime.timedelta(milliseconds=1500) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - datetime.timedelta(milliseconds=1500) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + datetime.timedelta(days=0.5) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) - datetime.timedelta(days=0.5) :: ok :: D(2000-02-29)
datetime.date(2000,2,29) + datetime.timedelta(seconds=-0.5) :: ok :: D(2000-02-28)
datetime.date(2000,2,29) - datetime.timedelta(seconds=-0.5) :: ok :: D(2000-03-01)
datetime.date(2000,2,29).strftime('%Y-%m-%d') :: ok :: s:2000-02-29
datetime.date(2000,2,29).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2000-02-29 00:00:00
datetime.date(2000,2,29).strftime('%d/%m/%Y') :: ok :: s:29/02/2000
datetime.date(2000,2,29).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.date(2000,2,29).strftime('%j') :: ok :: s:060
datetime.date(2000,2,29).strftime('%U') :: ok :: s:09
datetime.date(2000,2,29).strftime('%W') :: ok :: s:09
datetime.date(2000,2,29).strftime('%w') :: ok :: s:2
datetime.date(2000,2,29).strftime('%a') :: ok :: s:Tue
datetime.date(2000,2,29).strftime('%A') :: ok :: s:Tuesday
datetime.date(2000,2,29).strftime('%b') :: ok :: s:Feb
datetime.date(2000,2,29).strftime('%B') :: ok :: s:February
datetime.date(2000,2,29).strftime('%p') :: ok :: s:AM
datetime.date(2000,2,29).strftime('%I') :: ok :: s:12
datetime.date(2000,2,29).strftime('%y') :: ok :: s:00
datetime.date(2000,2,29).strftime('%m') :: ok :: s:02
datetime.date(2000,2,29).strftime('%d') :: ok :: s:29
datetime.date(2000,2,29).strftime('%f') :: ok :: s:000000
datetime.date(2000,2,29).strftime('%%') :: ok :: s:%
datetime.date(2000,2,29).strftime('%Y-%j') :: ok :: s:2000-060
datetime.date(2000,2,29).strftime('%c') :: ok :: s:Tue Feb 29 00:00:00 2000
datetime.date(2000,2,29).strftime('%x') :: ok :: s:02/29/00
datetime.date(2000,2,29).strftime('%X') :: ok :: s:00:00:00
datetime.date(2000,2,29).year :: ok :: 2000
datetime.date(2000,2,29).month :: ok :: 2
datetime.date(2000,2,29).day :: ok :: 29
datetime.date(2000,2,29).toordinal() :: ok :: 730179
str(datetime.date(2000,2,29)) :: ok :: s:2000-02-29
bool(datetime.date(2000,2,29)) :: ok :: True
datetime.date(2024,3,31) + relativedelta(days=1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(days=1) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) + relativedelta(days=-1) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) - relativedelta(days=-1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + relativedelta(days=0) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) - relativedelta(days=0) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) + relativedelta(days=45) :: ok :: D(2024-05-15)
datetime.date(2024,3,31) - relativedelta(days=45) :: ok :: D(2024-02-15)
datetime.date(2024,3,31) + relativedelta(days=-45) :: ok :: D(2024-02-15)
datetime.date(2024,3,31) - relativedelta(days=-45) :: ok :: D(2024-05-15)
datetime.date(2024,3,31) + relativedelta(weeks=2) :: ok :: D(2024-04-14)
datetime.date(2024,3,31) - relativedelta(weeks=2) :: ok :: D(2024-03-17)
datetime.date(2024,3,31) + relativedelta(weeks=-3) :: ok :: D(2024-03-10)
datetime.date(2024,3,31) - relativedelta(weeks=-3) :: ok :: D(2024-04-21)
datetime.date(2024,3,31) + relativedelta(months=1) :: ok :: D(2024-04-30)
datetime.date(2024,3,31) - relativedelta(months=1) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) + relativedelta(months=-1) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) - relativedelta(months=-1) :: ok :: D(2024-04-30)
datetime.date(2024,3,31) + relativedelta(months=13) :: ok :: D(2025-04-30)
datetime.date(2024,3,31) - relativedelta(months=13) :: ok :: D(2023-02-28)
datetime.date(2024,3,31) + relativedelta(months=-13) :: ok :: D(2023-02-28)
datetime.date(2024,3,31) - relativedelta(months=-13) :: ok :: D(2025-04-30)
datetime.date(2024,3,31) + relativedelta(months=12) :: ok :: D(2025-03-31)
datetime.date(2024,3,31) - relativedelta(months=12) :: ok :: D(2023-03-31)
datetime.date(2024,3,31) + relativedelta(years=1) :: ok :: D(2025-03-31)
datetime.date(2024,3,31) - relativedelta(years=1) :: ok :: D(2023-03-31)
datetime.date(2024,3,31) + relativedelta(years=-1) :: ok :: D(2023-03-31)
datetime.date(2024,3,31) - relativedelta(years=-1) :: ok :: D(2025-03-31)
datetime.date(2024,3,31) + relativedelta(years=100) :: ok :: D(2124-03-31)
datetime.date(2024,3,31) - relativedelta(years=100) :: ok :: D(1924-03-31)
datetime.date(2024,3,31) + relativedelta(hours=1) :: ok :: DT(2024-03-31 01:00:00.000000)
datetime.date(2024,3,31) - relativedelta(hours=1) :: ok :: DT(2024-03-30 23:00:00.000000)
datetime.date(2024,3,31) + relativedelta(hours=24) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(hours=24) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) + relativedelta(hours=-1) :: ok :: DT(2024-03-30 23:00:00.000000)
datetime.date(2024,3,31) - relativedelta(hours=-1) :: ok :: DT(2024-03-31 01:00:00.000000)
datetime.date(2024,3,31) + relativedelta(hours=-24) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) - relativedelta(hours=-24) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + relativedelta(hours=48) :: ok :: D(2024-04-02)
datetime.date(2024,3,31) - relativedelta(hours=48) :: ok :: D(2024-03-29)
datetime.date(2024,3,31) + relativedelta(minutes=1) :: ok :: DT(2024-03-31 00:01:00.000000)
datetime.date(2024,3,31) - relativedelta(minutes=1) :: ok :: DT(2024-03-30 23:59:00.000000)
datetime.date(2024,3,31) + relativedelta(minutes=1440) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(minutes=1440) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) + relativedelta(minutes=-90) :: ok :: DT(2024-03-30 22:30:00.000000)
datetime.date(2024,3,31) - relativedelta(minutes=-90) :: ok :: DT(2024-03-31 01:30:00.000000)
datetime.date(2024,3,31) + relativedelta(seconds=1) :: ok :: DT(2024-03-31 00:00:01.000000)
datetime.date(2024,3,31) - relativedelta(seconds=1) :: ok :: DT(2024-03-30 23:59:59.000000)
datetime.date(2024,3,31) + relativedelta(seconds=86400) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(seconds=86400) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) + relativedelta(seconds=-3600) :: ok :: DT(2024-03-30 23:00:00.000000)
datetime.date(2024,3,31) - relativedelta(seconds=-3600) :: ok :: DT(2024-03-31 01:00:00.000000)
datetime.date(2024,3,31) + relativedelta(microseconds=1) :: ok :: DT(2024-03-31 00:00:00.000001)
datetime.date(2024,3,31) - relativedelta(microseconds=1) :: ok :: DT(2024-03-30 23:59:59.999999)
datetime.date(2024,3,31) + relativedelta(microseconds=1000000) :: ok :: DT(2024-03-31 00:00:01.000000)
datetime.date(2024,3,31) - relativedelta(microseconds=1000000) :: ok :: DT(2024-03-30 23:59:59.000000)
datetime.date(2024,3,31) + relativedelta(microseconds=-1) :: ok :: DT(2024-03-30 23:59:59.999999)
datetime.date(2024,3,31) - relativedelta(microseconds=-1) :: ok :: DT(2024-03-31 00:00:00.000001)
datetime.date(2024,3,31) + relativedelta(day=1) :: ok :: D(2024-03-01)
datetime.date(2024,3,31) - relativedelta(day=1) :: ok :: D(2024-03-01)
datetime.date(2024,3,31) + relativedelta(day=15) :: ok :: D(2024-03-15)
datetime.date(2024,3,31) - relativedelta(day=15) :: ok :: D(2024-03-15)
datetime.date(2024,3,31) + relativedelta(day=31) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) - relativedelta(day=31) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) + relativedelta(month=1) :: ok :: D(2024-01-31)
datetime.date(2024,3,31) - relativedelta(month=1) :: ok :: D(2024-01-31)
datetime.date(2024,3,31) + relativedelta(month=2) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) - relativedelta(month=2) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) + relativedelta(month=12) :: ok :: D(2024-12-31)
datetime.date(2024,3,31) - relativedelta(month=12) :: ok :: D(2024-12-31)
datetime.date(2024,3,31) + relativedelta(year=2000) :: ok :: D(2000-03-31)
datetime.date(2024,3,31) - relativedelta(year=2000) :: ok :: D(2000-03-31)
datetime.date(2024,3,31) + relativedelta(year=1999) :: ok :: D(1999-03-31)
datetime.date(2024,3,31) - relativedelta(year=1999) :: ok :: D(1999-03-31)
datetime.date(2024,3,31) + relativedelta(hour=0) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.date(2024,3,31) - relativedelta(hour=0) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.date(2024,3,31) + relativedelta(hour=5) :: ok :: DT(2024-03-31 05:00:00.000000)
datetime.date(2024,3,31) - relativedelta(hour=5) :: ok :: DT(2024-03-31 05:00:00.000000)
datetime.date(2024,3,31) + relativedelta(hour=23) :: ok :: DT(2024-03-31 23:00:00.000000)
datetime.date(2024,3,31) - relativedelta(hour=23) :: ok :: DT(2024-03-31 23:00:00.000000)
datetime.date(2024,3,31) + relativedelta(minute=0) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.date(2024,3,31) - relativedelta(minute=0) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.date(2024,3,31) + relativedelta(minute=30) :: ok :: DT(2024-03-31 00:30:00.000000)
datetime.date(2024,3,31) - relativedelta(minute=30) :: ok :: DT(2024-03-31 00:30:00.000000)
datetime.date(2024,3,31) + relativedelta(second=0) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.date(2024,3,31) - relativedelta(second=0) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.date(2024,3,31) + relativedelta(second=59) :: ok :: DT(2024-03-31 00:00:59.000000)
datetime.date(2024,3,31) - relativedelta(second=59) :: ok :: DT(2024-03-31 00:00:59.000000)
datetime.date(2024,3,31) + relativedelta(microsecond=0) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.date(2024,3,31) - relativedelta(microsecond=0) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.date(2024,3,31) + relativedelta(microsecond=500000) :: ok :: DT(2024-03-31 00:00:00.500000)
datetime.date(2024,3,31) - relativedelta(microsecond=500000) :: ok :: DT(2024-03-31 00:00:00.500000)
datetime.date(2024,3,31) + relativedelta(weekday=0) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(weekday=0) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + relativedelta(weekday=4) :: ok :: D(2024-04-05)
datetime.date(2024,3,31) - relativedelta(weekday=4) :: ok :: D(2024-04-05)
datetime.date(2024,3,31) + relativedelta(weekday=6) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) - relativedelta(weekday=6) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) + relativedelta(weekday=-1) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) - relativedelta(weekday=-1) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) + relativedelta(weekday=-2) :: ok :: D(2024-04-06)
datetime.date(2024,3,31) - relativedelta(weekday=-2) :: ok :: D(2024-04-06)
datetime.date(2024,3,31) + relativedelta(weekday=-6) :: ok :: D(2024-04-02)
datetime.date(2024,3,31) - relativedelta(weekday=-6) :: ok :: D(2024-04-02)
datetime.date(2024,3,31) + relativedelta(weekday=-7) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(weekday=-7) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + relativedelta(weekday=-1,weeks=-1) :: ok :: D(2024-03-24)
datetime.date(2024,3,31) - relativedelta(weekday=-1,weeks=-1) :: ok :: D(2024-04-07)
datetime.date(2024,3,31) + relativedelta(weekday=-3,months=1) :: ok :: D(2024-05-03)
datetime.date(2024,3,31) - relativedelta(weekday=-3,months=1) :: ok :: D(2024-03-01)
datetime.date(2024,3,31) + relativedelta(leapdays=1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(leapdays=1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + relativedelta(leapdays=-1) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) - relativedelta(leapdays=-1) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) + relativedelta(yearday=60) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) - relativedelta(yearday=60) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) + relativedelta(yearday=1) :: ok :: D(2024-01-01)
datetime.date(2024,3,31) - relativedelta(yearday=1) :: ok :: D(2024-01-01)
datetime.date(2024,3,31) + relativedelta(yearday=366) :: ok :: D(2024-12-30)
datetime.date(2024,3,31) - relativedelta(yearday=366) :: ok :: D(2024-12-30)
datetime.date(2024,3,31) + relativedelta(nlyearday=60) :: ok :: D(2024-03-01)
datetime.date(2024,3,31) - relativedelta(nlyearday=60) :: ok :: D(2024-03-01)
datetime.date(2024,3,31) + relativedelta(nlyearday=200) :: ok :: D(2024-07-19)
datetime.date(2024,3,31) - relativedelta(nlyearday=200) :: ok :: D(2024-07-19)
datetime.date(2024,3,31) + relativedelta(months=1,days=-1) :: ok :: D(2024-04-29)
datetime.date(2024,3,31) - relativedelta(months=1,days=-1) :: ok :: D(2024-03-01)
datetime.date(2024,3,31) + relativedelta(years=1,months=-1) :: ok :: D(2025-02-28)
datetime.date(2024,3,31) - relativedelta(years=1,months=-1) :: ok :: D(2023-04-30)
datetime.date(2024,3,31) + relativedelta(day=1,months=1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(day=1,months=1) :: ok :: D(2024-02-01)
datetime.date(2024,3,31) + relativedelta(day=31,months=-1) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) - relativedelta(day=31,months=-1) :: ok :: D(2024-04-30)
datetime.date(2024,3,31) + relativedelta(months=1,day=1,days=-1) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) - relativedelta(months=1,day=1,days=-1) :: ok :: D(2024-02-02)
datetime.date(2024,3,31) + relativedelta(hours=1,minutes=30) :: ok :: DT(2024-03-31 01:30:00.000000)
datetime.date(2024,3,31) - relativedelta(hours=1,minutes=30) :: ok :: DT(2024-03-30 22:30:00.000000)
datetime.date(2024,3,31) + relativedelta(days=1,hours=-25) :: ok :: DT(2024-03-30 23:00:00.000000)
datetime.date(2024,3,31) - relativedelta(days=1,hours=-25) :: ok :: DT(2024-03-31 01:00:00.000000)
datetime.date(2024,3,31) + relativedelta(weekday=0,days=1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(weekday=0,days=1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + relativedelta(weekday=6,months=1) :: ok :: D(2024-05-05)
datetime.date(2024,3,31) - relativedelta(weekday=6,months=1) :: ok :: D(2024-03-03)
datetime.date(2024,3,31) + relativedelta(leapdays=1,months=2) :: ok :: D(2024-06-01)
datetime.date(2024,3,31) - relativedelta(leapdays=1,months=2) :: ok :: D(2024-01-31)
datetime.date(2024,3,31) + relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) - relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2024,3,31) + relativedelta(days=1.5) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - relativedelta(days=1.5) :: ok :: D(2024-03-29)
datetime.date(2024,3,31) + relativedelta(hours=1.5) :: ok :: DT(2024-03-31 01:30:00.000000)
datetime.date(2024,3,31) - relativedelta(hours=1.5) :: ok :: DT(2024-03-30 22:30:00.000000)
datetime.date(2024,3,31) + relativedelta(months=1.5) :: err
datetime.date(2024,3,31) - relativedelta(months=1.5) :: err
datetime.date(2024,3,31) + relativedelta(seconds=0.5) :: ok :: DT(2024-03-31 00:00:00.500000)
datetime.date(2024,3,31) - relativedelta(seconds=0.5) :: ok :: DT(2024-03-30 23:59:59.500000)
datetime.date(2024,3,31) + datetime.timedelta(days=1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - datetime.timedelta(days=1) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) + datetime.timedelta(days=-1) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) - datetime.timedelta(days=-1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + datetime.timedelta(hours=25) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - datetime.timedelta(hours=25) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) + datetime.timedelta(hours=-25) :: ok :: D(2024-03-29)
datetime.date(2024,3,31) - datetime.timedelta(hours=-25) :: ok :: D(2024-04-02)
datetime.date(2024,3,31) + datetime.timedelta(seconds=90061) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) - datetime.timedelta(seconds=90061) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) + datetime.timedelta(microseconds=-1) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) - datetime.timedelta(microseconds=-1) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + datetime.timedelta(days=1,hours=-25) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) - datetime.timedelta(days=1,hours=-25) :: ok :: D(2024-04-01)
datetime.date(2024,3,31) + datetime.timedelta(weeks=1) :: ok :: D(2024-04-07)
datetime.date(2024,3,31) - datetime.timedelta(weeks=1) :: ok :: D(2024-03-24)
datetime.date(2024,3,31) + datetime.timedelta(milliseconds=1500) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) - datetime.timedelta(milliseconds=1500) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) + datetime.timedelta(days=0.5) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) - datetime.timedelta(days=0.5) :: ok :: D(2024-03-31)
datetime.date(2024,3,31) + datetime.timedelta(seconds=-0.5) :: ok :: D(2024-03-30)
datetime.date(2024,3,31) - datetime.timedelta(seconds=-0.5) :: ok :: D(2024-04-01)
datetime.date(2024,3,31).strftime('%Y-%m-%d') :: ok :: s:2024-03-31
datetime.date(2024,3,31).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-31 00:00:00
datetime.date(2024,3,31).strftime('%d/%m/%Y') :: ok :: s:31/03/2024
datetime.date(2024,3,31).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.date(2024,3,31).strftime('%j') :: ok :: s:091
datetime.date(2024,3,31).strftime('%U') :: ok :: s:13
datetime.date(2024,3,31).strftime('%W') :: ok :: s:13
datetime.date(2024,3,31).strftime('%w') :: ok :: s:0
datetime.date(2024,3,31).strftime('%a') :: ok :: s:Sun
datetime.date(2024,3,31).strftime('%A') :: ok :: s:Sunday
datetime.date(2024,3,31).strftime('%b') :: ok :: s:Mar
datetime.date(2024,3,31).strftime('%B') :: ok :: s:March
datetime.date(2024,3,31).strftime('%p') :: ok :: s:AM
datetime.date(2024,3,31).strftime('%I') :: ok :: s:12
datetime.date(2024,3,31).strftime('%y') :: ok :: s:24
datetime.date(2024,3,31).strftime('%m') :: ok :: s:03
datetime.date(2024,3,31).strftime('%d') :: ok :: s:31
datetime.date(2024,3,31).strftime('%f') :: ok :: s:000000
datetime.date(2024,3,31).strftime('%%') :: ok :: s:%
datetime.date(2024,3,31).strftime('%Y-%j') :: ok :: s:2024-091
datetime.date(2024,3,31).strftime('%c') :: ok :: s:Sun Mar 31 00:00:00 2024
datetime.date(2024,3,31).strftime('%x') :: ok :: s:03/31/24
datetime.date(2024,3,31).strftime('%X') :: ok :: s:00:00:00
datetime.date(2024,3,31).year :: ok :: 2024
datetime.date(2024,3,31).month :: ok :: 3
datetime.date(2024,3,31).day :: ok :: 31
datetime.date(2024,3,31).toordinal() :: ok :: 738976
str(datetime.date(2024,3,31)) :: ok :: s:2024-03-31
bool(datetime.date(2024,3,31)) :: ok :: True
datetime.date(2021,5,17) + relativedelta(days=1) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - relativedelta(days=1) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) + relativedelta(days=-1) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) - relativedelta(days=-1) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) + relativedelta(days=0) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) - relativedelta(days=0) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) + relativedelta(days=45) :: ok :: D(2021-07-01)
datetime.date(2021,5,17) - relativedelta(days=45) :: ok :: D(2021-04-02)
datetime.date(2021,5,17) + relativedelta(days=-45) :: ok :: D(2021-04-02)
datetime.date(2021,5,17) - relativedelta(days=-45) :: ok :: D(2021-07-01)
datetime.date(2021,5,17) + relativedelta(weeks=2) :: ok :: D(2021-05-31)
datetime.date(2021,5,17) - relativedelta(weeks=2) :: ok :: D(2021-05-03)
datetime.date(2021,5,17) + relativedelta(weeks=-3) :: ok :: D(2021-04-26)
datetime.date(2021,5,17) - relativedelta(weeks=-3) :: ok :: D(2021-06-07)
datetime.date(2021,5,17) + relativedelta(months=1) :: ok :: D(2021-06-17)
datetime.date(2021,5,17) - relativedelta(months=1) :: ok :: D(2021-04-17)
datetime.date(2021,5,17) + relativedelta(months=-1) :: ok :: D(2021-04-17)
datetime.date(2021,5,17) - relativedelta(months=-1) :: ok :: D(2021-06-17)
datetime.date(2021,5,17) + relativedelta(months=13) :: ok :: D(2022-06-17)
datetime.date(2021,5,17) - relativedelta(months=13) :: ok :: D(2020-04-17)
datetime.date(2021,5,17) + relativedelta(months=-13) :: ok :: D(2020-04-17)
datetime.date(2021,5,17) - relativedelta(months=-13) :: ok :: D(2022-06-17)
datetime.date(2021,5,17) + relativedelta(months=12) :: ok :: D(2022-05-17)
datetime.date(2021,5,17) - relativedelta(months=12) :: ok :: D(2020-05-17)
datetime.date(2021,5,17) + relativedelta(years=1) :: ok :: D(2022-05-17)
datetime.date(2021,5,17) - relativedelta(years=1) :: ok :: D(2020-05-17)
datetime.date(2021,5,17) + relativedelta(years=-1) :: ok :: D(2020-05-17)
datetime.date(2021,5,17) - relativedelta(years=-1) :: ok :: D(2022-05-17)
datetime.date(2021,5,17) + relativedelta(years=100) :: ok :: D(2121-05-17)
datetime.date(2021,5,17) - relativedelta(years=100) :: ok :: D(1921-05-17)
datetime.date(2021,5,17) + relativedelta(hours=1) :: ok :: DT(2021-05-17 01:00:00.000000)
datetime.date(2021,5,17) - relativedelta(hours=1) :: ok :: DT(2021-05-16 23:00:00.000000)
datetime.date(2021,5,17) + relativedelta(hours=24) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - relativedelta(hours=24) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) + relativedelta(hours=-1) :: ok :: DT(2021-05-16 23:00:00.000000)
datetime.date(2021,5,17) - relativedelta(hours=-1) :: ok :: DT(2021-05-17 01:00:00.000000)
datetime.date(2021,5,17) + relativedelta(hours=-24) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) - relativedelta(hours=-24) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) + relativedelta(hours=48) :: ok :: D(2021-05-19)
datetime.date(2021,5,17) - relativedelta(hours=48) :: ok :: D(2021-05-15)
datetime.date(2021,5,17) + relativedelta(minutes=1) :: ok :: DT(2021-05-17 00:01:00.000000)
datetime.date(2021,5,17) - relativedelta(minutes=1) :: ok :: DT(2021-05-16 23:59:00.000000)
datetime.date(2021,5,17) + relativedelta(minutes=1440) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - relativedelta(minutes=1440) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) + relativedelta(minutes=-90) :: ok :: DT(2021-05-16 22:30:00.000000)
datetime.date(2021,5,17) - relativedelta(minutes=-90) :: ok :: DT(2021-05-17 01:30:00.000000)
datetime.date(2021,5,17) + relativedelta(seconds=1) :: ok :: DT(2021-05-17 00:00:01.000000)
datetime.date(2021,5,17) - relativedelta(seconds=1) :: ok :: DT(2021-05-16 23:59:59.000000)
datetime.date(2021,5,17) + relativedelta(seconds=86400) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - relativedelta(seconds=86400) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) + relativedelta(seconds=-3600) :: ok :: DT(2021-05-16 23:00:00.000000)
datetime.date(2021,5,17) - relativedelta(seconds=-3600) :: ok :: DT(2021-05-17 01:00:00.000000)
datetime.date(2021,5,17) + relativedelta(microseconds=1) :: ok :: DT(2021-05-17 00:00:00.000001)
datetime.date(2021,5,17) - relativedelta(microseconds=1) :: ok :: DT(2021-05-16 23:59:59.999999)
datetime.date(2021,5,17) + relativedelta(microseconds=1000000) :: ok :: DT(2021-05-17 00:00:01.000000)
datetime.date(2021,5,17) - relativedelta(microseconds=1000000) :: ok :: DT(2021-05-16 23:59:59.000000)
datetime.date(2021,5,17) + relativedelta(microseconds=-1) :: ok :: DT(2021-05-16 23:59:59.999999)
datetime.date(2021,5,17) - relativedelta(microseconds=-1) :: ok :: DT(2021-05-17 00:00:00.000001)
datetime.date(2021,5,17) + relativedelta(day=1) :: ok :: D(2021-05-01)
datetime.date(2021,5,17) - relativedelta(day=1) :: ok :: D(2021-05-01)
datetime.date(2021,5,17) + relativedelta(day=15) :: ok :: D(2021-05-15)
datetime.date(2021,5,17) - relativedelta(day=15) :: ok :: D(2021-05-15)
datetime.date(2021,5,17) + relativedelta(day=31) :: ok :: D(2021-05-31)
datetime.date(2021,5,17) - relativedelta(day=31) :: ok :: D(2021-05-31)
datetime.date(2021,5,17) + relativedelta(month=1) :: ok :: D(2021-01-17)
datetime.date(2021,5,17) - relativedelta(month=1) :: ok :: D(2021-01-17)
datetime.date(2021,5,17) + relativedelta(month=2) :: ok :: D(2021-02-17)
datetime.date(2021,5,17) - relativedelta(month=2) :: ok :: D(2021-02-17)
datetime.date(2021,5,17) + relativedelta(month=12) :: ok :: D(2021-12-17)
datetime.date(2021,5,17) - relativedelta(month=12) :: ok :: D(2021-12-17)
datetime.date(2021,5,17) + relativedelta(year=2000) :: ok :: D(2000-05-17)
datetime.date(2021,5,17) - relativedelta(year=2000) :: ok :: D(2000-05-17)
datetime.date(2021,5,17) + relativedelta(year=1999) :: ok :: D(1999-05-17)
datetime.date(2021,5,17) - relativedelta(year=1999) :: ok :: D(1999-05-17)
datetime.date(2021,5,17) + relativedelta(hour=0) :: ok :: DT(2021-05-17 00:00:00.000000)
datetime.date(2021,5,17) - relativedelta(hour=0) :: ok :: DT(2021-05-17 00:00:00.000000)
datetime.date(2021,5,17) + relativedelta(hour=5) :: ok :: DT(2021-05-17 05:00:00.000000)
datetime.date(2021,5,17) - relativedelta(hour=5) :: ok :: DT(2021-05-17 05:00:00.000000)
datetime.date(2021,5,17) + relativedelta(hour=23) :: ok :: DT(2021-05-17 23:00:00.000000)
datetime.date(2021,5,17) - relativedelta(hour=23) :: ok :: DT(2021-05-17 23:00:00.000000)
datetime.date(2021,5,17) + relativedelta(minute=0) :: ok :: DT(2021-05-17 00:00:00.000000)
datetime.date(2021,5,17) - relativedelta(minute=0) :: ok :: DT(2021-05-17 00:00:00.000000)
datetime.date(2021,5,17) + relativedelta(minute=30) :: ok :: DT(2021-05-17 00:30:00.000000)
datetime.date(2021,5,17) - relativedelta(minute=30) :: ok :: DT(2021-05-17 00:30:00.000000)
datetime.date(2021,5,17) + relativedelta(second=0) :: ok :: DT(2021-05-17 00:00:00.000000)
datetime.date(2021,5,17) - relativedelta(second=0) :: ok :: DT(2021-05-17 00:00:00.000000)
datetime.date(2021,5,17) + relativedelta(second=59) :: ok :: DT(2021-05-17 00:00:59.000000)
datetime.date(2021,5,17) - relativedelta(second=59) :: ok :: DT(2021-05-17 00:00:59.000000)
datetime.date(2021,5,17) + relativedelta(microsecond=0) :: ok :: DT(2021-05-17 00:00:00.000000)
datetime.date(2021,5,17) - relativedelta(microsecond=0) :: ok :: DT(2021-05-17 00:00:00.000000)
datetime.date(2021,5,17) + relativedelta(microsecond=500000) :: ok :: DT(2021-05-17 00:00:00.500000)
datetime.date(2021,5,17) - relativedelta(microsecond=500000) :: ok :: DT(2021-05-17 00:00:00.500000)
datetime.date(2021,5,17) + relativedelta(weekday=0) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) - relativedelta(weekday=0) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) + relativedelta(weekday=4) :: ok :: D(2021-05-21)
datetime.date(2021,5,17) - relativedelta(weekday=4) :: ok :: D(2021-05-21)
datetime.date(2021,5,17) + relativedelta(weekday=6) :: ok :: D(2021-05-23)
datetime.date(2021,5,17) - relativedelta(weekday=6) :: ok :: D(2021-05-23)
datetime.date(2021,5,17) + relativedelta(weekday=-1) :: ok :: D(2021-05-23)
datetime.date(2021,5,17) - relativedelta(weekday=-1) :: ok :: D(2021-05-23)
datetime.date(2021,5,17) + relativedelta(weekday=-2) :: ok :: D(2021-05-22)
datetime.date(2021,5,17) - relativedelta(weekday=-2) :: ok :: D(2021-05-22)
datetime.date(2021,5,17) + relativedelta(weekday=-6) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - relativedelta(weekday=-6) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) + relativedelta(weekday=-7) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) - relativedelta(weekday=-7) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) + relativedelta(weekday=-1,weeks=-1) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) - relativedelta(weekday=-1,weeks=-1) :: ok :: D(2021-05-30)
datetime.date(2021,5,17) + relativedelta(weekday=-3,months=1) :: ok :: D(2021-06-18)
datetime.date(2021,5,17) - relativedelta(weekday=-3,months=1) :: ok :: D(2021-04-23)
datetime.date(2021,5,17) + relativedelta(leapdays=1) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) - relativedelta(leapdays=1) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) + relativedelta(leapdays=-1) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) - relativedelta(leapdays=-1) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) + relativedelta(yearday=60) :: ok :: D(2021-03-01)
datetime.date(2021,5,17) - relativedelta(yearday=60) :: ok :: D(2021-03-01)
datetime.date(2021,5,17) + relativedelta(yearday=1) :: ok :: D(2021-01-01)
datetime.date(2021,5,17) - relativedelta(yearday=1) :: ok :: D(2021-01-01)
datetime.date(2021,5,17) + relativedelta(yearday=366) :: ok :: D(2021-12-31)
datetime.date(2021,5,17) - relativedelta(yearday=366) :: ok :: D(2021-12-31)
datetime.date(2021,5,17) + relativedelta(nlyearday=60) :: ok :: D(2021-03-01)
datetime.date(2021,5,17) - relativedelta(nlyearday=60) :: ok :: D(2021-03-01)
datetime.date(2021,5,17) + relativedelta(nlyearday=200) :: ok :: D(2021-07-19)
datetime.date(2021,5,17) - relativedelta(nlyearday=200) :: ok :: D(2021-07-19)
datetime.date(2021,5,17) + relativedelta(months=1,days=-1) :: ok :: D(2021-06-16)
datetime.date(2021,5,17) - relativedelta(months=1,days=-1) :: ok :: D(2021-04-18)
datetime.date(2021,5,17) + relativedelta(years=1,months=-1) :: ok :: D(2022-04-17)
datetime.date(2021,5,17) - relativedelta(years=1,months=-1) :: ok :: D(2020-06-17)
datetime.date(2021,5,17) + relativedelta(day=1,months=1) :: ok :: D(2021-06-01)
datetime.date(2021,5,17) - relativedelta(day=1,months=1) :: ok :: D(2021-04-01)
datetime.date(2021,5,17) + relativedelta(day=31,months=-1) :: ok :: D(2021-04-30)
datetime.date(2021,5,17) - relativedelta(day=31,months=-1) :: ok :: D(2021-06-30)
datetime.date(2021,5,17) + relativedelta(months=1,day=1,days=-1) :: ok :: D(2021-05-31)
datetime.date(2021,5,17) - relativedelta(months=1,day=1,days=-1) :: ok :: D(2021-04-02)
datetime.date(2021,5,17) + relativedelta(hours=1,minutes=30) :: ok :: DT(2021-05-17 01:30:00.000000)
datetime.date(2021,5,17) - relativedelta(hours=1,minutes=30) :: ok :: DT(2021-05-16 22:30:00.000000)
datetime.date(2021,5,17) + relativedelta(days=1,hours=-25) :: ok :: DT(2021-05-16 23:00:00.000000)
datetime.date(2021,5,17) - relativedelta(days=1,hours=-25) :: ok :: DT(2021-05-17 01:00:00.000000)
datetime.date(2021,5,17) + relativedelta(weekday=0,days=1) :: ok :: D(2021-05-24)
datetime.date(2021,5,17) - relativedelta(weekday=0,days=1) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) + relativedelta(weekday=6,months=1) :: ok :: D(2021-06-20)
datetime.date(2021,5,17) - relativedelta(weekday=6,months=1) :: ok :: D(2021-04-18)
datetime.date(2021,5,17) + relativedelta(leapdays=1,months=2) :: ok :: D(2021-07-17)
datetime.date(2021,5,17) - relativedelta(leapdays=1,months=2) :: ok :: D(2021-03-17)
datetime.date(2021,5,17) + relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2021,5,17) - relativedelta(year=2024,month=2,day=29) :: ok :: D(2024-02-29)
datetime.date(2021,5,17) + relativedelta(days=1.5) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - relativedelta(days=1.5) :: ok :: D(2021-05-15)
datetime.date(2021,5,17) + relativedelta(hours=1.5) :: ok :: DT(2021-05-17 01:30:00.000000)
datetime.date(2021,5,17) - relativedelta(hours=1.5) :: ok :: DT(2021-05-16 22:30:00.000000)
datetime.date(2021,5,17) + relativedelta(months=1.5) :: err
datetime.date(2021,5,17) - relativedelta(months=1.5) :: err
datetime.date(2021,5,17) + relativedelta(seconds=0.5) :: ok :: DT(2021-05-17 00:00:00.500000)
datetime.date(2021,5,17) - relativedelta(seconds=0.5) :: ok :: DT(2021-05-16 23:59:59.500000)
datetime.date(2021,5,17) + datetime.timedelta(days=1) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - datetime.timedelta(days=1) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) + datetime.timedelta(days=-1) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) - datetime.timedelta(days=-1) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) + datetime.timedelta(hours=25) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - datetime.timedelta(hours=25) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) + datetime.timedelta(hours=-25) :: ok :: D(2021-05-15)
datetime.date(2021,5,17) - datetime.timedelta(hours=-25) :: ok :: D(2021-05-19)
datetime.date(2021,5,17) + datetime.timedelta(seconds=90061) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) - datetime.timedelta(seconds=90061) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) + datetime.timedelta(microseconds=-1) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) - datetime.timedelta(microseconds=-1) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) + datetime.timedelta(days=1,hours=-25) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) - datetime.timedelta(days=1,hours=-25) :: ok :: D(2021-05-18)
datetime.date(2021,5,17) + datetime.timedelta(weeks=1) :: ok :: D(2021-05-24)
datetime.date(2021,5,17) - datetime.timedelta(weeks=1) :: ok :: D(2021-05-10)
datetime.date(2021,5,17) + datetime.timedelta(milliseconds=1500) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) - datetime.timedelta(milliseconds=1500) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) + datetime.timedelta(days=0.5) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) - datetime.timedelta(days=0.5) :: ok :: D(2021-05-17)
datetime.date(2021,5,17) + datetime.timedelta(seconds=-0.5) :: ok :: D(2021-05-16)
datetime.date(2021,5,17) - datetime.timedelta(seconds=-0.5) :: ok :: D(2021-05-18)
datetime.date(2021,5,17).strftime('%Y-%m-%d') :: ok :: s:2021-05-17
datetime.date(2021,5,17).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2021-05-17 00:00:00
datetime.date(2021,5,17).strftime('%d/%m/%Y') :: ok :: s:17/05/2021
datetime.date(2021,5,17).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.date(2021,5,17).strftime('%j') :: ok :: s:137
datetime.date(2021,5,17).strftime('%U') :: ok :: s:20
datetime.date(2021,5,17).strftime('%W') :: ok :: s:20
datetime.date(2021,5,17).strftime('%w') :: ok :: s:1
datetime.date(2021,5,17).strftime('%a') :: ok :: s:Mon
datetime.date(2021,5,17).strftime('%A') :: ok :: s:Monday
datetime.date(2021,5,17).strftime('%b') :: ok :: s:May
datetime.date(2021,5,17).strftime('%B') :: ok :: s:May
datetime.date(2021,5,17).strftime('%p') :: ok :: s:AM
datetime.date(2021,5,17).strftime('%I') :: ok :: s:12
datetime.date(2021,5,17).strftime('%y') :: ok :: s:21
datetime.date(2021,5,17).strftime('%m') :: ok :: s:05
datetime.date(2021,5,17).strftime('%d') :: ok :: s:17
datetime.date(2021,5,17).strftime('%f') :: ok :: s:000000
datetime.date(2021,5,17).strftime('%%') :: ok :: s:%
datetime.date(2021,5,17).strftime('%Y-%j') :: ok :: s:2021-137
datetime.date(2021,5,17).strftime('%c') :: ok :: s:Mon May 17 00:00:00 2021
datetime.date(2021,5,17).strftime('%x') :: ok :: s:05/17/21
datetime.date(2021,5,17).strftime('%X') :: ok :: s:00:00:00
datetime.date(2021,5,17).year :: ok :: 2021
datetime.date(2021,5,17).month :: ok :: 5
datetime.date(2021,5,17).day :: ok :: 17
datetime.date(2021,5,17).toordinal() :: ok :: 737927
str(datetime.date(2021,5,17)) :: ok :: s:2021-05-17
bool(datetime.date(2021,5,17)) :: ok :: True
datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=1) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(days=1) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=-1) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(days=-1) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=0) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(days=0) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=45) :: ok :: DT(2024-03-16 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(days=45) :: ok :: DT(2023-12-17 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=-45) :: ok :: DT(2023-12-17 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(days=-45) :: ok :: DT(2024-03-16 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weeks=2) :: ok :: DT(2024-02-14 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weeks=2) :: ok :: DT(2024-01-17 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weeks=-3) :: ok :: DT(2024-01-10 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weeks=-3) :: ok :: DT(2024-02-21 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(months=1) :: ok :: DT(2023-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=-1) :: ok :: DT(2023-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(months=-1) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=13) :: ok :: DT(2025-02-28 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(months=13) :: ok :: DT(2022-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=-13) :: ok :: DT(2022-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(months=-13) :: ok :: DT(2025-02-28 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=12) :: ok :: DT(2025-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(months=12) :: ok :: DT(2023-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(years=1) :: ok :: DT(2025-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(years=1) :: ok :: DT(2023-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(years=-1) :: ok :: DT(2023-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(years=-1) :: ok :: DT(2025-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(years=100) :: ok :: DT(2124-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(years=100) :: ok :: DT(1924-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=1) :: ok :: DT(2024-02-01 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hours=1) :: ok :: DT(2024-01-31 22:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=24) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hours=24) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=-1) :: ok :: DT(2024-01-31 22:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hours=-1) :: ok :: DT(2024-02-01 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=-24) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hours=-24) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=48) :: ok :: DT(2024-02-02 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hours=48) :: ok :: DT(2024-01-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(minutes=1) :: ok :: DT(2024-02-01 00:00:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(minutes=1) :: ok :: DT(2024-01-31 23:58:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(minutes=1440) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(minutes=1440) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(minutes=-90) :: ok :: DT(2024-01-31 22:29:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(minutes=-90) :: ok :: DT(2024-02-01 01:29:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(seconds=1) :: ok :: DT(2024-02-01 00:00:00.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(seconds=1) :: ok :: DT(2024-01-31 23:59:58.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(seconds=86400) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(seconds=86400) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(seconds=-3600) :: ok :: DT(2024-01-31 22:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(seconds=-3600) :: ok :: DT(2024-02-01 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(microseconds=1) :: ok :: DT(2024-01-31 23:59:59.000001)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(microseconds=1) :: ok :: DT(2024-01-31 23:59:58.999999)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(microseconds=1000000) :: ok :: DT(2024-02-01 00:00:00.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(microseconds=1000000) :: ok :: DT(2024-01-31 23:59:58.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(microseconds=-1) :: ok :: DT(2024-01-31 23:59:58.999999)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(microseconds=-1) :: ok :: DT(2024-01-31 23:59:59.000001)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(day=1) :: ok :: DT(2024-01-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(day=1) :: ok :: DT(2024-01-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(day=15) :: ok :: DT(2024-01-15 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(day=15) :: ok :: DT(2024-01-15 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(day=31) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(day=31) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(month=1) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(month=1) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(month=2) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(month=2) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(month=12) :: ok :: DT(2024-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(month=12) :: ok :: DT(2024-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(year=2000) :: ok :: DT(2000-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(year=2000) :: ok :: DT(2000-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(year=1999) :: ok :: DT(1999-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(year=1999) :: ok :: DT(1999-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hour=0) :: ok :: DT(2024-01-31 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hour=0) :: ok :: DT(2024-01-31 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hour=5) :: ok :: DT(2024-01-31 05:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hour=5) :: ok :: DT(2024-01-31 05:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hour=23) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hour=23) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(minute=0) :: ok :: DT(2024-01-31 23:00:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(minute=0) :: ok :: DT(2024-01-31 23:00:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(minute=30) :: ok :: DT(2024-01-31 23:30:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(minute=30) :: ok :: DT(2024-01-31 23:30:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(second=0) :: ok :: DT(2024-01-31 23:59:00.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(second=0) :: ok :: DT(2024-01-31 23:59:00.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(second=59) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(second=59) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(microsecond=0) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(microsecond=0) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(microsecond=500000) :: ok :: DT(2024-01-31 23:59:59.500000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(microsecond=500000) :: ok :: DT(2024-01-31 23:59:59.500000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=0) :: ok :: DT(2024-02-05 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=0) :: ok :: DT(2024-02-05 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=4) :: ok :: DT(2024-02-02 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=4) :: ok :: DT(2024-02-02 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=6) :: ok :: DT(2024-02-04 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=6) :: ok :: DT(2024-02-04 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=-1) :: ok :: DT(2024-02-04 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=-1) :: ok :: DT(2024-02-04 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=-2) :: ok :: DT(2024-02-03 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=-2) :: ok :: DT(2024-02-03 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=-6) :: ok :: DT(2024-02-06 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=-6) :: ok :: DT(2024-02-06 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=-7) :: ok :: DT(2024-02-05 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=-7) :: ok :: DT(2024-02-05 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=-1,weeks=-1) :: ok :: DT(2024-01-28 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=-1,weeks=-1) :: ok :: DT(2024-02-11 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=-3,months=1) :: ok :: DT(2024-03-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=-3,months=1) :: ok :: DT(2024-01-05 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(leapdays=1) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(leapdays=1) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(leapdays=-1) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(leapdays=-1) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(yearday=60) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(yearday=60) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(yearday=1) :: ok :: DT(2024-01-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(yearday=1) :: ok :: DT(2024-01-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(yearday=366) :: ok :: DT(2024-12-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(yearday=366) :: ok :: DT(2024-12-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(nlyearday=60) :: ok :: DT(2024-03-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(nlyearday=60) :: ok :: DT(2024-03-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(nlyearday=200) :: ok :: DT(2024-07-19 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(nlyearday=200) :: ok :: DT(2024-07-19 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1,days=-1) :: ok :: DT(2024-02-28 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(months=1,days=-1) :: ok :: DT(2024-01-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(years=1,months=-1) :: ok :: DT(2024-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(years=1,months=-1) :: ok :: DT(2023-02-28 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(day=1,months=1) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(day=1,months=1) :: ok :: DT(2023-12-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(day=31,months=-1) :: ok :: DT(2023-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(day=31,months=-1) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1,day=1,days=-1) :: ok :: DT(2024-01-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(months=1,day=1,days=-1) :: ok :: DT(2023-12-02 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=1,minutes=30) :: ok :: DT(2024-02-01 01:29:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hours=1,minutes=30) :: ok :: DT(2024-01-31 22:29:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=1,hours=-25) :: ok :: DT(2024-01-31 22:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(days=1,hours=-25) :: ok :: DT(2024-02-01 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=0,days=1) :: ok :: DT(2024-02-05 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=0,days=1) :: ok :: DT(2024-02-05 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=6,months=1) :: ok :: DT(2024-03-03 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(weekday=6,months=1) :: ok :: DT(2023-12-31 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(leapdays=1,months=2) :: ok :: DT(2024-04-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(leapdays=1,months=2) :: ok :: DT(2023-11-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(year=2024,month=2,day=29) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(year=2024,month=2,day=29) :: ok :: DT(2024-02-29 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=1.5) :: ok :: DT(2024-02-02 11:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(days=1.5) :: ok :: DT(2024-01-30 11:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=1.5) :: ok :: DT(2024-02-01 01:29:59.000000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(hours=1.5) :: ok :: DT(2024-01-31 22:29:59.000000)
datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1.5) :: err
datetime.datetime(2024,1,31,23,59,59) - relativedelta(months=1.5) :: err
datetime.datetime(2024,1,31,23,59,59) + relativedelta(seconds=0.5) :: ok :: DT(2024-01-31 23:59:59.500000)
datetime.datetime(2024,1,31,23,59,59) - relativedelta(seconds=0.5) :: ok :: DT(2024-01-31 23:59:58.500000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(days=1) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(days=1) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(days=-1) :: ok :: DT(2024-01-30 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(days=-1) :: ok :: DT(2024-02-01 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(hours=25) :: ok :: DT(2024-02-02 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(hours=25) :: ok :: DT(2024-01-30 22:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(hours=-25) :: ok :: DT(2024-01-30 22:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(hours=-25) :: ok :: DT(2024-02-02 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(seconds=90061) :: ok :: DT(2024-02-02 01:01:00.000000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(seconds=90061) :: ok :: DT(2024-01-30 22:58:58.000000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(microseconds=-1) :: ok :: DT(2024-01-31 23:59:58.999999)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(microseconds=-1) :: ok :: DT(2024-01-31 23:59:59.000001)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(days=1,hours=-25) :: ok :: DT(2024-01-31 22:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(days=1,hours=-25) :: ok :: DT(2024-02-01 00:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(weeks=1) :: ok :: DT(2024-02-07 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(weeks=1) :: ok :: DT(2024-01-24 23:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(milliseconds=1500) :: ok :: DT(2024-02-01 00:00:00.500000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(milliseconds=1500) :: ok :: DT(2024-01-31 23:59:57.500000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(days=0.5) :: ok :: DT(2024-02-01 11:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(days=0.5) :: ok :: DT(2024-01-31 11:59:59.000000)
datetime.datetime(2024,1,31,23,59,59) + datetime.timedelta(seconds=-0.5) :: ok :: DT(2024-01-31 23:59:58.500000)
datetime.datetime(2024,1,31,23,59,59) - datetime.timedelta(seconds=-0.5) :: ok :: DT(2024-01-31 23:59:59.500000)
datetime.datetime(2024,1,31,23,59,59).strftime('%Y-%m-%d') :: ok :: s:2024-01-31
datetime.datetime(2024,1,31,23,59,59).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-01-31 23:59:59
datetime.datetime(2024,1,31,23,59,59).strftime('%d/%m/%Y') :: ok :: s:31/01/2024
datetime.datetime(2024,1,31,23,59,59).strftime('%H:%M:%S') :: ok :: s:23:59:59
datetime.datetime(2024,1,31,23,59,59).strftime('%j') :: ok :: s:031
datetime.datetime(2024,1,31,23,59,59).strftime('%U') :: ok :: s:04
datetime.datetime(2024,1,31,23,59,59).strftime('%W') :: ok :: s:05
datetime.datetime(2024,1,31,23,59,59).strftime('%w') :: ok :: s:3
datetime.datetime(2024,1,31,23,59,59).strftime('%a') :: ok :: s:Wed
datetime.datetime(2024,1,31,23,59,59).strftime('%A') :: ok :: s:Wednesday
datetime.datetime(2024,1,31,23,59,59).strftime('%b') :: ok :: s:Jan
datetime.datetime(2024,1,31,23,59,59).strftime('%B') :: ok :: s:January
datetime.datetime(2024,1,31,23,59,59).strftime('%p') :: ok :: s:PM
datetime.datetime(2024,1,31,23,59,59).strftime('%I') :: ok :: s:11
datetime.datetime(2024,1,31,23,59,59).strftime('%y') :: ok :: s:24
datetime.datetime(2024,1,31,23,59,59).strftime('%m') :: ok :: s:01
datetime.datetime(2024,1,31,23,59,59).strftime('%d') :: ok :: s:31
datetime.datetime(2024,1,31,23,59,59).strftime('%f') :: ok :: s:000000
datetime.datetime(2024,1,31,23,59,59).strftime('%%') :: ok :: s:%
datetime.datetime(2024,1,31,23,59,59).strftime('%Y-%j') :: ok :: s:2024-031
datetime.datetime(2024,1,31,23,59,59).strftime('%c') :: ok :: s:Wed Jan 31 23:59:59 2024
datetime.datetime(2024,1,31,23,59,59).strftime('%x') :: ok :: s:01/31/24
datetime.datetime(2024,1,31,23,59,59).strftime('%X') :: ok :: s:23:59:59
datetime.datetime(2024,1,31,23,59,59).year :: ok :: 2024
datetime.datetime(2024,1,31,23,59,59).month :: ok :: 1
datetime.datetime(2024,1,31,23,59,59).day :: ok :: 31
datetime.datetime(2024,1,31,23,59,59).toordinal() :: ok :: 738916
str(datetime.datetime(2024,1,31,23,59,59)) :: ok :: s:2024-01-31 23:59:59
bool(datetime.datetime(2024,1,31,23,59,59)) :: ok :: True
datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=1) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(days=1) :: ok :: DT(2024-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=-1) :: ok :: DT(2024-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(days=-1) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(days=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=45) :: ok :: DT(2024-04-14 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(days=45) :: ok :: DT(2024-01-15 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=-45) :: ok :: DT(2024-01-15 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(days=-45) :: ok :: DT(2024-04-14 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weeks=2) :: ok :: DT(2024-03-14 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weeks=2) :: ok :: DT(2024-02-15 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weeks=-3) :: ok :: DT(2024-02-08 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weeks=-3) :: ok :: DT(2024-03-21 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1) :: ok :: DT(2024-03-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(months=1) :: ok :: DT(2024-01-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=-1) :: ok :: DT(2024-01-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(months=-1) :: ok :: DT(2024-03-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=13) :: ok :: DT(2025-03-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(months=13) :: ok :: DT(2023-01-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=-13) :: ok :: DT(2023-01-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(months=-13) :: ok :: DT(2025-03-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=12) :: ok :: DT(2025-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(months=12) :: ok :: DT(2023-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(years=1) :: ok :: DT(2025-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(years=1) :: ok :: DT(2023-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(years=-1) :: ok :: DT(2023-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(years=-1) :: ok :: DT(2025-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(years=100) :: ok :: DT(2124-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(years=100) :: ok :: DT(1924-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=1) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hours=1) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=24) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hours=24) :: ok :: DT(2024-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=-1) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hours=-1) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=-24) :: ok :: DT(2024-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hours=-24) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=48) :: ok :: DT(2024-03-02 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hours=48) :: ok :: DT(2024-02-27 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(minutes=1) :: ok :: DT(2024-02-29 00:01:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(minutes=1) :: ok :: DT(2024-02-28 23:59:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(minutes=1440) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(minutes=1440) :: ok :: DT(2024-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(minutes=-90) :: ok :: DT(2024-02-28 22:30:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(minutes=-90) :: ok :: DT(2024-02-29 01:30:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(seconds=1) :: ok :: DT(2024-02-29 00:00:01.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(seconds=1) :: ok :: DT(2024-02-28 23:59:59.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(seconds=86400) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(seconds=86400) :: ok :: DT(2024-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(seconds=-3600) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(seconds=-3600) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(microseconds=1) :: ok :: DT(2024-02-29 00:00:00.000001)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(microseconds=1) :: ok :: DT(2024-02-28 23:59:59.999999)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(microseconds=1000000) :: ok :: DT(2024-02-29 00:00:01.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(microseconds=1000000) :: ok :: DT(2024-02-28 23:59:59.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(microseconds=-1) :: ok :: DT(2024-02-28 23:59:59.999999)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(microseconds=-1) :: ok :: DT(2024-02-29 00:00:00.000001)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(day=1) :: ok :: DT(2024-02-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(day=1) :: ok :: DT(2024-02-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(day=15) :: ok :: DT(2024-02-15 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(day=15) :: ok :: DT(2024-02-15 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(day=31) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(day=31) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(month=1) :: ok :: DT(2024-01-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(month=1) :: ok :: DT(2024-01-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(month=2) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(month=2) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(month=12) :: ok :: DT(2024-12-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(month=12) :: ok :: DT(2024-12-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(year=2000) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(year=2000) :: ok :: DT(2000-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(year=1999) :: ok :: DT(1999-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(year=1999) :: ok :: DT(1999-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hour=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hour=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hour=5) :: ok :: DT(2024-02-29 05:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hour=5) :: ok :: DT(2024-02-29 05:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hour=23) :: ok :: DT(2024-02-29 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hour=23) :: ok :: DT(2024-02-29 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(minute=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(minute=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(minute=30) :: ok :: DT(2024-02-29 00:30:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(minute=30) :: ok :: DT(2024-02-29 00:30:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(second=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(second=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(second=59) :: ok :: DT(2024-02-29 00:00:59.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(second=59) :: ok :: DT(2024-02-29 00:00:59.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(microsecond=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(microsecond=0) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(microsecond=500000) :: ok :: DT(2024-02-29 00:00:00.500000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(microsecond=500000) :: ok :: DT(2024-02-29 00:00:00.500000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=0) :: ok :: DT(2024-03-04 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=0) :: ok :: DT(2024-03-04 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=4) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=4) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=6) :: ok :: DT(2024-03-03 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=6) :: ok :: DT(2024-03-03 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=-1) :: ok :: DT(2024-03-03 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=-1) :: ok :: DT(2024-03-03 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=-2) :: ok :: DT(2024-03-02 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=-2) :: ok :: DT(2024-03-02 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=-6) :: ok :: DT(2024-03-05 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=-6) :: ok :: DT(2024-03-05 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=-7) :: ok :: DT(2024-03-04 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=-7) :: ok :: DT(2024-03-04 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=-1,weeks=-1) :: ok :: DT(2024-02-25 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=-1,weeks=-1) :: ok :: DT(2024-03-10 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=-3,months=1) :: ok :: DT(2024-03-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=-3,months=1) :: ok :: DT(2024-02-02 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(leapdays=1) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(leapdays=1) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(leapdays=-1) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(leapdays=-1) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(yearday=60) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(yearday=60) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(yearday=1) :: ok :: DT(2024-01-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(yearday=1) :: ok :: DT(2024-01-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(yearday=366) :: ok :: DT(2024-12-30 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(yearday=366) :: ok :: DT(2024-12-30 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(nlyearday=60) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(nlyearday=60) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(nlyearday=200) :: ok :: DT(2024-07-19 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(nlyearday=200) :: ok :: DT(2024-07-19 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1,days=-1) :: ok :: DT(2024-03-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(months=1,days=-1) :: ok :: DT(2024-01-30 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(years=1,months=-1) :: ok :: DT(2025-01-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(years=1,months=-1) :: ok :: DT(2023-03-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(day=1,months=1) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(day=1,months=1) :: ok :: DT(2024-01-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(day=31,months=-1) :: ok :: DT(2024-01-31 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(day=31,months=-1) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1,day=1,days=-1) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(months=1,day=1,days=-1) :: ok :: DT(2024-01-02 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=1,minutes=30) :: ok :: DT(2024-02-29 01:30:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hours=1,minutes=30) :: ok :: DT(2024-02-28 22:30:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=1,hours=-25) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(days=1,hours=-25) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=0,days=1) :: ok :: DT(2024-03-04 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=0,days=1) :: ok :: DT(2024-03-04 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=6,months=1) :: ok :: DT(2024-03-31 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(weekday=6,months=1) :: ok :: DT(2024-02-04 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(leapdays=1,months=2) :: ok :: DT(2024-04-30 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(leapdays=1,months=2) :: ok :: DT(2023-12-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(year=2024,month=2,day=29) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(year=2024,month=2,day=29) :: ok :: DT(2024-02-29 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=1.5) :: ok :: DT(2024-03-01 12:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(days=1.5) :: ok :: DT(2024-02-27 12:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=1.5) :: ok :: DT(2024-02-29 01:30:00.000000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(hours=1.5) :: ok :: DT(2024-02-28 22:30:00.000000)
datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1.5) :: err
datetime.datetime(2024,2,29,0,0,0) - relativedelta(months=1.5) :: err
datetime.datetime(2024,2,29,0,0,0) + relativedelta(seconds=0.5) :: ok :: DT(2024-02-29 00:00:00.500000)
datetime.datetime(2024,2,29,0,0,0) - relativedelta(seconds=0.5) :: ok :: DT(2024-02-28 23:59:59.500000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(days=1) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(days=1) :: ok :: DT(2024-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(days=-1) :: ok :: DT(2024-02-28 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(days=-1) :: ok :: DT(2024-03-01 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(hours=25) :: ok :: DT(2024-03-01 01:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(hours=25) :: ok :: DT(2024-02-27 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(hours=-25) :: ok :: DT(2024-02-27 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(hours=-25) :: ok :: DT(2024-03-01 01:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(seconds=90061) :: ok :: DT(2024-03-01 01:01:01.000000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(seconds=90061) :: ok :: DT(2024-02-27 22:58:59.000000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(microseconds=-1) :: ok :: DT(2024-02-28 23:59:59.999999)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(microseconds=-1) :: ok :: DT(2024-02-29 00:00:00.000001)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(days=1,hours=-25) :: ok :: DT(2024-02-28 23:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(days=1,hours=-25) :: ok :: DT(2024-02-29 01:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(weeks=1) :: ok :: DT(2024-03-07 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(weeks=1) :: ok :: DT(2024-02-22 00:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(milliseconds=1500) :: ok :: DT(2024-02-29 00:00:01.500000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(milliseconds=1500) :: ok :: DT(2024-02-28 23:59:58.500000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(days=0.5) :: ok :: DT(2024-02-29 12:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(days=0.5) :: ok :: DT(2024-02-28 12:00:00.000000)
datetime.datetime(2024,2,29,0,0,0) + datetime.timedelta(seconds=-0.5) :: ok :: DT(2024-02-28 23:59:59.500000)
datetime.datetime(2024,2,29,0,0,0) - datetime.timedelta(seconds=-0.5) :: ok :: DT(2024-02-29 00:00:00.500000)
datetime.datetime(2024,2,29,0,0,0).strftime('%Y-%m-%d') :: ok :: s:2024-02-29
datetime.datetime(2024,2,29,0,0,0).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-29 00:00:00
datetime.datetime(2024,2,29,0,0,0).strftime('%d/%m/%Y') :: ok :: s:29/02/2024
datetime.datetime(2024,2,29,0,0,0).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.datetime(2024,2,29,0,0,0).strftime('%j') :: ok :: s:060
datetime.datetime(2024,2,29,0,0,0).strftime('%U') :: ok :: s:08
datetime.datetime(2024,2,29,0,0,0).strftime('%W') :: ok :: s:09
datetime.datetime(2024,2,29,0,0,0).strftime('%w') :: ok :: s:4
datetime.datetime(2024,2,29,0,0,0).strftime('%a') :: ok :: s:Thu
datetime.datetime(2024,2,29,0,0,0).strftime('%A') :: ok :: s:Thursday
datetime.datetime(2024,2,29,0,0,0).strftime('%b') :: ok :: s:Feb
datetime.datetime(2024,2,29,0,0,0).strftime('%B') :: ok :: s:February
datetime.datetime(2024,2,29,0,0,0).strftime('%p') :: ok :: s:AM
datetime.datetime(2024,2,29,0,0,0).strftime('%I') :: ok :: s:12
datetime.datetime(2024,2,29,0,0,0).strftime('%y') :: ok :: s:24
datetime.datetime(2024,2,29,0,0,0).strftime('%m') :: ok :: s:02
datetime.datetime(2024,2,29,0,0,0).strftime('%d') :: ok :: s:29
datetime.datetime(2024,2,29,0,0,0).strftime('%f') :: ok :: s:000000
datetime.datetime(2024,2,29,0,0,0).strftime('%%') :: ok :: s:%
datetime.datetime(2024,2,29,0,0,0).strftime('%Y-%j') :: ok :: s:2024-060
datetime.datetime(2024,2,29,0,0,0).strftime('%c') :: ok :: s:Thu Feb 29 00:00:00 2024
datetime.datetime(2024,2,29,0,0,0).strftime('%x') :: ok :: s:02/29/24
datetime.datetime(2024,2,29,0,0,0).strftime('%X') :: ok :: s:00:00:00
datetime.datetime(2024,2,29,0,0,0).year :: ok :: 2024
datetime.datetime(2024,2,29,0,0,0).month :: ok :: 2
datetime.datetime(2024,2,29,0,0,0).day :: ok :: 29
datetime.datetime(2024,2,29,0,0,0).toordinal() :: ok :: 738945
str(datetime.datetime(2024,2,29,0,0,0)) :: ok :: s:2024-02-29 00:00:00
bool(datetime.datetime(2024,2,29,0,0,0)) :: ok :: True
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(days=1) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(days=1) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(days=-1) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(days=-1) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(days=0) :: ok :: DT(2024-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(days=0) :: ok :: DT(2024-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(days=45) :: ok :: DT(2024-07-30 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(days=45) :: ok :: DT(2024-05-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(days=-45) :: ok :: DT(2024-05-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(days=-45) :: ok :: DT(2024-07-30 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weeks=2) :: ok :: DT(2024-06-29 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weeks=2) :: ok :: DT(2024-06-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weeks=-3) :: ok :: DT(2024-05-25 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weeks=-3) :: ok :: DT(2024-07-06 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(months=1) :: ok :: DT(2024-07-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(months=1) :: ok :: DT(2024-05-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(months=-1) :: ok :: DT(2024-05-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(months=-1) :: ok :: DT(2024-07-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(months=13) :: ok :: DT(2025-07-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(months=13) :: ok :: DT(2023-05-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(months=-13) :: ok :: DT(2023-05-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(months=-13) :: ok :: DT(2025-07-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(months=12) :: ok :: DT(2025-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(months=12) :: ok :: DT(2023-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(years=1) :: ok :: DT(2025-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(years=1) :: ok :: DT(2023-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(years=-1) :: ok :: DT(2023-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(years=-1) :: ok :: DT(2025-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(years=100) :: ok :: DT(2124-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(years=100) :: ok :: DT(1924-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hours=1) :: ok :: DT(2024-06-15 13:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hours=1) :: ok :: DT(2024-06-15 11:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hours=24) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hours=24) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hours=-1) :: ok :: DT(2024-06-15 11:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hours=-1) :: ok :: DT(2024-06-15 13:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hours=-24) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hours=-24) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hours=48) :: ok :: DT(2024-06-17 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hours=48) :: ok :: DT(2024-06-13 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(minutes=1) :: ok :: DT(2024-06-15 12:31:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(minutes=1) :: ok :: DT(2024-06-15 12:29:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(minutes=1440) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(minutes=1440) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(minutes=-90) :: ok :: DT(2024-06-15 11:00:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(minutes=-90) :: ok :: DT(2024-06-15 14:00:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(seconds=1) :: ok :: DT(2024-06-15 12:30:46.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(seconds=1) :: ok :: DT(2024-06-15 12:30:44.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(seconds=86400) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(seconds=86400) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(seconds=-3600) :: ok :: DT(2024-06-15 11:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(seconds=-3600) :: ok :: DT(2024-06-15 13:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(microseconds=1) :: ok :: DT(2024-06-15 12:30:45.123457)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(microseconds=1) :: ok :: DT(2024-06-15 12:30:45.123455)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(microseconds=1000000) :: ok :: DT(2024-06-15 12:30:46.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(microseconds=1000000) :: ok :: DT(2024-06-15 12:30:44.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(microseconds=-1) :: ok :: DT(2024-06-15 12:30:45.123455)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(microseconds=-1) :: ok :: DT(2024-06-15 12:30:45.123457)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(day=1) :: ok :: DT(2024-06-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(day=1) :: ok :: DT(2024-06-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(day=15) :: ok :: DT(2024-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(day=15) :: ok :: DT(2024-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(day=31) :: ok :: DT(2024-06-30 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(day=31) :: ok :: DT(2024-06-30 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(month=1) :: ok :: DT(2024-01-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(month=1) :: ok :: DT(2024-01-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(month=2) :: ok :: DT(2024-02-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(month=2) :: ok :: DT(2024-02-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(month=12) :: ok :: DT(2024-12-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(month=12) :: ok :: DT(2024-12-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(year=2000) :: ok :: DT(2000-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(year=2000) :: ok :: DT(2000-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(year=1999) :: ok :: DT(1999-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(year=1999) :: ok :: DT(1999-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hour=0) :: ok :: DT(2024-06-15 00:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hour=0) :: ok :: DT(2024-06-15 00:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hour=5) :: ok :: DT(2024-06-15 05:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hour=5) :: ok :: DT(2024-06-15 05:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hour=23) :: ok :: DT(2024-06-15 23:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hour=23) :: ok :: DT(2024-06-15 23:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(minute=0) :: ok :: DT(2024-06-15 12:00:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(minute=0) :: ok :: DT(2024-06-15 12:00:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(minute=30) :: ok :: DT(2024-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(minute=30) :: ok :: DT(2024-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(second=0) :: ok :: DT(2024-06-15 12:30:00.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(second=0) :: ok :: DT(2024-06-15 12:30:00.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(second=59) :: ok :: DT(2024-06-15 12:30:59.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(second=59) :: ok :: DT(2024-06-15 12:30:59.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(microsecond=0) :: ok :: DT(2024-06-15 12:30:45.000000)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(microsecond=0) :: ok :: DT(2024-06-15 12:30:45.000000)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(microsecond=500000) :: ok :: DT(2024-06-15 12:30:45.500000)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(microsecond=500000) :: ok :: DT(2024-06-15 12:30:45.500000)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=0) :: ok :: DT(2024-06-17 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=0) :: ok :: DT(2024-06-17 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=4) :: ok :: DT(2024-06-21 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=4) :: ok :: DT(2024-06-21 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=6) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=6) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=-1) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=-1) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=-2) :: ok :: DT(2024-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=-2) :: ok :: DT(2024-06-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=-6) :: ok :: DT(2024-06-18 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=-6) :: ok :: DT(2024-06-18 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=-7) :: ok :: DT(2024-06-17 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=-7) :: ok :: DT(2024-06-17 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=-1,weeks=-1) :: ok :: DT(2024-06-09 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=-1,weeks=-1) :: ok :: DT(2024-06-23 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=-3,months=1) :: ok :: DT(2024-07-19 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=-3,months=1) :: ok :: DT(2024-05-17 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(leapdays=1) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(leapdays=1) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(leapdays=-1) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(leapdays=-1) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(yearday=60) :: ok :: DT(2024-02-29 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(yearday=60) :: ok :: DT(2024-02-29 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(yearday=1) :: ok :: DT(2024-01-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(yearday=1) :: ok :: DT(2024-01-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(yearday=366) :: ok :: DT(2024-12-30 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(yearday=366) :: ok :: DT(2024-12-30 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(nlyearday=60) :: ok :: DT(2024-03-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(nlyearday=60) :: ok :: DT(2024-03-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(nlyearday=200) :: ok :: DT(2024-07-19 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(nlyearday=200) :: ok :: DT(2024-07-19 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(months=1,days=-1) :: ok :: DT(2024-07-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(months=1,days=-1) :: ok :: DT(2024-05-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(years=1,months=-1) :: ok :: DT(2025-05-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(years=1,months=-1) :: ok :: DT(2023-07-15 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(day=1,months=1) :: ok :: DT(2024-07-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(day=1,months=1) :: ok :: DT(2024-05-01 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(day=31,months=-1) :: ok :: DT(2024-05-31 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(day=31,months=-1) :: ok :: DT(2024-07-31 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(months=1,day=1,days=-1) :: ok :: DT(2024-06-30 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(months=1,day=1,days=-1) :: ok :: DT(2024-05-02 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hours=1,minutes=30) :: ok :: DT(2024-06-15 14:00:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hours=1,minutes=30) :: ok :: DT(2024-06-15 11:00:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(days=1,hours=-25) :: ok :: DT(2024-06-15 11:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(days=1,hours=-25) :: ok :: DT(2024-06-15 13:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=0,days=1) :: ok :: DT(2024-06-17 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=0,days=1) :: ok :: DT(2024-06-17 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(weekday=6,months=1) :: ok :: DT(2024-07-21 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(weekday=6,months=1) :: ok :: DT(2024-05-19 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(leapdays=1,months=2) :: ok :: DT(2024-08-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(leapdays=1,months=2) :: ok :: DT(2024-04-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(year=2024,month=2,day=29) :: ok :: DT(2024-02-29 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(year=2024,month=2,day=29) :: ok :: DT(2024-02-29 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(days=1.5) :: ok :: DT(2024-06-17 00:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(days=1.5) :: ok :: DT(2024-06-14 00:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(hours=1.5) :: ok :: DT(2024-06-15 14:00:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(hours=1.5) :: ok :: DT(2024-06-15 11:00:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(months=1.5) :: err
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(months=1.5) :: err
datetime.datetime(2024,6,15,12,30,45,123456) + relativedelta(seconds=0.5) :: ok :: DT(2024-06-15 12:30:45.623456)
datetime.datetime(2024,6,15,12,30,45,123456) - relativedelta(seconds=0.5) :: ok :: DT(2024-06-15 12:30:44.623456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(days=1) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(days=1) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(days=-1) :: ok :: DT(2024-06-14 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(days=-1) :: ok :: DT(2024-06-16 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(hours=25) :: ok :: DT(2024-06-16 13:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(hours=25) :: ok :: DT(2024-06-14 11:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(hours=-25) :: ok :: DT(2024-06-14 11:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(hours=-25) :: ok :: DT(2024-06-16 13:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(seconds=90061) :: ok :: DT(2024-06-16 13:31:46.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(seconds=90061) :: ok :: DT(2024-06-14 11:29:44.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(microseconds=-1) :: ok :: DT(2024-06-15 12:30:45.123455)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(microseconds=-1) :: ok :: DT(2024-06-15 12:30:45.123457)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(days=1,hours=-25) :: ok :: DT(2024-06-15 11:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(days=1,hours=-25) :: ok :: DT(2024-06-15 13:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(weeks=1) :: ok :: DT(2024-06-22 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(weeks=1) :: ok :: DT(2024-06-08 12:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(milliseconds=1500) :: ok :: DT(2024-06-15 12:30:46.623456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(milliseconds=1500) :: ok :: DT(2024-06-15 12:30:43.623456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(days=0.5) :: ok :: DT(2024-06-16 00:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(days=0.5) :: ok :: DT(2024-06-15 00:30:45.123456)
datetime.datetime(2024,6,15,12,30,45,123456) + datetime.timedelta(seconds=-0.5) :: ok :: DT(2024-06-15 12:30:44.623456)
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.timedelta(seconds=-0.5) :: ok :: DT(2024-06-15 12:30:45.623456)
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%Y-%m-%d') :: ok :: s:2024-06-15
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-06-15 12:30:45
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%d/%m/%Y') :: ok :: s:15/06/2024
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%H:%M:%S') :: ok :: s:12:30:45
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%j') :: ok :: s:167
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%U') :: ok :: s:23
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%W') :: ok :: s:24
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%w') :: ok :: s:6
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%a') :: ok :: s:Sat
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%A') :: ok :: s:Saturday
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%b') :: ok :: s:Jun
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%B') :: ok :: s:June
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%p') :: ok :: s:PM
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%I') :: ok :: s:12
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%y') :: ok :: s:24
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%m') :: ok :: s:06
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%d') :: ok :: s:15
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%f') :: ok :: s:123456
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%%') :: ok :: s:%
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%Y-%j') :: ok :: s:2024-167
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%c') :: ok :: s:Sat Jun 15 12:30:45 2024
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%x') :: ok :: s:06/15/24
datetime.datetime(2024,6,15,12,30,45,123456).strftime('%X') :: ok :: s:12:30:45
datetime.datetime(2024,6,15,12,30,45,123456).year :: ok :: 2024
datetime.datetime(2024,6,15,12,30,45,123456).month :: ok :: 6
datetime.datetime(2024,6,15,12,30,45,123456).day :: ok :: 15
datetime.datetime(2024,6,15,12,30,45,123456).toordinal() :: ok :: 739052
str(datetime.datetime(2024,6,15,12,30,45,123456)) :: ok :: s:2024-06-15 12:30:45.123456
bool(datetime.datetime(2024,6,15,12,30,45,123456)) :: ok :: True
datetime.datetime(2023,12,31,23,0,0) + relativedelta(days=1) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(days=1) :: ok :: DT(2023-12-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(days=-1) :: ok :: DT(2023-12-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(days=-1) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(days=0) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(days=0) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(days=45) :: ok :: DT(2024-02-14 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(days=45) :: ok :: DT(2023-11-16 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(days=-45) :: ok :: DT(2023-11-16 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(days=-45) :: ok :: DT(2024-02-14 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weeks=2) :: ok :: DT(2024-01-14 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weeks=2) :: ok :: DT(2023-12-17 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weeks=-3) :: ok :: DT(2023-12-10 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weeks=-3) :: ok :: DT(2024-01-21 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(months=1) :: ok :: DT(2024-01-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(months=1) :: ok :: DT(2023-11-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(months=-1) :: ok :: DT(2023-11-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(months=-1) :: ok :: DT(2024-01-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(months=13) :: ok :: DT(2025-01-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(months=13) :: ok :: DT(2022-11-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(months=-13) :: ok :: DT(2022-11-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(months=-13) :: ok :: DT(2025-01-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(months=12) :: ok :: DT(2024-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(months=12) :: ok :: DT(2022-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(years=1) :: ok :: DT(2024-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(years=1) :: ok :: DT(2022-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(years=-1) :: ok :: DT(2022-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(years=-1) :: ok :: DT(2024-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(years=100) :: ok :: DT(2123-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(years=100) :: ok :: DT(1923-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hours=1) :: ok :: DT(2024-01-01 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hours=1) :: ok :: DT(2023-12-31 22:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hours=24) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hours=24) :: ok :: DT(2023-12-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hours=-1) :: ok :: DT(2023-12-31 22:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hours=-1) :: ok :: DT(2024-01-01 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hours=-24) :: ok :: DT(2023-12-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hours=-24) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hours=48) :: ok :: DT(2024-01-02 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hours=48) :: ok :: DT(2023-12-29 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(minutes=1) :: ok :: DT(2023-12-31 23:01:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(minutes=1) :: ok :: DT(2023-12-31 22:59:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(minutes=1440) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(minutes=1440) :: ok :: DT(2023-12-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(minutes=-90) :: ok :: DT(2023-12-31 21:30:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(minutes=-90) :: ok :: DT(2024-01-01 00:30:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(seconds=1) :: ok :: DT(2023-12-31 23:00:01.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(seconds=1) :: ok :: DT(2023-12-31 22:59:59.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(seconds=86400) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(seconds=86400) :: ok :: DT(2023-12-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(seconds=-3600) :: ok :: DT(2023-12-31 22:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(seconds=-3600) :: ok :: DT(2024-01-01 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(microseconds=1) :: ok :: DT(2023-12-31 23:00:00.000001)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(microseconds=1) :: ok :: DT(2023-12-31 22:59:59.999999)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(microseconds=1000000) :: ok :: DT(2023-12-31 23:00:01.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(microseconds=1000000) :: ok :: DT(2023-12-31 22:59:59.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(microseconds=-1) :: ok :: DT(2023-12-31 22:59:59.999999)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(microseconds=-1) :: ok :: DT(2023-12-31 23:00:00.000001)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(day=1) :: ok :: DT(2023-12-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(day=1) :: ok :: DT(2023-12-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(day=15) :: ok :: DT(2023-12-15 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(day=15) :: ok :: DT(2023-12-15 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(day=31) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(day=31) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(month=1) :: ok :: DT(2023-01-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(month=1) :: ok :: DT(2023-01-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(month=2) :: ok :: DT(2023-02-28 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(month=2) :: ok :: DT(2023-02-28 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(month=12) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(month=12) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(year=2000) :: ok :: DT(2000-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(year=2000) :: ok :: DT(2000-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(year=1999) :: ok :: DT(1999-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(year=1999) :: ok :: DT(1999-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hour=0) :: ok :: DT(2023-12-31 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hour=0) :: ok :: DT(2023-12-31 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hour=5) :: ok :: DT(2023-12-31 05:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hour=5) :: ok :: DT(2023-12-31 05:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hour=23) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hour=23) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(minute=0) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(minute=0) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(minute=30) :: ok :: DT(2023-12-31 23:30:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(minute=30) :: ok :: DT(2023-12-31 23:30:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(second=0) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(second=0) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(second=59) :: ok :: DT(2023-12-31 23:00:59.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(second=59) :: ok :: DT(2023-12-31 23:00:59.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(microsecond=0) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(microsecond=0) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(microsecond=500000) :: ok :: DT(2023-12-31 23:00:00.500000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(microsecond=500000) :: ok :: DT(2023-12-31 23:00:00.500000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=0) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=0) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=4) :: ok :: DT(2024-01-05 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=4) :: ok :: DT(2024-01-05 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=6) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=6) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=-1) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=-1) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=-2) :: ok :: DT(2024-01-06 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=-2) :: ok :: DT(2024-01-06 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=-6) :: ok :: DT(2024-01-02 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=-6) :: ok :: DT(2024-01-02 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=-7) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=-7) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=-1,weeks=-1) :: ok :: DT(2023-12-24 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=-1,weeks=-1) :: ok :: DT(2024-01-07 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=-3,months=1) :: ok :: DT(2024-02-02 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=-3,months=1) :: ok :: DT(2023-12-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(leapdays=1) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(leapdays=1) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(leapdays=-1) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(leapdays=-1) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(yearday=60) :: ok :: DT(2023-03-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(yearday=60) :: ok :: DT(2023-03-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(yearday=1) :: ok :: DT(2023-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(yearday=1) :: ok :: DT(2023-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(yearday=366) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(yearday=366) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(nlyearday=60) :: ok :: DT(2023-03-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(nlyearday=60) :: ok :: DT(2023-03-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(nlyearday=200) :: ok :: DT(2023-07-19 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(nlyearday=200) :: ok :: DT(2023-07-19 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(months=1,days=-1) :: ok :: DT(2024-01-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(months=1,days=-1) :: ok :: DT(2023-12-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(years=1,months=-1) :: ok :: DT(2024-11-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(years=1,months=-1) :: ok :: DT(2023-01-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(day=1,months=1) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(day=1,months=1) :: ok :: DT(2023-11-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(day=31,months=-1) :: ok :: DT(2023-11-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(day=31,months=-1) :: ok :: DT(2024-01-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(months=1,day=1,days=-1) :: ok :: DT(2023-12-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(months=1,day=1,days=-1) :: ok :: DT(2023-11-02 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hours=1,minutes=30) :: ok :: DT(2024-01-01 00:30:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hours=1,minutes=30) :: ok :: DT(2023-12-31 21:30:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(days=1,hours=-25) :: ok :: DT(2023-12-31 22:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(days=1,hours=-25) :: ok :: DT(2024-01-01 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=0,days=1) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=0,days=1) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(weekday=6,months=1) :: ok :: DT(2024-02-04 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(weekday=6,months=1) :: ok :: DT(2023-12-03 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(leapdays=1,months=2) :: ok :: DT(2024-02-29 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(leapdays=1,months=2) :: ok :: DT(2023-10-31 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(year=2024,month=2,day=29) :: ok :: DT(2024-02-29 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(year=2024,month=2,day=29) :: ok :: DT(2024-02-29 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(days=1.5) :: ok :: DT(2024-01-02 11:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(days=1.5) :: ok :: DT(2023-12-30 11:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(hours=1.5) :: ok :: DT(2024-01-01 00:30:00.000000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(hours=1.5) :: ok :: DT(2023-12-31 21:30:00.000000)
datetime.datetime(2023,12,31,23,0,0) + relativedelta(months=1.5) :: err
datetime.datetime(2023,12,31,23,0,0) - relativedelta(months=1.5) :: err
datetime.datetime(2023,12,31,23,0,0) + relativedelta(seconds=0.5) :: ok :: DT(2023-12-31 23:00:00.500000)
datetime.datetime(2023,12,31,23,0,0) - relativedelta(seconds=0.5) :: ok :: DT(2023-12-31 22:59:59.500000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(days=1) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(days=1) :: ok :: DT(2023-12-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(days=-1) :: ok :: DT(2023-12-30 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(days=-1) :: ok :: DT(2024-01-01 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(hours=25) :: ok :: DT(2024-01-02 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(hours=25) :: ok :: DT(2023-12-30 22:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(hours=-25) :: ok :: DT(2023-12-30 22:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(hours=-25) :: ok :: DT(2024-01-02 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(seconds=90061) :: ok :: DT(2024-01-02 00:01:01.000000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(seconds=90061) :: ok :: DT(2023-12-30 21:58:59.000000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(microseconds=-1) :: ok :: DT(2023-12-31 22:59:59.999999)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(microseconds=-1) :: ok :: DT(2023-12-31 23:00:00.000001)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(days=1,hours=-25) :: ok :: DT(2023-12-31 22:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(days=1,hours=-25) :: ok :: DT(2024-01-01 00:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(weeks=1) :: ok :: DT(2024-01-07 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(weeks=1) :: ok :: DT(2023-12-24 23:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(milliseconds=1500) :: ok :: DT(2023-12-31 23:00:01.500000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(milliseconds=1500) :: ok :: DT(2023-12-31 22:59:58.500000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(days=0.5) :: ok :: DT(2024-01-01 11:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(days=0.5) :: ok :: DT(2023-12-31 11:00:00.000000)
datetime.datetime(2023,12,31,23,0,0) + datetime.timedelta(seconds=-0.5) :: ok :: DT(2023-12-31 22:59:59.500000)
datetime.datetime(2023,12,31,23,0,0) - datetime.timedelta(seconds=-0.5) :: ok :: DT(2023-12-31 23:00:00.500000)
datetime.datetime(2023,12,31,23,0,0).strftime('%Y-%m-%d') :: ok :: s:2023-12-31
datetime.datetime(2023,12,31,23,0,0).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2023-12-31 23:00:00
datetime.datetime(2023,12,31,23,0,0).strftime('%d/%m/%Y') :: ok :: s:31/12/2023
datetime.datetime(2023,12,31,23,0,0).strftime('%H:%M:%S') :: ok :: s:23:00:00
datetime.datetime(2023,12,31,23,0,0).strftime('%j') :: ok :: s:365
datetime.datetime(2023,12,31,23,0,0).strftime('%U') :: ok :: s:53
datetime.datetime(2023,12,31,23,0,0).strftime('%W') :: ok :: s:52
datetime.datetime(2023,12,31,23,0,0).strftime('%w') :: ok :: s:0
datetime.datetime(2023,12,31,23,0,0).strftime('%a') :: ok :: s:Sun
datetime.datetime(2023,12,31,23,0,0).strftime('%A') :: ok :: s:Sunday
datetime.datetime(2023,12,31,23,0,0).strftime('%b') :: ok :: s:Dec
datetime.datetime(2023,12,31,23,0,0).strftime('%B') :: ok :: s:December
datetime.datetime(2023,12,31,23,0,0).strftime('%p') :: ok :: s:PM
datetime.datetime(2023,12,31,23,0,0).strftime('%I') :: ok :: s:11
datetime.datetime(2023,12,31,23,0,0).strftime('%y') :: ok :: s:23
datetime.datetime(2023,12,31,23,0,0).strftime('%m') :: ok :: s:12
datetime.datetime(2023,12,31,23,0,0).strftime('%d') :: ok :: s:31
datetime.datetime(2023,12,31,23,0,0).strftime('%f') :: ok :: s:000000
datetime.datetime(2023,12,31,23,0,0).strftime('%%') :: ok :: s:%
datetime.datetime(2023,12,31,23,0,0).strftime('%Y-%j') :: ok :: s:2023-365
datetime.datetime(2023,12,31,23,0,0).strftime('%c') :: ok :: s:Sun Dec 31 23:00:00 2023
datetime.datetime(2023,12,31,23,0,0).strftime('%x') :: ok :: s:12/31/23
datetime.datetime(2023,12,31,23,0,0).strftime('%X') :: ok :: s:23:00:00
datetime.datetime(2023,12,31,23,0,0).year :: ok :: 2023
datetime.datetime(2023,12,31,23,0,0).month :: ok :: 12
datetime.datetime(2023,12,31,23,0,0).day :: ok :: 31
datetime.datetime(2023,12,31,23,0,0).toordinal() :: ok :: 738885
str(datetime.datetime(2023,12,31,23,0,0)) :: ok :: s:2023-12-31 23:00:00
bool(datetime.datetime(2023,12,31,23,0,0)) :: ok :: True
datetime.date(2024,1,31) - datetime.date(2024,2,29) :: ok :: TD(-29,0,0)
datetime.date(2024,2,29) - datetime.date(2024,1,31) :: ok :: TD(29,0,0)
datetime.date(2024,1,31) < datetime.date(2024,2,29) :: ok :: True
datetime.date(2024,1,31) == datetime.date(2024,2,29) :: ok :: False
(datetime.date(2024,1,31) - datetime.date(2024,2,29)).days :: ok :: -29
datetime.date(2024,1,31) - datetime.date(2023,3,1) :: ok :: TD(336,0,0)
datetime.date(2023,3,1) - datetime.date(2024,1,31) :: ok :: TD(-336,0,0)
datetime.date(2024,1,31) < datetime.date(2023,3,1) :: ok :: False
datetime.date(2024,1,31) == datetime.date(2023,3,1) :: ok :: False
(datetime.date(2024,1,31) - datetime.date(2023,3,1)).days :: ok :: 336
datetime.date(2024,1,31) - datetime.date(2024,12,31) :: ok :: TD(-335,0,0)
datetime.date(2024,12,31) - datetime.date(2024,1,31) :: ok :: TD(335,0,0)
datetime.date(2024,1,31) < datetime.date(2024,12,31) :: ok :: True
datetime.date(2024,1,31) == datetime.date(2024,12,31) :: ok :: False
(datetime.date(2024,1,31) - datetime.date(2024,12,31)).days :: ok :: -335
datetime.date(2024,1,31) - datetime.date(2000,2,29) :: ok :: TD(8737,0,0)
datetime.date(2000,2,29) - datetime.date(2024,1,31) :: ok :: TD(-8737,0,0)
datetime.date(2024,1,31) < datetime.date(2000,2,29) :: ok :: False
datetime.date(2024,1,31) == datetime.date(2000,2,29) :: ok :: False
(datetime.date(2024,1,31) - datetime.date(2000,2,29)).days :: ok :: 8737
datetime.date(2024,1,31) - datetime.date(2024,3,31) :: ok :: TD(-60,0,0)
datetime.date(2024,3,31) - datetime.date(2024,1,31) :: ok :: TD(60,0,0)
datetime.date(2024,1,31) < datetime.date(2024,3,31) :: ok :: True
datetime.date(2024,1,31) == datetime.date(2024,3,31) :: ok :: False
(datetime.date(2024,1,31) - datetime.date(2024,3,31)).days :: ok :: -60
datetime.date(2024,1,31) - datetime.date(2021,5,17) :: ok :: TD(989,0,0)
datetime.date(2021,5,17) - datetime.date(2024,1,31) :: ok :: TD(-989,0,0)
datetime.date(2024,1,31) < datetime.date(2021,5,17) :: ok :: False
datetime.date(2024,1,31) == datetime.date(2021,5,17) :: ok :: False
(datetime.date(2024,1,31) - datetime.date(2021,5,17)).days :: ok :: 989
datetime.date(2024,2,29) - datetime.date(2023,3,1) :: ok :: TD(365,0,0)
datetime.date(2023,3,1) - datetime.date(2024,2,29) :: ok :: TD(-365,0,0)
datetime.date(2024,2,29) < datetime.date(2023,3,1) :: ok :: False
datetime.date(2024,2,29) == datetime.date(2023,3,1) :: ok :: False
(datetime.date(2024,2,29) - datetime.date(2023,3,1)).days :: ok :: 365
datetime.date(2024,2,29) - datetime.date(2024,12,31) :: ok :: TD(-306,0,0)
datetime.date(2024,12,31) - datetime.date(2024,2,29) :: ok :: TD(306,0,0)
datetime.date(2024,2,29) < datetime.date(2024,12,31) :: ok :: True
datetime.date(2024,2,29) == datetime.date(2024,12,31) :: ok :: False
(datetime.date(2024,2,29) - datetime.date(2024,12,31)).days :: ok :: -306
datetime.date(2024,2,29) - datetime.date(2000,2,29) :: ok :: TD(8766,0,0)
datetime.date(2000,2,29) - datetime.date(2024,2,29) :: ok :: TD(-8766,0,0)
datetime.date(2024,2,29) < datetime.date(2000,2,29) :: ok :: False
datetime.date(2024,2,29) == datetime.date(2000,2,29) :: ok :: False
(datetime.date(2024,2,29) - datetime.date(2000,2,29)).days :: ok :: 8766
datetime.date(2024,2,29) - datetime.date(2024,3,31) :: ok :: TD(-31,0,0)
datetime.date(2024,3,31) - datetime.date(2024,2,29) :: ok :: TD(31,0,0)
datetime.date(2024,2,29) < datetime.date(2024,3,31) :: ok :: True
datetime.date(2024,2,29) == datetime.date(2024,3,31) :: ok :: False
(datetime.date(2024,2,29) - datetime.date(2024,3,31)).days :: ok :: -31
datetime.date(2024,2,29) - datetime.date(2021,5,17) :: ok :: TD(1018,0,0)
datetime.date(2021,5,17) - datetime.date(2024,2,29) :: ok :: TD(-1018,0,0)
datetime.date(2024,2,29) < datetime.date(2021,5,17) :: ok :: False
datetime.date(2024,2,29) == datetime.date(2021,5,17) :: ok :: False
(datetime.date(2024,2,29) - datetime.date(2021,5,17)).days :: ok :: 1018
datetime.date(2023,3,1) - datetime.date(2024,12,31) :: ok :: TD(-671,0,0)
datetime.date(2024,12,31) - datetime.date(2023,3,1) :: ok :: TD(671,0,0)
datetime.date(2023,3,1) < datetime.date(2024,12,31) :: ok :: True
datetime.date(2023,3,1) == datetime.date(2024,12,31) :: ok :: False
(datetime.date(2023,3,1) - datetime.date(2024,12,31)).days :: ok :: -671
datetime.date(2023,3,1) - datetime.date(2000,2,29) :: ok :: TD(8401,0,0)
datetime.date(2000,2,29) - datetime.date(2023,3,1) :: ok :: TD(-8401,0,0)
datetime.date(2023,3,1) < datetime.date(2000,2,29) :: ok :: False
datetime.date(2023,3,1) == datetime.date(2000,2,29) :: ok :: False
(datetime.date(2023,3,1) - datetime.date(2000,2,29)).days :: ok :: 8401
datetime.date(2023,3,1) - datetime.date(2024,3,31) :: ok :: TD(-396,0,0)
datetime.date(2024,3,31) - datetime.date(2023,3,1) :: ok :: TD(396,0,0)
datetime.date(2023,3,1) < datetime.date(2024,3,31) :: ok :: True
datetime.date(2023,3,1) == datetime.date(2024,3,31) :: ok :: False
(datetime.date(2023,3,1) - datetime.date(2024,3,31)).days :: ok :: -396
datetime.date(2023,3,1) - datetime.date(2021,5,17) :: ok :: TD(653,0,0)
datetime.date(2021,5,17) - datetime.date(2023,3,1) :: ok :: TD(-653,0,0)
datetime.date(2023,3,1) < datetime.date(2021,5,17) :: ok :: False
datetime.date(2023,3,1) == datetime.date(2021,5,17) :: ok :: False
(datetime.date(2023,3,1) - datetime.date(2021,5,17)).days :: ok :: 653
datetime.date(2024,12,31) - datetime.date(2000,2,29) :: ok :: TD(9072,0,0)
datetime.date(2000,2,29) - datetime.date(2024,12,31) :: ok :: TD(-9072,0,0)
datetime.date(2024,12,31) < datetime.date(2000,2,29) :: ok :: False
datetime.date(2024,12,31) == datetime.date(2000,2,29) :: ok :: False
(datetime.date(2024,12,31) - datetime.date(2000,2,29)).days :: ok :: 9072
datetime.date(2024,12,31) - datetime.date(2024,3,31) :: ok :: TD(275,0,0)
datetime.date(2024,3,31) - datetime.date(2024,12,31) :: ok :: TD(-275,0,0)
datetime.date(2024,12,31) < datetime.date(2024,3,31) :: ok :: False
datetime.date(2024,12,31) == datetime.date(2024,3,31) :: ok :: False
(datetime.date(2024,12,31) - datetime.date(2024,3,31)).days :: ok :: 275
datetime.date(2024,12,31) - datetime.date(2021,5,17) :: ok :: TD(1324,0,0)
datetime.date(2021,5,17) - datetime.date(2024,12,31) :: ok :: TD(-1324,0,0)
datetime.date(2024,12,31) < datetime.date(2021,5,17) :: ok :: False
datetime.date(2024,12,31) == datetime.date(2021,5,17) :: ok :: False
(datetime.date(2024,12,31) - datetime.date(2021,5,17)).days :: ok :: 1324
datetime.date(2000,2,29) - datetime.date(2024,3,31) :: ok :: TD(-8797,0,0)
datetime.date(2024,3,31) - datetime.date(2000,2,29) :: ok :: TD(8797,0,0)
datetime.date(2000,2,29) < datetime.date(2024,3,31) :: ok :: True
datetime.date(2000,2,29) == datetime.date(2024,3,31) :: ok :: False
(datetime.date(2000,2,29) - datetime.date(2024,3,31)).days :: ok :: -8797
datetime.date(2000,2,29) - datetime.date(2021,5,17) :: ok :: TD(-7748,0,0)
datetime.date(2021,5,17) - datetime.date(2000,2,29) :: ok :: TD(7748,0,0)
datetime.date(2000,2,29) < datetime.date(2021,5,17) :: ok :: True
datetime.date(2000,2,29) == datetime.date(2021,5,17) :: ok :: False
(datetime.date(2000,2,29) - datetime.date(2021,5,17)).days :: ok :: -7748
datetime.date(2024,3,31) - datetime.date(2021,5,17) :: ok :: TD(1049,0,0)
datetime.date(2021,5,17) - datetime.date(2024,3,31) :: ok :: TD(-1049,0,0)
datetime.date(2024,3,31) < datetime.date(2021,5,17) :: ok :: False
datetime.date(2024,3,31) == datetime.date(2021,5,17) :: ok :: False
(datetime.date(2024,3,31) - datetime.date(2021,5,17)).days :: ok :: 1049
datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2024,2,29,0,0,0) :: ok :: TD(-29,86399,0)
(datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2024,2,29,0,0,0)).days :: ok :: -29
(datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2024,2,29,0,0,0)).seconds :: ok :: 86399
datetime.datetime(2024,1,31,23,59,59) < datetime.datetime(2024,2,29,0,0,0) :: ok :: True
datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2024,6,15,12,30,45,123456) :: ok :: TD(-136,41353,876544)
(datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2024,6,15,12,30,45,123456)).days :: ok :: -136
(datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2024,6,15,12,30,45,123456)).seconds :: ok :: 41353
datetime.datetime(2024,1,31,23,59,59) < datetime.datetime(2024,6,15,12,30,45,123456) :: ok :: True
datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2023,12,31,23,0,0) :: ok :: TD(31,3599,0)
(datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2023,12,31,23,0,0)).days :: ok :: 31
(datetime.datetime(2024,1,31,23,59,59) - datetime.datetime(2023,12,31,23,0,0)).seconds :: ok :: 3599
datetime.datetime(2024,1,31,23,59,59) < datetime.datetime(2023,12,31,23,0,0) :: ok :: False
datetime.datetime(2024,2,29,0,0,0) - datetime.datetime(2024,6,15,12,30,45,123456) :: ok :: TD(-108,41354,876544)
(datetime.datetime(2024,2,29,0,0,0) - datetime.datetime(2024,6,15,12,30,45,123456)).days :: ok :: -108
(datetime.datetime(2024,2,29,0,0,0) - datetime.datetime(2024,6,15,12,30,45,123456)).seconds :: ok :: 41354
datetime.datetime(2024,2,29,0,0,0) < datetime.datetime(2024,6,15,12,30,45,123456) :: ok :: True
datetime.datetime(2024,2,29,0,0,0) - datetime.datetime(2023,12,31,23,0,0) :: ok :: TD(59,3600,0)
(datetime.datetime(2024,2,29,0,0,0) - datetime.datetime(2023,12,31,23,0,0)).days :: ok :: 59
(datetime.datetime(2024,2,29,0,0,0) - datetime.datetime(2023,12,31,23,0,0)).seconds :: ok :: 3600
datetime.datetime(2024,2,29,0,0,0) < datetime.datetime(2023,12,31,23,0,0) :: ok :: False
datetime.datetime(2024,6,15,12,30,45,123456) - datetime.datetime(2023,12,31,23,0,0) :: ok :: TD(166,48645,123456)
(datetime.datetime(2024,6,15,12,30,45,123456) - datetime.datetime(2023,12,31,23,0,0)).days :: ok :: 166
(datetime.datetime(2024,6,15,12,30,45,123456) - datetime.datetime(2023,12,31,23,0,0)).seconds :: ok :: 48645
datetime.datetime(2024,6,15,12,30,45,123456) < datetime.datetime(2023,12,31,23,0,0) :: ok :: False
(datetime.date(2024,1,31) + relativedelta(days=1)).strftime('%Y-%m-%d') :: ok :: s:2024-02-01
(datetime.date(2024,1,31) + relativedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-01 00:00:00
str(datetime.date(2024,1,31) + relativedelta(days=1)) :: ok :: s:2024-02-01
(datetime.date(2024,1,31) + relativedelta(months=1)).strftime('%Y-%m-%d') :: ok :: s:2024-02-29
(datetime.date(2024,1,31) + relativedelta(months=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-29 00:00:00
str(datetime.date(2024,1,31) + relativedelta(months=1)) :: ok :: s:2024-02-29
(datetime.date(2024,1,31) + relativedelta(hours=24)).strftime('%Y-%m-%d') :: ok :: s:2024-02-01
(datetime.date(2024,1,31) + relativedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-01 00:00:00
str(datetime.date(2024,1,31) + relativedelta(hours=24)) :: ok :: s:2024-02-01
(datetime.date(2024,1,31) + relativedelta(hour=5)).strftime('%Y-%m-%d') :: ok :: s:2024-01-31
(datetime.date(2024,1,31) + relativedelta(hour=5)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-01-31 05:00:00
str(datetime.date(2024,1,31) + relativedelta(hour=5)) :: ok :: s:2024-01-31 05:00:00
(datetime.date(2024,1,31) + relativedelta(weekday=0)).strftime('%Y-%m-%d') :: ok :: s:2024-02-05
(datetime.date(2024,1,31) + relativedelta(weekday=0)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-05 00:00:00
str(datetime.date(2024,1,31) + relativedelta(weekday=0)) :: ok :: s:2024-02-05
(datetime.date(2024,1,31) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d') :: ok :: s:2024-02-28
(datetime.date(2024,1,31) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-28 00:00:00
str(datetime.date(2024,1,31) + relativedelta(months=1,days=-1)) :: ok :: s:2024-02-28
(datetime.date(2024,1,31) + relativedelta(years=1)).strftime('%Y-%m-%d') :: ok :: s:2025-01-31
(datetime.date(2024,1,31) + relativedelta(years=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2025-01-31 00:00:00
str(datetime.date(2024,1,31) + relativedelta(years=1)) :: ok :: s:2025-01-31
(datetime.date(2024,2,29) + relativedelta(days=1)).strftime('%Y-%m-%d') :: ok :: s:2024-03-01
(datetime.date(2024,2,29) + relativedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-01 00:00:00
str(datetime.date(2024,2,29) + relativedelta(days=1)) :: ok :: s:2024-03-01
(datetime.date(2024,2,29) + relativedelta(months=1)).strftime('%Y-%m-%d') :: ok :: s:2024-03-29
(datetime.date(2024,2,29) + relativedelta(months=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-29 00:00:00
str(datetime.date(2024,2,29) + relativedelta(months=1)) :: ok :: s:2024-03-29
(datetime.date(2024,2,29) + relativedelta(hours=24)).strftime('%Y-%m-%d') :: ok :: s:2024-03-01
(datetime.date(2024,2,29) + relativedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-01 00:00:00
str(datetime.date(2024,2,29) + relativedelta(hours=24)) :: ok :: s:2024-03-01
(datetime.date(2024,2,29) + relativedelta(hour=5)).strftime('%Y-%m-%d') :: ok :: s:2024-02-29
(datetime.date(2024,2,29) + relativedelta(hour=5)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-29 05:00:00
str(datetime.date(2024,2,29) + relativedelta(hour=5)) :: ok :: s:2024-02-29 05:00:00
(datetime.date(2024,2,29) + relativedelta(weekday=0)).strftime('%Y-%m-%d') :: ok :: s:2024-03-04
(datetime.date(2024,2,29) + relativedelta(weekday=0)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-04 00:00:00
str(datetime.date(2024,2,29) + relativedelta(weekday=0)) :: ok :: s:2024-03-04
(datetime.date(2024,2,29) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d') :: ok :: s:2024-03-28
(datetime.date(2024,2,29) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-28 00:00:00
str(datetime.date(2024,2,29) + relativedelta(months=1,days=-1)) :: ok :: s:2024-03-28
(datetime.date(2024,2,29) + relativedelta(years=1)).strftime('%Y-%m-%d') :: ok :: s:2025-02-28
(datetime.date(2024,2,29) + relativedelta(years=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2025-02-28 00:00:00
str(datetime.date(2024,2,29) + relativedelta(years=1)) :: ok :: s:2025-02-28
(datetime.date(2023,3,1) + relativedelta(days=1)).strftime('%Y-%m-%d') :: ok :: s:2023-03-02
(datetime.date(2023,3,1) + relativedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2023-03-02 00:00:00
str(datetime.date(2023,3,1) + relativedelta(days=1)) :: ok :: s:2023-03-02
(datetime.date(2023,3,1) + relativedelta(months=1)).strftime('%Y-%m-%d') :: ok :: s:2023-04-01
(datetime.date(2023,3,1) + relativedelta(months=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2023-04-01 00:00:00
str(datetime.date(2023,3,1) + relativedelta(months=1)) :: ok :: s:2023-04-01
(datetime.date(2023,3,1) + relativedelta(hours=24)).strftime('%Y-%m-%d') :: ok :: s:2023-03-02
(datetime.date(2023,3,1) + relativedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2023-03-02 00:00:00
str(datetime.date(2023,3,1) + relativedelta(hours=24)) :: ok :: s:2023-03-02
(datetime.date(2023,3,1) + relativedelta(hour=5)).strftime('%Y-%m-%d') :: ok :: s:2023-03-01
(datetime.date(2023,3,1) + relativedelta(hour=5)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2023-03-01 05:00:00
str(datetime.date(2023,3,1) + relativedelta(hour=5)) :: ok :: s:2023-03-01 05:00:00
(datetime.date(2023,3,1) + relativedelta(weekday=0)).strftime('%Y-%m-%d') :: ok :: s:2023-03-06
(datetime.date(2023,3,1) + relativedelta(weekday=0)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2023-03-06 00:00:00
str(datetime.date(2023,3,1) + relativedelta(weekday=0)) :: ok :: s:2023-03-06
(datetime.date(2023,3,1) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d') :: ok :: s:2023-03-31
(datetime.date(2023,3,1) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2023-03-31 00:00:00
str(datetime.date(2023,3,1) + relativedelta(months=1,days=-1)) :: ok :: s:2023-03-31
(datetime.date(2023,3,1) + relativedelta(years=1)).strftime('%Y-%m-%d') :: ok :: s:2024-03-01
(datetime.date(2023,3,1) + relativedelta(years=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-01 00:00:00
str(datetime.date(2023,3,1) + relativedelta(years=1)) :: ok :: s:2024-03-01
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=1)).strftime('%Y-%m-%d') :: ok :: s:2024-02-01
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-01 23:59:59
str(datetime.datetime(2024,1,31,23,59,59) + relativedelta(days=1)) :: ok :: s:2024-02-01 23:59:59
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1)).strftime('%Y-%m-%d') :: ok :: s:2024-02-29
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-29 23:59:59
str(datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1)) :: ok :: s:2024-02-29 23:59:59
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=24)).strftime('%Y-%m-%d') :: ok :: s:2024-02-01
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-01 23:59:59
str(datetime.datetime(2024,1,31,23,59,59) + relativedelta(hours=24)) :: ok :: s:2024-02-01 23:59:59
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(hour=5)).strftime('%Y-%m-%d') :: ok :: s:2024-01-31
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(hour=5)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-01-31 05:59:59
str(datetime.datetime(2024,1,31,23,59,59) + relativedelta(hour=5)) :: ok :: s:2024-01-31 05:59:59
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=0)).strftime('%Y-%m-%d') :: ok :: s:2024-02-05
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=0)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-05 23:59:59
str(datetime.datetime(2024,1,31,23,59,59) + relativedelta(weekday=0)) :: ok :: s:2024-02-05 23:59:59
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d') :: ok :: s:2024-02-28
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-28 23:59:59
str(datetime.datetime(2024,1,31,23,59,59) + relativedelta(months=1,days=-1)) :: ok :: s:2024-02-28 23:59:59
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(years=1)).strftime('%Y-%m-%d') :: ok :: s:2025-01-31
(datetime.datetime(2024,1,31,23,59,59) + relativedelta(years=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2025-01-31 23:59:59
str(datetime.datetime(2024,1,31,23,59,59) + relativedelta(years=1)) :: ok :: s:2025-01-31 23:59:59
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=1)).strftime('%Y-%m-%d') :: ok :: s:2024-03-01
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-01 00:00:00
str(datetime.datetime(2024,2,29,0,0,0) + relativedelta(days=1)) :: ok :: s:2024-03-01 00:00:00
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1)).strftime('%Y-%m-%d') :: ok :: s:2024-03-29
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-29 00:00:00
str(datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1)) :: ok :: s:2024-03-29 00:00:00
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=24)).strftime('%Y-%m-%d') :: ok :: s:2024-03-01
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-01 00:00:00
str(datetime.datetime(2024,2,29,0,0,0) + relativedelta(hours=24)) :: ok :: s:2024-03-01 00:00:00
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(hour=5)).strftime('%Y-%m-%d') :: ok :: s:2024-02-29
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(hour=5)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-02-29 05:00:00
str(datetime.datetime(2024,2,29,0,0,0) + relativedelta(hour=5)) :: ok :: s:2024-02-29 05:00:00
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=0)).strftime('%Y-%m-%d') :: ok :: s:2024-03-04
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=0)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-04 00:00:00
str(datetime.datetime(2024,2,29,0,0,0) + relativedelta(weekday=0)) :: ok :: s:2024-03-04 00:00:00
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d') :: ok :: s:2024-03-28
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1,days=-1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2024-03-28 00:00:00
str(datetime.datetime(2024,2,29,0,0,0) + relativedelta(months=1,days=-1)) :: ok :: s:2024-03-28 00:00:00
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(years=1)).strftime('%Y-%m-%d') :: ok :: s:2025-02-28
(datetime.datetime(2024,2,29,0,0,0) + relativedelta(years=1)).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:2025-02-28 00:00:00
str(datetime.datetime(2024,2,29,0,0,0) + relativedelta(years=1)) :: ok :: s:2025-02-28 00:00:00
datetime.timedelta(days=1) :: ok :: TD(1,0,0)
datetime.timedelta(days=1).days :: ok :: 1
datetime.timedelta(days=1).seconds :: ok :: 0
bool(datetime.timedelta(days=1)) :: ok :: True
datetime.timedelta(days=-1) :: ok :: TD(-1,0,0)
datetime.timedelta(days=-1).days :: ok :: -1
datetime.timedelta(days=-1).seconds :: ok :: 0
bool(datetime.timedelta(days=-1)) :: ok :: True
datetime.timedelta(hours=25) :: ok :: TD(1,3600,0)
datetime.timedelta(hours=25).days :: ok :: 1
datetime.timedelta(hours=25).seconds :: ok :: 3600
bool(datetime.timedelta(hours=25)) :: ok :: True
datetime.timedelta(hours=-25) :: ok :: TD(-2,82800,0)
datetime.timedelta(hours=-25).days :: ok :: -2
datetime.timedelta(hours=-25).seconds :: ok :: 82800
bool(datetime.timedelta(hours=-25)) :: ok :: True
datetime.timedelta(seconds=90061) :: ok :: TD(1,3661,0)
datetime.timedelta(seconds=90061).days :: ok :: 1
datetime.timedelta(seconds=90061).seconds :: ok :: 3661
bool(datetime.timedelta(seconds=90061)) :: ok :: True
datetime.timedelta(microseconds=-1) :: ok :: TD(-1,86399,999999)
datetime.timedelta(microseconds=-1).days :: ok :: -1
datetime.timedelta(microseconds=-1).seconds :: ok :: 86399
bool(datetime.timedelta(microseconds=-1)) :: ok :: True
datetime.timedelta(days=1,hours=-25) :: ok :: TD(-1,82800,0)
datetime.timedelta(days=1,hours=-25).days :: ok :: -1
datetime.timedelta(days=1,hours=-25).seconds :: ok :: 82800
bool(datetime.timedelta(days=1,hours=-25)) :: ok :: True
datetime.timedelta(weeks=1) :: ok :: TD(7,0,0)
datetime.timedelta(weeks=1).days :: ok :: 7
datetime.timedelta(weeks=1).seconds :: ok :: 0
bool(datetime.timedelta(weeks=1)) :: ok :: True
datetime.timedelta(milliseconds=1500) :: ok :: TD(0,1,500000)
datetime.timedelta(milliseconds=1500).days :: ok :: 0
datetime.timedelta(milliseconds=1500).seconds :: ok :: 1
bool(datetime.timedelta(milliseconds=1500)) :: ok :: True
datetime.timedelta(days=0.5) :: ok :: TD(0,43200,0)
datetime.timedelta(days=0.5).days :: ok :: 0
datetime.timedelta(days=0.5).seconds :: ok :: 43200
bool(datetime.timedelta(days=0.5)) :: ok :: True
datetime.timedelta(seconds=-0.5) :: ok :: TD(-1,86399,500000)
datetime.timedelta(seconds=-0.5).days :: ok :: -1
datetime.timedelta(seconds=-0.5).seconds :: ok :: 86399
bool(datetime.timedelta(seconds=-0.5)) :: ok :: True
datetime.timedelta(days=1) + datetime.timedelta(days=-1) :: ok :: TD(0,0,0)
datetime.timedelta(days=1) - datetime.timedelta(days=-1) :: ok :: TD(2,0,0)
datetime.timedelta(days=1) < datetime.timedelta(days=-1) :: ok :: False
datetime.timedelta(days=1) == datetime.timedelta(days=-1) :: ok :: False
datetime.timedelta(days=1) + datetime.timedelta(hours=25) :: ok :: TD(2,3600,0)
datetime.timedelta(days=1) - datetime.timedelta(hours=25) :: ok :: TD(-1,82800,0)
datetime.timedelta(days=1) < datetime.timedelta(hours=25) :: ok :: True
datetime.timedelta(days=1) == datetime.timedelta(hours=25) :: ok :: False
datetime.timedelta(days=1) + datetime.timedelta(hours=-25) :: ok :: TD(-1,82800,0)
datetime.timedelta(days=1) - datetime.timedelta(hours=-25) :: ok :: TD(2,3600,0)
datetime.timedelta(days=1) < datetime.timedelta(hours=-25) :: ok :: False
datetime.timedelta(days=1) == datetime.timedelta(hours=-25) :: ok :: False
datetime.timedelta(days=1) + datetime.timedelta(seconds=90061) :: ok :: TD(2,3661,0)
datetime.timedelta(days=1) - datetime.timedelta(seconds=90061) :: ok :: TD(-1,82739,0)
datetime.timedelta(days=1) < datetime.timedelta(seconds=90061) :: ok :: True
datetime.timedelta(days=1) == datetime.timedelta(seconds=90061) :: ok :: False
datetime.timedelta(days=1) + datetime.timedelta(microseconds=-1) :: ok :: TD(0,86399,999999)
datetime.timedelta(days=1) - datetime.timedelta(microseconds=-1) :: ok :: TD(1,0,1)
datetime.timedelta(days=1) < datetime.timedelta(microseconds=-1) :: ok :: False
datetime.timedelta(days=1) == datetime.timedelta(microseconds=-1) :: ok :: False
datetime.timedelta(days=-1) + datetime.timedelta(hours=25) :: ok :: TD(0,3600,0)
datetime.timedelta(days=-1) - datetime.timedelta(hours=25) :: ok :: TD(-3,82800,0)
datetime.timedelta(days=-1) < datetime.timedelta(hours=25) :: ok :: True
datetime.timedelta(days=-1) == datetime.timedelta(hours=25) :: ok :: False
datetime.timedelta(days=-1) + datetime.timedelta(hours=-25) :: ok :: TD(-3,82800,0)
datetime.timedelta(days=-1) - datetime.timedelta(hours=-25) :: ok :: TD(0,3600,0)
datetime.timedelta(days=-1) < datetime.timedelta(hours=-25) :: ok :: False
datetime.timedelta(days=-1) == datetime.timedelta(hours=-25) :: ok :: False
datetime.timedelta(days=-1) + datetime.timedelta(seconds=90061) :: ok :: TD(0,3661,0)
datetime.timedelta(days=-1) - datetime.timedelta(seconds=90061) :: ok :: TD(-3,82739,0)
datetime.timedelta(days=-1) < datetime.timedelta(seconds=90061) :: ok :: True
datetime.timedelta(days=-1) == datetime.timedelta(seconds=90061) :: ok :: False
datetime.timedelta(days=-1) + datetime.timedelta(microseconds=-1) :: ok :: TD(-2,86399,999999)
datetime.timedelta(days=-1) - datetime.timedelta(microseconds=-1) :: ok :: TD(-1,0,1)
datetime.timedelta(days=-1) < datetime.timedelta(microseconds=-1) :: ok :: True
datetime.timedelta(days=-1) == datetime.timedelta(microseconds=-1) :: ok :: False
datetime.timedelta(hours=25) + datetime.timedelta(hours=-25) :: ok :: TD(0,0,0)
datetime.timedelta(hours=25) - datetime.timedelta(hours=-25) :: ok :: TD(2,7200,0)
datetime.timedelta(hours=25) < datetime.timedelta(hours=-25) :: ok :: False
datetime.timedelta(hours=25) == datetime.timedelta(hours=-25) :: ok :: False
datetime.timedelta(hours=25) + datetime.timedelta(seconds=90061) :: ok :: TD(2,7261,0)
datetime.timedelta(hours=25) - datetime.timedelta(seconds=90061) :: ok :: TD(-1,86339,0)
datetime.timedelta(hours=25) < datetime.timedelta(seconds=90061) :: ok :: True
datetime.timedelta(hours=25) == datetime.timedelta(seconds=90061) :: ok :: False
datetime.timedelta(hours=25) + datetime.timedelta(microseconds=-1) :: ok :: TD(1,3599,999999)
datetime.timedelta(hours=25) - datetime.timedelta(microseconds=-1) :: ok :: TD(1,3600,1)
datetime.timedelta(hours=25) < datetime.timedelta(microseconds=-1) :: ok :: False
datetime.timedelta(hours=25) == datetime.timedelta(microseconds=-1) :: ok :: False
datetime.timedelta(hours=-25) + datetime.timedelta(seconds=90061) :: ok :: TD(0,61,0)
datetime.timedelta(hours=-25) - datetime.timedelta(seconds=90061) :: ok :: TD(-3,79139,0)
datetime.timedelta(hours=-25) < datetime.timedelta(seconds=90061) :: ok :: True
datetime.timedelta(hours=-25) == datetime.timedelta(seconds=90061) :: ok :: False
datetime.timedelta(hours=-25) + datetime.timedelta(microseconds=-1) :: ok :: TD(-2,82799,999999)
datetime.timedelta(hours=-25) - datetime.timedelta(microseconds=-1) :: ok :: TD(-2,82800,1)
datetime.timedelta(hours=-25) < datetime.timedelta(microseconds=-1) :: ok :: True
datetime.timedelta(hours=-25) == datetime.timedelta(microseconds=-1) :: ok :: False
datetime.timedelta(seconds=90061) + datetime.timedelta(microseconds=-1) :: ok :: TD(1,3660,999999)
datetime.timedelta(seconds=90061) - datetime.timedelta(microseconds=-1) :: ok :: TD(1,3661,1)
datetime.timedelta(seconds=90061) < datetime.timedelta(microseconds=-1) :: ok :: False
datetime.timedelta(seconds=90061) == datetime.timedelta(microseconds=-1) :: ok :: False
str(datetime.time(0,0,0)) :: ok :: s:00:00:00
datetime.time(0,0,0).hour :: ok :: 0
bool(datetime.time(0,0,0)) :: ok :: True
datetime.time(0,0,0).strftime('%Y-%m-%d') :: ok :: s:1900-01-01
datetime.time(0,0,0).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:1900-01-01 00:00:00
datetime.time(0,0,0).strftime('%d/%m/%Y') :: ok :: s:01/01/1900
datetime.time(0,0,0).strftime('%H:%M:%S') :: ok :: s:00:00:00
datetime.time(0,0,0).strftime('%j') :: ok :: s:001
datetime.time(0,0,0).strftime('%U') :: ok :: s:00
datetime.time(0,0,0).strftime('%W') :: ok :: s:01
datetime.time(0,0,0).strftime('%w') :: ok :: s:1
datetime.time(0,0,0).strftime('%a') :: ok :: s:Mon
datetime.time(0,0,0).strftime('%A') :: ok :: s:Monday
datetime.time(0,0,0).strftime('%b') :: ok :: s:Jan
datetime.time(0,0,0).strftime('%B') :: ok :: s:January
datetime.time(0,0,0).strftime('%p') :: ok :: s:AM
datetime.time(0,0,0).strftime('%I') :: ok :: s:12
datetime.time(0,0,0).strftime('%y') :: ok :: s:00
datetime.time(0,0,0).strftime('%m') :: ok :: s:01
datetime.time(0,0,0).strftime('%d') :: ok :: s:01
datetime.time(0,0,0).strftime('%f') :: ok :: s:000000
datetime.time(0,0,0).strftime('%%') :: ok :: s:%
datetime.time(0,0,0).strftime('%Y-%j') :: ok :: s:1900-001
datetime.time(0,0,0).strftime('%c') :: ok :: s:Mon Jan  1 00:00:00 1900
datetime.time(0,0,0).strftime('%x') :: ok :: s:01/01/00
datetime.time(0,0,0).strftime('%X') :: ok :: s:00:00:00
str(datetime.time(12,30,45)) :: ok :: s:12:30:45
datetime.time(12,30,45).hour :: ok :: 12
bool(datetime.time(12,30,45)) :: ok :: True
datetime.time(12,30,45).strftime('%Y-%m-%d') :: ok :: s:1900-01-01
datetime.time(12,30,45).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:1900-01-01 12:30:45
datetime.time(12,30,45).strftime('%d/%m/%Y') :: ok :: s:01/01/1900
datetime.time(12,30,45).strftime('%H:%M:%S') :: ok :: s:12:30:45
datetime.time(12,30,45).strftime('%j') :: ok :: s:001
datetime.time(12,30,45).strftime('%U') :: ok :: s:00
datetime.time(12,30,45).strftime('%W') :: ok :: s:01
datetime.time(12,30,45).strftime('%w') :: ok :: s:1
datetime.time(12,30,45).strftime('%a') :: ok :: s:Mon
datetime.time(12,30,45).strftime('%A') :: ok :: s:Monday
datetime.time(12,30,45).strftime('%b') :: ok :: s:Jan
datetime.time(12,30,45).strftime('%B') :: ok :: s:January
datetime.time(12,30,45).strftime('%p') :: ok :: s:PM
datetime.time(12,30,45).strftime('%I') :: ok :: s:12
datetime.time(12,30,45).strftime('%y') :: ok :: s:00
datetime.time(12,30,45).strftime('%m') :: ok :: s:01
datetime.time(12,30,45).strftime('%d') :: ok :: s:01
datetime.time(12,30,45).strftime('%f') :: ok :: s:000000
datetime.time(12,30,45).strftime('%%') :: ok :: s:%
datetime.time(12,30,45).strftime('%Y-%j') :: ok :: s:1900-001
datetime.time(12,30,45).strftime('%c') :: ok :: s:Mon Jan  1 12:30:45 1900
datetime.time(12,30,45).strftime('%x') :: ok :: s:01/01/00
datetime.time(12,30,45).strftime('%X') :: ok :: s:12:30:45
str(datetime.time(23,59,59)) :: ok :: s:23:59:59
datetime.time(23,59,59).hour :: ok :: 23
bool(datetime.time(23,59,59)) :: ok :: True
datetime.time(23,59,59).strftime('%Y-%m-%d') :: ok :: s:1900-01-01
datetime.time(23,59,59).strftime('%Y-%m-%d %H:%M:%S') :: ok :: s:1900-01-01 23:59:59
datetime.time(23,59,59).strftime('%d/%m/%Y') :: ok :: s:01/01/1900
datetime.time(23,59,59).strftime('%H:%M:%S') :: ok :: s:23:59:59
datetime.time(23,59,59).strftime('%j') :: ok :: s:001
datetime.time(23,59,59).strftime('%U') :: ok :: s:00
datetime.time(23,59,59).strftime('%W') :: ok :: s:01
datetime.time(23,59,59).strftime('%w') :: ok :: s:1
datetime.time(23,59,59).strftime('%a') :: ok :: s:Mon
datetime.time(23,59,59).strftime('%A') :: ok :: s:Monday
datetime.time(23,59,59).strftime('%b') :: ok :: s:Jan
datetime.time(23,59,59).strftime('%B') :: ok :: s:January
datetime.time(23,59,59).strftime('%p') :: ok :: s:PM
datetime.time(23,59,59).strftime('%I') :: ok :: s:11
datetime.time(23,59,59).strftime('%y') :: ok :: s:00
datetime.time(23,59,59).strftime('%m') :: ok :: s:01
datetime.time(23,59,59).strftime('%d') :: ok :: s:01
datetime.time(23,59,59).strftime('%f') :: ok :: s:000000
datetime.time(23,59,59).strftime('%%') :: ok :: s:%
datetime.time(23,59,59).strftime('%Y-%j') :: ok :: s:1900-001
datetime.time(23,59,59).strftime('%c') :: ok :: s:Mon Jan  1 23:59:59 1900
datetime.time(23,59,59).strftime('%x') :: ok :: s:01/01/00
datetime.time(23,59,59).strftime('%X') :: ok :: s:23:59:59
datetime.date(2024,1,31) + relativedelta(months=1.5) :: err
datetime.date(2024,1,31) + relativedelta(years=1.5) :: err
datetime.date(2024,1,31) + relativedelta(yearday=400) :: err
datetime.date(2024,1,31) + relativedelta(weekday=7) :: err
datetime.date(2024,1,31) + relativedelta(weekday=-1) :: ok :: D(2024-02-04)
datetime.date(2024,1,31) + relativedelta(month=13) :: err
datetime.date(2024,1,31) + relativedelta(hour=24) :: err
datetime.date(2024,1,31) + relativedelta(minute=60) :: err
datetime.date(2024,1,31) + relativedelta(second=60) :: err
datetime.date(2024,1,31) + relativedelta(microsecond=1000000) :: err
datetime.date(2024,1,31) + relativedelta(weekday=7) :: err
datetime.date(2024,1,31) + relativedelta(weekday=-8) :: err
datetime.date(2024,1,31) + relativedelta(months=1.0000001) :: err
datetime.date(2024,1,31) + relativedelta(months=2.0) :: ok :: D(2024-03-31)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(months=2.0) :: ok :: DT(2024-03-31 06:00:00.000000)
datetime.date(2024,1,31) + relativedelta(years=-1.0) :: ok :: D(2023-01-31)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(years=-1.0) :: ok :: DT(2023-01-31 06:00:00.000000)
datetime.date(2024,1,31) + relativedelta(days=1.5) :: ok :: D(2024-02-01)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(days=1.5) :: ok :: DT(2024-02-01 18:00:00.000000)
datetime.date(2024,1,31) + relativedelta(hours=1.5) :: ok :: DT(2024-01-31 01:30:00.000000)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(hours=1.5) :: ok :: DT(2024-01-31 07:30:00.000000)
datetime.date(2024,1,31) + relativedelta(weeks=0.5) :: ok :: D(2024-02-03)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(weeks=0.5) :: ok :: DT(2024-02-03 18:00:00.000000)
datetime.date(2024,1,31) + relativedelta(hours=24) :: ok :: D(2024-02-01)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(hours=24) :: ok :: DT(2024-02-01 06:00:00.000000)
datetime.date(2024,1,31) + relativedelta(hours=-24) :: ok :: D(2024-01-30)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(hours=-24) :: ok :: DT(2024-01-30 06:00:00.000000)
datetime.date(2024,1,31) + relativedelta(minutes=1440) :: ok :: D(2024-02-01)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(minutes=1440) :: ok :: DT(2024-02-01 06:00:00.000000)
datetime.date(2024,1,31) + relativedelta(microseconds=86400000000) :: ok :: D(2024-02-01)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(microseconds=86400000000) :: ok :: DT(2024-02-01 06:00:00.000000)
datetime.date(2024,1,31) + relativedelta(seconds=59) :: ok :: DT(2024-01-31 00:00:59.000000)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(seconds=59) :: ok :: DT(2024-01-31 06:00:59.000000)
datetime.date(2024,1,31) + relativedelta(hours=23) :: ok :: DT(2024-01-31 23:00:00.000000)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(hours=23) :: ok :: DT(2024-02-01 05:00:00.000000)
datetime.date(2024,1,31) + relativedelta(months=11) :: ok :: D(2024-12-31)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(months=11) :: ok :: DT(2024-12-31 06:00:00.000000)
datetime.date(2024,1,31) + relativedelta(months=12) :: ok :: D(2025-01-31)
datetime.datetime(2024,1,31,6,0,0) + relativedelta(months=12) :: ok :: DT(2025-01-31 06:00:00.000000)
datetime.date(2024,1,31).replace(day=1) :: ok :: D(2024-01-01)
str(datetime.date(2024,1,31).replace(day=1)) :: ok :: s:2024-01-01
datetime.date(2024,1,31).replace(month=1) :: ok :: D(2024-01-31)
str(datetime.date(2024,1,31).replace(month=1)) :: ok :: s:2024-01-31
datetime.date(2024,1,31).replace(year=2000) :: ok :: D(2000-01-31)
str(datetime.date(2024,1,31).replace(year=2000)) :: ok :: s:2000-01-31
datetime.date(2024,1,31).replace(day=1,month=2) :: ok :: D(2024-02-01)
str(datetime.date(2024,1,31).replace(day=1,month=2)) :: ok :: s:2024-02-01
datetime.date(2024,1,31).replace(year=2023,month=2,day=28) :: ok :: D(2023-02-28)
str(datetime.date(2024,1,31).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28
datetime.date(2024,1,31).replace(day=31) :: ok :: D(2024-01-31)
str(datetime.date(2024,1,31).replace(day=31)) :: ok :: s:2024-01-31
datetime.date(2024,1,31).replace(month=2,day=30) :: err
str(datetime.date(2024,1,31).replace(month=2,day=30)) :: err
datetime.date(2024,1,31).replace(month=13) :: err
str(datetime.date(2024,1,31).replace(month=13)) :: err
datetime.date(2024,1,31).replace(day=0) :: err
str(datetime.date(2024,1,31).replace(day=0)) :: err
datetime.date(2024,1,31).replace(year=0) :: err
str(datetime.date(2024,1,31).replace(year=0)) :: err
datetime.date(2024,2,29).replace(day=1) :: ok :: D(2024-02-01)
str(datetime.date(2024,2,29).replace(day=1)) :: ok :: s:2024-02-01
datetime.date(2024,2,29).replace(month=1) :: ok :: D(2024-01-29)
str(datetime.date(2024,2,29).replace(month=1)) :: ok :: s:2024-01-29
datetime.date(2024,2,29).replace(year=2000) :: ok :: D(2000-02-29)
str(datetime.date(2024,2,29).replace(year=2000)) :: ok :: s:2000-02-29
datetime.date(2024,2,29).replace(day=1,month=2) :: ok :: D(2024-02-01)
str(datetime.date(2024,2,29).replace(day=1,month=2)) :: ok :: s:2024-02-01
datetime.date(2024,2,29).replace(year=2023,month=2,day=28) :: ok :: D(2023-02-28)
str(datetime.date(2024,2,29).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28
datetime.date(2024,2,29).replace(day=31) :: err
str(datetime.date(2024,2,29).replace(day=31)) :: err
datetime.date(2024,2,29).replace(month=2,day=30) :: err
str(datetime.date(2024,2,29).replace(month=2,day=30)) :: err
datetime.date(2024,2,29).replace(month=13) :: err
str(datetime.date(2024,2,29).replace(month=13)) :: err
datetime.date(2024,2,29).replace(day=0) :: err
str(datetime.date(2024,2,29).replace(day=0)) :: err
datetime.date(2024,2,29).replace(year=0) :: err
str(datetime.date(2024,2,29).replace(year=0)) :: err
datetime.date(2023,3,1).replace(day=1) :: ok :: D(2023-03-01)
str(datetime.date(2023,3,1).replace(day=1)) :: ok :: s:2023-03-01
datetime.date(2023,3,1).replace(month=1) :: ok :: D(2023-01-01)
str(datetime.date(2023,3,1).replace(month=1)) :: ok :: s:2023-01-01
datetime.date(2023,3,1).replace(year=2000) :: ok :: D(2000-03-01)
str(datetime.date(2023,3,1).replace(year=2000)) :: ok :: s:2000-03-01
datetime.date(2023,3,1).replace(day=1,month=2) :: ok :: D(2023-02-01)
str(datetime.date(2023,3,1).replace(day=1,month=2)) :: ok :: s:2023-02-01
datetime.date(2023,3,1).replace(year=2023,month=2,day=28) :: ok :: D(2023-02-28)
str(datetime.date(2023,3,1).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28
datetime.date(2023,3,1).replace(day=31) :: ok :: D(2023-03-31)
str(datetime.date(2023,3,1).replace(day=31)) :: ok :: s:2023-03-31
datetime.date(2023,3,1).replace(month=2,day=30) :: err
str(datetime.date(2023,3,1).replace(month=2,day=30)) :: err
datetime.date(2023,3,1).replace(month=13) :: err
str(datetime.date(2023,3,1).replace(month=13)) :: err
datetime.date(2023,3,1).replace(day=0) :: err
str(datetime.date(2023,3,1).replace(day=0)) :: err
datetime.date(2023,3,1).replace(year=0) :: err
str(datetime.date(2023,3,1).replace(year=0)) :: err
datetime.date(2024,12,31).replace(day=1) :: ok :: D(2024-12-01)
str(datetime.date(2024,12,31).replace(day=1)) :: ok :: s:2024-12-01
datetime.date(2024,12,31).replace(month=1) :: ok :: D(2024-01-31)
str(datetime.date(2024,12,31).replace(month=1)) :: ok :: s:2024-01-31
datetime.date(2024,12,31).replace(year=2000) :: ok :: D(2000-12-31)
str(datetime.date(2024,12,31).replace(year=2000)) :: ok :: s:2000-12-31
datetime.date(2024,12,31).replace(day=1,month=2) :: ok :: D(2024-02-01)
str(datetime.date(2024,12,31).replace(day=1,month=2)) :: ok :: s:2024-02-01
datetime.date(2024,12,31).replace(year=2023,month=2,day=28) :: ok :: D(2023-02-28)
str(datetime.date(2024,12,31).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28
datetime.date(2024,12,31).replace(day=31) :: ok :: D(2024-12-31)
str(datetime.date(2024,12,31).replace(day=31)) :: ok :: s:2024-12-31
datetime.date(2024,12,31).replace(month=2,day=30) :: err
str(datetime.date(2024,12,31).replace(month=2,day=30)) :: err
datetime.date(2024,12,31).replace(month=13) :: err
str(datetime.date(2024,12,31).replace(month=13)) :: err
datetime.date(2024,12,31).replace(day=0) :: err
str(datetime.date(2024,12,31).replace(day=0)) :: err
datetime.date(2024,12,31).replace(year=0) :: err
str(datetime.date(2024,12,31).replace(year=0)) :: err
datetime.date(2000,2,29).replace(day=1) :: ok :: D(2000-02-01)
str(datetime.date(2000,2,29).replace(day=1)) :: ok :: s:2000-02-01
datetime.date(2000,2,29).replace(month=1) :: ok :: D(2000-01-29)
str(datetime.date(2000,2,29).replace(month=1)) :: ok :: s:2000-01-29
datetime.date(2000,2,29).replace(year=2000) :: ok :: D(2000-02-29)
str(datetime.date(2000,2,29).replace(year=2000)) :: ok :: s:2000-02-29
datetime.date(2000,2,29).replace(day=1,month=2) :: ok :: D(2000-02-01)
str(datetime.date(2000,2,29).replace(day=1,month=2)) :: ok :: s:2000-02-01
datetime.date(2000,2,29).replace(year=2023,month=2,day=28) :: ok :: D(2023-02-28)
str(datetime.date(2000,2,29).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28
datetime.date(2000,2,29).replace(day=31) :: err
str(datetime.date(2000,2,29).replace(day=31)) :: err
datetime.date(2000,2,29).replace(month=2,day=30) :: err
str(datetime.date(2000,2,29).replace(month=2,day=30)) :: err
datetime.date(2000,2,29).replace(month=13) :: err
str(datetime.date(2000,2,29).replace(month=13)) :: err
datetime.date(2000,2,29).replace(day=0) :: err
str(datetime.date(2000,2,29).replace(day=0)) :: err
datetime.date(2000,2,29).replace(year=0) :: err
str(datetime.date(2000,2,29).replace(year=0)) :: err
datetime.date(2024,3,31).replace(day=1) :: ok :: D(2024-03-01)
str(datetime.date(2024,3,31).replace(day=1)) :: ok :: s:2024-03-01
datetime.date(2024,3,31).replace(month=1) :: ok :: D(2024-01-31)
str(datetime.date(2024,3,31).replace(month=1)) :: ok :: s:2024-01-31
datetime.date(2024,3,31).replace(year=2000) :: ok :: D(2000-03-31)
str(datetime.date(2024,3,31).replace(year=2000)) :: ok :: s:2000-03-31
datetime.date(2024,3,31).replace(day=1,month=2) :: ok :: D(2024-02-01)
str(datetime.date(2024,3,31).replace(day=1,month=2)) :: ok :: s:2024-02-01
datetime.date(2024,3,31).replace(year=2023,month=2,day=28) :: ok :: D(2023-02-28)
str(datetime.date(2024,3,31).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28
datetime.date(2024,3,31).replace(day=31) :: ok :: D(2024-03-31)
str(datetime.date(2024,3,31).replace(day=31)) :: ok :: s:2024-03-31
datetime.date(2024,3,31).replace(month=2,day=30) :: err
str(datetime.date(2024,3,31).replace(month=2,day=30)) :: err
datetime.date(2024,3,31).replace(month=13) :: err
str(datetime.date(2024,3,31).replace(month=13)) :: err
datetime.date(2024,3,31).replace(day=0) :: err
str(datetime.date(2024,3,31).replace(day=0)) :: err
datetime.date(2024,3,31).replace(year=0) :: err
str(datetime.date(2024,3,31).replace(year=0)) :: err
datetime.date(2021,5,17).replace(day=1) :: ok :: D(2021-05-01)
str(datetime.date(2021,5,17).replace(day=1)) :: ok :: s:2021-05-01
datetime.date(2021,5,17).replace(month=1) :: ok :: D(2021-01-17)
str(datetime.date(2021,5,17).replace(month=1)) :: ok :: s:2021-01-17
datetime.date(2021,5,17).replace(year=2000) :: ok :: D(2000-05-17)
str(datetime.date(2021,5,17).replace(year=2000)) :: ok :: s:2000-05-17
datetime.date(2021,5,17).replace(day=1,month=2) :: ok :: D(2021-02-01)
str(datetime.date(2021,5,17).replace(day=1,month=2)) :: ok :: s:2021-02-01
datetime.date(2021,5,17).replace(year=2023,month=2,day=28) :: ok :: D(2023-02-28)
str(datetime.date(2021,5,17).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28
datetime.date(2021,5,17).replace(day=31) :: ok :: D(2021-05-31)
str(datetime.date(2021,5,17).replace(day=31)) :: ok :: s:2021-05-31
datetime.date(2021,5,17).replace(month=2,day=30) :: err
str(datetime.date(2021,5,17).replace(month=2,day=30)) :: err
datetime.date(2021,5,17).replace(month=13) :: err
str(datetime.date(2021,5,17).replace(month=13)) :: err
datetime.date(2021,5,17).replace(day=0) :: err
str(datetime.date(2021,5,17).replace(day=0)) :: err
datetime.date(2021,5,17).replace(year=0) :: err
str(datetime.date(2021,5,17).replace(year=0)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(day=1) :: ok :: DT(2024-01-01 23:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(day=1)) :: ok :: s:2024-01-01 23:59:59
datetime.datetime(2024,1,31,23,59,59).replace(month=1) :: ok :: DT(2024-01-31 23:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(month=1)) :: ok :: s:2024-01-31 23:59:59
datetime.datetime(2024,1,31,23,59,59).replace(year=2000) :: ok :: DT(2000-01-31 23:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(year=2000)) :: ok :: s:2000-01-31 23:59:59
datetime.datetime(2024,1,31,23,59,59).replace(day=1,month=2) :: ok :: DT(2024-02-01 23:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(day=1,month=2)) :: ok :: s:2024-02-01 23:59:59
datetime.datetime(2024,1,31,23,59,59).replace(year=2023,month=2,day=28) :: ok :: DT(2023-02-28 23:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28 23:59:59
datetime.datetime(2024,1,31,23,59,59).replace(day=31) :: ok :: DT(2024-01-31 23:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(day=31)) :: ok :: s:2024-01-31 23:59:59
datetime.datetime(2024,1,31,23,59,59).replace(month=2,day=30) :: err
str(datetime.datetime(2024,1,31,23,59,59).replace(month=2,day=30)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(month=13) :: err
str(datetime.datetime(2024,1,31,23,59,59).replace(month=13)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(day=0) :: err
str(datetime.datetime(2024,1,31,23,59,59).replace(day=0)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(year=0) :: err
str(datetime.datetime(2024,1,31,23,59,59).replace(year=0)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(hour=0) :: ok :: DT(2024-01-31 00:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(hour=0)) :: ok :: s:2024-01-31 00:59:59
datetime.datetime(2024,1,31,23,59,59).replace(hour=0,minute=0,second=0) :: ok :: DT(2024-01-31 00:00:00.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(hour=0,minute=0,second=0)) :: ok :: s:2024-01-31 00:00:00
datetime.datetime(2024,1,31,23,59,59).replace(microsecond=0) :: ok :: DT(2024-01-31 23:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(microsecond=0)) :: ok :: s:2024-01-31 23:59:59
datetime.datetime(2024,1,31,23,59,59).replace(hour=23,minute=59,second=59) :: ok :: DT(2024-01-31 23:59:59.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(hour=23,minute=59,second=59)) :: ok :: s:2024-01-31 23:59:59
datetime.datetime(2024,1,31,23,59,59).replace(hour=24) :: err
str(datetime.datetime(2024,1,31,23,59,59).replace(hour=24)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(minute=60) :: err
str(datetime.datetime(2024,1,31,23,59,59).replace(minute=60)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(second=-1) :: err
str(datetime.datetime(2024,1,31,23,59,59).replace(second=-1)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(microsecond=1000000) :: err
str(datetime.datetime(2024,1,31,23,59,59).replace(microsecond=1000000)) :: err
datetime.datetime(2024,1,31,23,59,59).replace(year=2020,month=6,day=1,hour=1,minute=2,second=3) :: ok :: DT(2020-06-01 01:02:03.000000)
str(datetime.datetime(2024,1,31,23,59,59).replace(year=2020,month=6,day=1,hour=1,minute=2,second=3)) :: ok :: s:2020-06-01 01:02:03
datetime.datetime(2024,2,29,0,0,0).replace(day=1) :: ok :: DT(2024-02-01 00:00:00.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(day=1)) :: ok :: s:2024-02-01 00:00:00
datetime.datetime(2024,2,29,0,0,0).replace(month=1) :: ok :: DT(2024-01-29 00:00:00.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(month=1)) :: ok :: s:2024-01-29 00:00:00
datetime.datetime(2024,2,29,0,0,0).replace(year=2000) :: ok :: DT(2000-02-29 00:00:00.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(year=2000)) :: ok :: s:2000-02-29 00:00:00
datetime.datetime(2024,2,29,0,0,0).replace(day=1,month=2) :: ok :: DT(2024-02-01 00:00:00.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(day=1,month=2)) :: ok :: s:2024-02-01 00:00:00
datetime.datetime(2024,2,29,0,0,0).replace(year=2023,month=2,day=28) :: ok :: DT(2023-02-28 00:00:00.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28 00:00:00
datetime.datetime(2024,2,29,0,0,0).replace(day=31) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(day=31)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(month=2,day=30) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(month=2,day=30)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(month=13) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(month=13)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(day=0) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(day=0)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(year=0) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(year=0)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(hour=0) :: ok :: DT(2024-02-29 00:00:00.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(hour=0)) :: ok :: s:2024-02-29 00:00:00
datetime.datetime(2024,2,29,0,0,0).replace(hour=0,minute=0,second=0) :: ok :: DT(2024-02-29 00:00:00.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(hour=0,minute=0,second=0)) :: ok :: s:2024-02-29 00:00:00
datetime.datetime(2024,2,29,0,0,0).replace(microsecond=0) :: ok :: DT(2024-02-29 00:00:00.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(microsecond=0)) :: ok :: s:2024-02-29 00:00:00
datetime.datetime(2024,2,29,0,0,0).replace(hour=23,minute=59,second=59) :: ok :: DT(2024-02-29 23:59:59.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(hour=23,minute=59,second=59)) :: ok :: s:2024-02-29 23:59:59
datetime.datetime(2024,2,29,0,0,0).replace(hour=24) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(hour=24)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(minute=60) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(minute=60)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(second=-1) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(second=-1)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(microsecond=1000000) :: err
str(datetime.datetime(2024,2,29,0,0,0).replace(microsecond=1000000)) :: err
datetime.datetime(2024,2,29,0,0,0).replace(year=2020,month=6,day=1,hour=1,minute=2,second=3) :: ok :: DT(2020-06-01 01:02:03.000000)
str(datetime.datetime(2024,2,29,0,0,0).replace(year=2020,month=6,day=1,hour=1,minute=2,second=3)) :: ok :: s:2020-06-01 01:02:03
datetime.datetime(2024,6,15,12,30,45,123456).replace(day=1) :: ok :: DT(2024-06-01 12:30:45.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(day=1)) :: ok :: s:2024-06-01 12:30:45.123456
datetime.datetime(2024,6,15,12,30,45,123456).replace(month=1) :: ok :: DT(2024-01-15 12:30:45.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(month=1)) :: ok :: s:2024-01-15 12:30:45.123456
datetime.datetime(2024,6,15,12,30,45,123456).replace(year=2000) :: ok :: DT(2000-06-15 12:30:45.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(year=2000)) :: ok :: s:2000-06-15 12:30:45.123456
datetime.datetime(2024,6,15,12,30,45,123456).replace(day=1,month=2) :: ok :: DT(2024-02-01 12:30:45.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(day=1,month=2)) :: ok :: s:2024-02-01 12:30:45.123456
datetime.datetime(2024,6,15,12,30,45,123456).replace(year=2023,month=2,day=28) :: ok :: DT(2023-02-28 12:30:45.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28 12:30:45.123456
datetime.datetime(2024,6,15,12,30,45,123456).replace(day=31) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(day=31)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(month=2,day=30) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(month=2,day=30)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(month=13) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(month=13)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(day=0) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(day=0)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(year=0) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(year=0)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(hour=0) :: ok :: DT(2024-06-15 00:30:45.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(hour=0)) :: ok :: s:2024-06-15 00:30:45.123456
datetime.datetime(2024,6,15,12,30,45,123456).replace(hour=0,minute=0,second=0) :: ok :: DT(2024-06-15 00:00:00.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(hour=0,minute=0,second=0)) :: ok :: s:2024-06-15 00:00:00.123456
datetime.datetime(2024,6,15,12,30,45,123456).replace(microsecond=0) :: ok :: DT(2024-06-15 12:30:45.000000)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(microsecond=0)) :: ok :: s:2024-06-15 12:30:45
datetime.datetime(2024,6,15,12,30,45,123456).replace(hour=23,minute=59,second=59) :: ok :: DT(2024-06-15 23:59:59.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(hour=23,minute=59,second=59)) :: ok :: s:2024-06-15 23:59:59.123456
datetime.datetime(2024,6,15,12,30,45,123456).replace(hour=24) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(hour=24)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(minute=60) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(minute=60)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(second=-1) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(second=-1)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(microsecond=1000000) :: err
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(microsecond=1000000)) :: err
datetime.datetime(2024,6,15,12,30,45,123456).replace(year=2020,month=6,day=1,hour=1,minute=2,second=3) :: ok :: DT(2020-06-01 01:02:03.123456)
str(datetime.datetime(2024,6,15,12,30,45,123456).replace(year=2020,month=6,day=1,hour=1,minute=2,second=3)) :: ok :: s:2020-06-01 01:02:03.123456
datetime.datetime(2023,12,31,23,0,0).replace(day=1) :: ok :: DT(2023-12-01 23:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(day=1)) :: ok :: s:2023-12-01 23:00:00
datetime.datetime(2023,12,31,23,0,0).replace(month=1) :: ok :: DT(2023-01-31 23:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(month=1)) :: ok :: s:2023-01-31 23:00:00
datetime.datetime(2023,12,31,23,0,0).replace(year=2000) :: ok :: DT(2000-12-31 23:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(year=2000)) :: ok :: s:2000-12-31 23:00:00
datetime.datetime(2023,12,31,23,0,0).replace(day=1,month=2) :: ok :: DT(2023-02-01 23:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(day=1,month=2)) :: ok :: s:2023-02-01 23:00:00
datetime.datetime(2023,12,31,23,0,0).replace(year=2023,month=2,day=28) :: ok :: DT(2023-02-28 23:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(year=2023,month=2,day=28)) :: ok :: s:2023-02-28 23:00:00
datetime.datetime(2023,12,31,23,0,0).replace(day=31) :: ok :: DT(2023-12-31 23:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(day=31)) :: ok :: s:2023-12-31 23:00:00
datetime.datetime(2023,12,31,23,0,0).replace(month=2,day=30) :: err
str(datetime.datetime(2023,12,31,23,0,0).replace(month=2,day=30)) :: err
datetime.datetime(2023,12,31,23,0,0).replace(month=13) :: err
str(datetime.datetime(2023,12,31,23,0,0).replace(month=13)) :: err
datetime.datetime(2023,12,31,23,0,0).replace(day=0) :: err
str(datetime.datetime(2023,12,31,23,0,0).replace(day=0)) :: err
datetime.datetime(2023,12,31,23,0,0).replace(year=0) :: err
str(datetime.datetime(2023,12,31,23,0,0).replace(year=0)) :: err
datetime.datetime(2023,12,31,23,0,0).replace(hour=0) :: ok :: DT(2023-12-31 00:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(hour=0)) :: ok :: s:2023-12-31 00:00:00
datetime.datetime(2023,12,31,23,0,0).replace(hour=0,minute=0,second=0) :: ok :: DT(2023-12-31 00:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(hour=0,minute=0,second=0)) :: ok :: s:2023-12-31 00:00:00
datetime.datetime(2023,12,31,23,0,0).replace(microsecond=0) :: ok :: DT(2023-12-31 23:00:00.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(microsecond=0)) :: ok :: s:2023-12-31 23:00:00
datetime.datetime(2023,12,31,23,0,0).replace(hour=23,minute=59,second=59) :: ok :: DT(2023-12-31 23:59:59.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(hour=23,minute=59,second=59)) :: ok :: s:2023-12-31 23:59:59
datetime.datetime(2023,12,31,23,0,0).replace(hour=24) :: err
str(datetime.datetime(2023,12,31,23,0,0).replace(hour=24)) :: err
datetime.datetime(2023,12,31,23,0,0).replace(minute=60) :: err
str(datetime.datetime(2023,12,31,23,0,0).replace(minute=60)) :: err
datetime.datetime(2023,12,31,23,0,0).replace(second=-1) :: err
str(datetime.datetime(2023,12,31,23,0,0).replace(second=-1)) :: err
datetime.datetime(2023,12,31,23,0,0).replace(microsecond=1000000) :: err
str(datetime.datetime(2023,12,31,23,0,0).replace(microsecond=1000000)) :: err
datetime.datetime(2023,12,31,23,0,0).replace(year=2020,month=6,day=1,hour=1,minute=2,second=3) :: ok :: DT(2020-06-01 01:02:03.000000)
str(datetime.datetime(2023,12,31,23,0,0).replace(year=2020,month=6,day=1,hour=1,minute=2,second=3)) :: ok :: s:2020-06-01 01:02:03
datetime.time(0,0,0).replace(hour=1) :: ok :: T(01:00:00)
datetime.time(0,0,0).replace(minute=5) :: ok :: T(00:05:00)
datetime.time(0,0,0).replace(second=9) :: ok :: T(00:00:09)
datetime.time(0,0,0).replace(hour=1,minute=2,second=3) :: ok :: T(01:02:03)
datetime.time(0,0,0).replace(hour=24) :: err
datetime.time(0,0,0).replace(minute=60) :: err
datetime.time(12,30,45).replace(hour=1) :: ok :: T(01:30:45)
datetime.time(12,30,45).replace(minute=5) :: ok :: T(12:05:45)
datetime.time(12,30,45).replace(second=9) :: ok :: T(12:30:09)
datetime.time(12,30,45).replace(hour=1,minute=2,second=3) :: ok :: T(01:02:03)
datetime.time(12,30,45).replace(hour=24) :: err
datetime.time(12,30,45).replace(minute=60) :: err
datetime.date(2024,1,31).replace(2020) :: ok :: D(2020-01-31)
datetime.date(2024,1,31).replace(2020, 5) :: ok :: D(2020-05-31)
datetime.date(2024,1,31).replace(2020, 5, 6) :: ok :: D(2020-05-06)
datetime.date(2024,2,29).replace(2020) :: ok :: D(2020-02-29)
datetime.date(2024,2,29).replace(2020, 5) :: ok :: D(2020-05-29)
datetime.date(2024,2,29).replace(2020, 5, 6) :: ok :: D(2020-05-06)
datetime.datetime(2024,1,31,23,59,59).replace(2020, 5, 6, 7) :: ok :: DT(2020-05-06 07:59:59.000000)
datetime.datetime(2024,1,31,23,59,59).replace(2020, 5, 6, 7, 8, 9) :: ok :: DT(2020-05-06 07:08:09.000000)
datetime.datetime(2024,2,29,0,0,0).replace(2020, 5, 6, 7) :: ok :: DT(2020-05-06 07:00:00.000000)
datetime.datetime(2024,2,29,0,0,0).replace(2020, 5, 6, 7, 8, 9) :: ok :: DT(2020-05-06 07:08:09.000000)
datetime.datetime(2024,3,15,14,22,7).replace(hour=0, minute=0, second=0) :: ok :: DT(2024-03-15 00:00:00.000000)
(datetime.datetime(2024,3,15,14,22,7) - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0) :: ok :: DT(2024-03-14 00:00:00.000000)
(datetime.date(2024,3,15).replace(day=1)).strftime('%Y-%m-%d') :: ok :: s:2024-03-01
(datetime.date(2024,3,15).replace(day=1) - datetime.timedelta(days=1)).strftime('%Y-%m') :: ok :: s:2024-02
datetime.datetime.combine(datetime.date(2024,1,31), datetime.time(1,2,3)) :: ok :: DT(2024-01-31 01:02:03.000000)
datetime.datetime.combine(datetime.date(2024,2,29), datetime.time(1,2,3)) :: ok :: DT(2024-02-29 01:02:03.000000)
datetime.datetime.combine(datetime.date(2023,3,1), datetime.time(1,2,3)) :: ok :: DT(2023-03-01 01:02:03.000000)
`
    .trim()
    .split("\n")
    .map((line) => line.split(" :: "));

const YEAR_SWEEP = `
2023-01-01 2023|23|01|01| 1|001|01|00|0|Sun|Sunday|Jan|January|01/01/23
2023-01-02 2023|23|01|02| 2|002|01|01|1|Mon|Monday|Jan|January|01/02/23
2023-01-03 2023|23|01|03| 3|003|01|01|2|Tue|Tuesday|Jan|January|01/03/23
2023-01-04 2023|23|01|04| 4|004|01|01|3|Wed|Wednesday|Jan|January|01/04/23
2023-01-05 2023|23|01|05| 5|005|01|01|4|Thu|Thursday|Jan|January|01/05/23
2023-01-06 2023|23|01|06| 6|006|01|01|5|Fri|Friday|Jan|January|01/06/23
2023-01-07 2023|23|01|07| 7|007|01|01|6|Sat|Saturday|Jan|January|01/07/23
2023-01-08 2023|23|01|08| 8|008|02|01|0|Sun|Sunday|Jan|January|01/08/23
2023-01-09 2023|23|01|09| 9|009|02|02|1|Mon|Monday|Jan|January|01/09/23
2023-01-10 2023|23|01|10|10|010|02|02|2|Tue|Tuesday|Jan|January|01/10/23
2023-01-11 2023|23|01|11|11|011|02|02|3|Wed|Wednesday|Jan|January|01/11/23
2023-01-12 2023|23|01|12|12|012|02|02|4|Thu|Thursday|Jan|January|01/12/23
2023-01-13 2023|23|01|13|13|013|02|02|5|Fri|Friday|Jan|January|01/13/23
2023-01-14 2023|23|01|14|14|014|02|02|6|Sat|Saturday|Jan|January|01/14/23
2023-01-15 2023|23|01|15|15|015|03|02|0|Sun|Sunday|Jan|January|01/15/23
2023-01-16 2023|23|01|16|16|016|03|03|1|Mon|Monday|Jan|January|01/16/23
2023-01-17 2023|23|01|17|17|017|03|03|2|Tue|Tuesday|Jan|January|01/17/23
2023-01-18 2023|23|01|18|18|018|03|03|3|Wed|Wednesday|Jan|January|01/18/23
2023-01-19 2023|23|01|19|19|019|03|03|4|Thu|Thursday|Jan|January|01/19/23
2023-01-20 2023|23|01|20|20|020|03|03|5|Fri|Friday|Jan|January|01/20/23
2023-01-21 2023|23|01|21|21|021|03|03|6|Sat|Saturday|Jan|January|01/21/23
2023-01-22 2023|23|01|22|22|022|04|03|0|Sun|Sunday|Jan|January|01/22/23
2023-01-23 2023|23|01|23|23|023|04|04|1|Mon|Monday|Jan|January|01/23/23
2023-01-24 2023|23|01|24|24|024|04|04|2|Tue|Tuesday|Jan|January|01/24/23
2023-01-25 2023|23|01|25|25|025|04|04|3|Wed|Wednesday|Jan|January|01/25/23
2023-01-26 2023|23|01|26|26|026|04|04|4|Thu|Thursday|Jan|January|01/26/23
2023-01-27 2023|23|01|27|27|027|04|04|5|Fri|Friday|Jan|January|01/27/23
2023-01-28 2023|23|01|28|28|028|04|04|6|Sat|Saturday|Jan|January|01/28/23
2023-01-29 2023|23|01|29|29|029|05|04|0|Sun|Sunday|Jan|January|01/29/23
2023-01-30 2023|23|01|30|30|030|05|05|1|Mon|Monday|Jan|January|01/30/23
2023-01-31 2023|23|01|31|31|031|05|05|2|Tue|Tuesday|Jan|January|01/31/23
2023-02-01 2023|23|02|01| 1|032|05|05|3|Wed|Wednesday|Feb|February|02/01/23
2023-02-02 2023|23|02|02| 2|033|05|05|4|Thu|Thursday|Feb|February|02/02/23
2023-02-03 2023|23|02|03| 3|034|05|05|5|Fri|Friday|Feb|February|02/03/23
2023-02-04 2023|23|02|04| 4|035|05|05|6|Sat|Saturday|Feb|February|02/04/23
2023-02-05 2023|23|02|05| 5|036|06|05|0|Sun|Sunday|Feb|February|02/05/23
2023-02-06 2023|23|02|06| 6|037|06|06|1|Mon|Monday|Feb|February|02/06/23
2023-02-07 2023|23|02|07| 7|038|06|06|2|Tue|Tuesday|Feb|February|02/07/23
2023-02-08 2023|23|02|08| 8|039|06|06|3|Wed|Wednesday|Feb|February|02/08/23
2023-02-09 2023|23|02|09| 9|040|06|06|4|Thu|Thursday|Feb|February|02/09/23
2023-02-10 2023|23|02|10|10|041|06|06|5|Fri|Friday|Feb|February|02/10/23
2023-02-11 2023|23|02|11|11|042|06|06|6|Sat|Saturday|Feb|February|02/11/23
2023-02-12 2023|23|02|12|12|043|07|06|0|Sun|Sunday|Feb|February|02/12/23
2023-02-13 2023|23|02|13|13|044|07|07|1|Mon|Monday|Feb|February|02/13/23
2023-02-14 2023|23|02|14|14|045|07|07|2|Tue|Tuesday|Feb|February|02/14/23
2023-02-15 2023|23|02|15|15|046|07|07|3|Wed|Wednesday|Feb|February|02/15/23
2023-02-16 2023|23|02|16|16|047|07|07|4|Thu|Thursday|Feb|February|02/16/23
2023-02-17 2023|23|02|17|17|048|07|07|5|Fri|Friday|Feb|February|02/17/23
2023-02-18 2023|23|02|18|18|049|07|07|6|Sat|Saturday|Feb|February|02/18/23
2023-02-19 2023|23|02|19|19|050|08|07|0|Sun|Sunday|Feb|February|02/19/23
2023-02-20 2023|23|02|20|20|051|08|08|1|Mon|Monday|Feb|February|02/20/23
2023-02-21 2023|23|02|21|21|052|08|08|2|Tue|Tuesday|Feb|February|02/21/23
2023-02-22 2023|23|02|22|22|053|08|08|3|Wed|Wednesday|Feb|February|02/22/23
2023-02-23 2023|23|02|23|23|054|08|08|4|Thu|Thursday|Feb|February|02/23/23
2023-02-24 2023|23|02|24|24|055|08|08|5|Fri|Friday|Feb|February|02/24/23
2023-02-25 2023|23|02|25|25|056|08|08|6|Sat|Saturday|Feb|February|02/25/23
2023-02-26 2023|23|02|26|26|057|09|08|0|Sun|Sunday|Feb|February|02/26/23
2023-02-27 2023|23|02|27|27|058|09|09|1|Mon|Monday|Feb|February|02/27/23
2023-02-28 2023|23|02|28|28|059|09|09|2|Tue|Tuesday|Feb|February|02/28/23
2023-03-01 2023|23|03|01| 1|060|09|09|3|Wed|Wednesday|Mar|March|03/01/23
2023-03-02 2023|23|03|02| 2|061|09|09|4|Thu|Thursday|Mar|March|03/02/23
2023-03-03 2023|23|03|03| 3|062|09|09|5|Fri|Friday|Mar|March|03/03/23
2023-03-04 2023|23|03|04| 4|063|09|09|6|Sat|Saturday|Mar|March|03/04/23
2023-03-05 2023|23|03|05| 5|064|10|09|0|Sun|Sunday|Mar|March|03/05/23
2023-03-06 2023|23|03|06| 6|065|10|10|1|Mon|Monday|Mar|March|03/06/23
2023-03-07 2023|23|03|07| 7|066|10|10|2|Tue|Tuesday|Mar|March|03/07/23
2023-03-08 2023|23|03|08| 8|067|10|10|3|Wed|Wednesday|Mar|March|03/08/23
2023-03-09 2023|23|03|09| 9|068|10|10|4|Thu|Thursday|Mar|March|03/09/23
2023-03-10 2023|23|03|10|10|069|10|10|5|Fri|Friday|Mar|March|03/10/23
2023-03-11 2023|23|03|11|11|070|10|10|6|Sat|Saturday|Mar|March|03/11/23
2023-03-12 2023|23|03|12|12|071|11|10|0|Sun|Sunday|Mar|March|03/12/23
2023-03-13 2023|23|03|13|13|072|11|11|1|Mon|Monday|Mar|March|03/13/23
2023-03-14 2023|23|03|14|14|073|11|11|2|Tue|Tuesday|Mar|March|03/14/23
2023-03-15 2023|23|03|15|15|074|11|11|3|Wed|Wednesday|Mar|March|03/15/23
2023-03-16 2023|23|03|16|16|075|11|11|4|Thu|Thursday|Mar|March|03/16/23
2023-03-17 2023|23|03|17|17|076|11|11|5|Fri|Friday|Mar|March|03/17/23
2023-03-18 2023|23|03|18|18|077|11|11|6|Sat|Saturday|Mar|March|03/18/23
2023-03-19 2023|23|03|19|19|078|12|11|0|Sun|Sunday|Mar|March|03/19/23
2023-03-20 2023|23|03|20|20|079|12|12|1|Mon|Monday|Mar|March|03/20/23
2023-03-21 2023|23|03|21|21|080|12|12|2|Tue|Tuesday|Mar|March|03/21/23
2023-03-22 2023|23|03|22|22|081|12|12|3|Wed|Wednesday|Mar|March|03/22/23
2023-03-23 2023|23|03|23|23|082|12|12|4|Thu|Thursday|Mar|March|03/23/23
2023-03-24 2023|23|03|24|24|083|12|12|5|Fri|Friday|Mar|March|03/24/23
2023-03-25 2023|23|03|25|25|084|12|12|6|Sat|Saturday|Mar|March|03/25/23
2023-03-26 2023|23|03|26|26|085|13|12|0|Sun|Sunday|Mar|March|03/26/23
2023-03-27 2023|23|03|27|27|086|13|13|1|Mon|Monday|Mar|March|03/27/23
2023-03-28 2023|23|03|28|28|087|13|13|2|Tue|Tuesday|Mar|March|03/28/23
2023-03-29 2023|23|03|29|29|088|13|13|3|Wed|Wednesday|Mar|March|03/29/23
2023-03-30 2023|23|03|30|30|089|13|13|4|Thu|Thursday|Mar|March|03/30/23
2023-03-31 2023|23|03|31|31|090|13|13|5|Fri|Friday|Mar|March|03/31/23
2023-04-01 2023|23|04|01| 1|091|13|13|6|Sat|Saturday|Apr|April|04/01/23
2023-04-02 2023|23|04|02| 2|092|14|13|0|Sun|Sunday|Apr|April|04/02/23
2023-04-03 2023|23|04|03| 3|093|14|14|1|Mon|Monday|Apr|April|04/03/23
2023-04-04 2023|23|04|04| 4|094|14|14|2|Tue|Tuesday|Apr|April|04/04/23
2023-04-05 2023|23|04|05| 5|095|14|14|3|Wed|Wednesday|Apr|April|04/05/23
2023-04-06 2023|23|04|06| 6|096|14|14|4|Thu|Thursday|Apr|April|04/06/23
2023-04-07 2023|23|04|07| 7|097|14|14|5|Fri|Friday|Apr|April|04/07/23
2023-04-08 2023|23|04|08| 8|098|14|14|6|Sat|Saturday|Apr|April|04/08/23
2023-04-09 2023|23|04|09| 9|099|15|14|0|Sun|Sunday|Apr|April|04/09/23
2023-04-10 2023|23|04|10|10|100|15|15|1|Mon|Monday|Apr|April|04/10/23
2023-04-11 2023|23|04|11|11|101|15|15|2|Tue|Tuesday|Apr|April|04/11/23
2023-04-12 2023|23|04|12|12|102|15|15|3|Wed|Wednesday|Apr|April|04/12/23
2023-04-13 2023|23|04|13|13|103|15|15|4|Thu|Thursday|Apr|April|04/13/23
2023-04-14 2023|23|04|14|14|104|15|15|5|Fri|Friday|Apr|April|04/14/23
2023-04-15 2023|23|04|15|15|105|15|15|6|Sat|Saturday|Apr|April|04/15/23
2023-04-16 2023|23|04|16|16|106|16|15|0|Sun|Sunday|Apr|April|04/16/23
2023-04-17 2023|23|04|17|17|107|16|16|1|Mon|Monday|Apr|April|04/17/23
2023-04-18 2023|23|04|18|18|108|16|16|2|Tue|Tuesday|Apr|April|04/18/23
2023-04-19 2023|23|04|19|19|109|16|16|3|Wed|Wednesday|Apr|April|04/19/23
2023-04-20 2023|23|04|20|20|110|16|16|4|Thu|Thursday|Apr|April|04/20/23
2023-04-21 2023|23|04|21|21|111|16|16|5|Fri|Friday|Apr|April|04/21/23
2023-04-22 2023|23|04|22|22|112|16|16|6|Sat|Saturday|Apr|April|04/22/23
2023-04-23 2023|23|04|23|23|113|17|16|0|Sun|Sunday|Apr|April|04/23/23
2023-04-24 2023|23|04|24|24|114|17|17|1|Mon|Monday|Apr|April|04/24/23
2023-04-25 2023|23|04|25|25|115|17|17|2|Tue|Tuesday|Apr|April|04/25/23
2023-04-26 2023|23|04|26|26|116|17|17|3|Wed|Wednesday|Apr|April|04/26/23
2023-04-27 2023|23|04|27|27|117|17|17|4|Thu|Thursday|Apr|April|04/27/23
2023-04-28 2023|23|04|28|28|118|17|17|5|Fri|Friday|Apr|April|04/28/23
2023-04-29 2023|23|04|29|29|119|17|17|6|Sat|Saturday|Apr|April|04/29/23
2023-04-30 2023|23|04|30|30|120|18|17|0|Sun|Sunday|Apr|April|04/30/23
2023-05-01 2023|23|05|01| 1|121|18|18|1|Mon|Monday|May|May|05/01/23
2023-05-02 2023|23|05|02| 2|122|18|18|2|Tue|Tuesday|May|May|05/02/23
2023-05-03 2023|23|05|03| 3|123|18|18|3|Wed|Wednesday|May|May|05/03/23
2023-05-04 2023|23|05|04| 4|124|18|18|4|Thu|Thursday|May|May|05/04/23
2023-05-05 2023|23|05|05| 5|125|18|18|5|Fri|Friday|May|May|05/05/23
2023-05-06 2023|23|05|06| 6|126|18|18|6|Sat|Saturday|May|May|05/06/23
2023-05-07 2023|23|05|07| 7|127|19|18|0|Sun|Sunday|May|May|05/07/23
2023-05-08 2023|23|05|08| 8|128|19|19|1|Mon|Monday|May|May|05/08/23
2023-05-09 2023|23|05|09| 9|129|19|19|2|Tue|Tuesday|May|May|05/09/23
2023-05-10 2023|23|05|10|10|130|19|19|3|Wed|Wednesday|May|May|05/10/23
2023-05-11 2023|23|05|11|11|131|19|19|4|Thu|Thursday|May|May|05/11/23
2023-05-12 2023|23|05|12|12|132|19|19|5|Fri|Friday|May|May|05/12/23
2023-05-13 2023|23|05|13|13|133|19|19|6|Sat|Saturday|May|May|05/13/23
2023-05-14 2023|23|05|14|14|134|20|19|0|Sun|Sunday|May|May|05/14/23
2023-05-15 2023|23|05|15|15|135|20|20|1|Mon|Monday|May|May|05/15/23
2023-05-16 2023|23|05|16|16|136|20|20|2|Tue|Tuesday|May|May|05/16/23
2023-05-17 2023|23|05|17|17|137|20|20|3|Wed|Wednesday|May|May|05/17/23
2023-05-18 2023|23|05|18|18|138|20|20|4|Thu|Thursday|May|May|05/18/23
2023-05-19 2023|23|05|19|19|139|20|20|5|Fri|Friday|May|May|05/19/23
2023-05-20 2023|23|05|20|20|140|20|20|6|Sat|Saturday|May|May|05/20/23
2023-05-21 2023|23|05|21|21|141|21|20|0|Sun|Sunday|May|May|05/21/23
2023-05-22 2023|23|05|22|22|142|21|21|1|Mon|Monday|May|May|05/22/23
2023-05-23 2023|23|05|23|23|143|21|21|2|Tue|Tuesday|May|May|05/23/23
2023-05-24 2023|23|05|24|24|144|21|21|3|Wed|Wednesday|May|May|05/24/23
2023-05-25 2023|23|05|25|25|145|21|21|4|Thu|Thursday|May|May|05/25/23
2023-05-26 2023|23|05|26|26|146|21|21|5|Fri|Friday|May|May|05/26/23
2023-05-27 2023|23|05|27|27|147|21|21|6|Sat|Saturday|May|May|05/27/23
2023-05-28 2023|23|05|28|28|148|22|21|0|Sun|Sunday|May|May|05/28/23
2023-05-29 2023|23|05|29|29|149|22|22|1|Mon|Monday|May|May|05/29/23
2023-05-30 2023|23|05|30|30|150|22|22|2|Tue|Tuesday|May|May|05/30/23
2023-05-31 2023|23|05|31|31|151|22|22|3|Wed|Wednesday|May|May|05/31/23
2023-06-01 2023|23|06|01| 1|152|22|22|4|Thu|Thursday|Jun|June|06/01/23
2023-06-02 2023|23|06|02| 2|153|22|22|5|Fri|Friday|Jun|June|06/02/23
2023-06-03 2023|23|06|03| 3|154|22|22|6|Sat|Saturday|Jun|June|06/03/23
2023-06-04 2023|23|06|04| 4|155|23|22|0|Sun|Sunday|Jun|June|06/04/23
2023-06-05 2023|23|06|05| 5|156|23|23|1|Mon|Monday|Jun|June|06/05/23
2023-06-06 2023|23|06|06| 6|157|23|23|2|Tue|Tuesday|Jun|June|06/06/23
2023-06-07 2023|23|06|07| 7|158|23|23|3|Wed|Wednesday|Jun|June|06/07/23
2023-06-08 2023|23|06|08| 8|159|23|23|4|Thu|Thursday|Jun|June|06/08/23
2023-06-09 2023|23|06|09| 9|160|23|23|5|Fri|Friday|Jun|June|06/09/23
2023-06-10 2023|23|06|10|10|161|23|23|6|Sat|Saturday|Jun|June|06/10/23
2023-06-11 2023|23|06|11|11|162|24|23|0|Sun|Sunday|Jun|June|06/11/23
2023-06-12 2023|23|06|12|12|163|24|24|1|Mon|Monday|Jun|June|06/12/23
2023-06-13 2023|23|06|13|13|164|24|24|2|Tue|Tuesday|Jun|June|06/13/23
2023-06-14 2023|23|06|14|14|165|24|24|3|Wed|Wednesday|Jun|June|06/14/23
2023-06-15 2023|23|06|15|15|166|24|24|4|Thu|Thursday|Jun|June|06/15/23
2023-06-16 2023|23|06|16|16|167|24|24|5|Fri|Friday|Jun|June|06/16/23
2023-06-17 2023|23|06|17|17|168|24|24|6|Sat|Saturday|Jun|June|06/17/23
2023-06-18 2023|23|06|18|18|169|25|24|0|Sun|Sunday|Jun|June|06/18/23
2023-06-19 2023|23|06|19|19|170|25|25|1|Mon|Monday|Jun|June|06/19/23
2023-06-20 2023|23|06|20|20|171|25|25|2|Tue|Tuesday|Jun|June|06/20/23
2023-06-21 2023|23|06|21|21|172|25|25|3|Wed|Wednesday|Jun|June|06/21/23
2023-06-22 2023|23|06|22|22|173|25|25|4|Thu|Thursday|Jun|June|06/22/23
2023-06-23 2023|23|06|23|23|174|25|25|5|Fri|Friday|Jun|June|06/23/23
2023-06-24 2023|23|06|24|24|175|25|25|6|Sat|Saturday|Jun|June|06/24/23
2023-06-25 2023|23|06|25|25|176|26|25|0|Sun|Sunday|Jun|June|06/25/23
2023-06-26 2023|23|06|26|26|177|26|26|1|Mon|Monday|Jun|June|06/26/23
2023-06-27 2023|23|06|27|27|178|26|26|2|Tue|Tuesday|Jun|June|06/27/23
2023-06-28 2023|23|06|28|28|179|26|26|3|Wed|Wednesday|Jun|June|06/28/23
2023-06-29 2023|23|06|29|29|180|26|26|4|Thu|Thursday|Jun|June|06/29/23
2023-06-30 2023|23|06|30|30|181|26|26|5|Fri|Friday|Jun|June|06/30/23
2023-07-01 2023|23|07|01| 1|182|26|26|6|Sat|Saturday|Jul|July|07/01/23
2023-07-02 2023|23|07|02| 2|183|27|26|0|Sun|Sunday|Jul|July|07/02/23
2023-07-03 2023|23|07|03| 3|184|27|27|1|Mon|Monday|Jul|July|07/03/23
2023-07-04 2023|23|07|04| 4|185|27|27|2|Tue|Tuesday|Jul|July|07/04/23
2023-07-05 2023|23|07|05| 5|186|27|27|3|Wed|Wednesday|Jul|July|07/05/23
2023-07-06 2023|23|07|06| 6|187|27|27|4|Thu|Thursday|Jul|July|07/06/23
2023-07-07 2023|23|07|07| 7|188|27|27|5|Fri|Friday|Jul|July|07/07/23
2023-07-08 2023|23|07|08| 8|189|27|27|6|Sat|Saturday|Jul|July|07/08/23
2023-07-09 2023|23|07|09| 9|190|28|27|0|Sun|Sunday|Jul|July|07/09/23
2023-07-10 2023|23|07|10|10|191|28|28|1|Mon|Monday|Jul|July|07/10/23
2023-07-11 2023|23|07|11|11|192|28|28|2|Tue|Tuesday|Jul|July|07/11/23
2023-07-12 2023|23|07|12|12|193|28|28|3|Wed|Wednesday|Jul|July|07/12/23
2023-07-13 2023|23|07|13|13|194|28|28|4|Thu|Thursday|Jul|July|07/13/23
2023-07-14 2023|23|07|14|14|195|28|28|5|Fri|Friday|Jul|July|07/14/23
2023-07-15 2023|23|07|15|15|196|28|28|6|Sat|Saturday|Jul|July|07/15/23
2023-07-16 2023|23|07|16|16|197|29|28|0|Sun|Sunday|Jul|July|07/16/23
2023-07-17 2023|23|07|17|17|198|29|29|1|Mon|Monday|Jul|July|07/17/23
2023-07-18 2023|23|07|18|18|199|29|29|2|Tue|Tuesday|Jul|July|07/18/23
2023-07-19 2023|23|07|19|19|200|29|29|3|Wed|Wednesday|Jul|July|07/19/23
2023-07-20 2023|23|07|20|20|201|29|29|4|Thu|Thursday|Jul|July|07/20/23
2023-07-21 2023|23|07|21|21|202|29|29|5|Fri|Friday|Jul|July|07/21/23
2023-07-22 2023|23|07|22|22|203|29|29|6|Sat|Saturday|Jul|July|07/22/23
2023-07-23 2023|23|07|23|23|204|30|29|0|Sun|Sunday|Jul|July|07/23/23
2023-07-24 2023|23|07|24|24|205|30|30|1|Mon|Monday|Jul|July|07/24/23
2023-07-25 2023|23|07|25|25|206|30|30|2|Tue|Tuesday|Jul|July|07/25/23
2023-07-26 2023|23|07|26|26|207|30|30|3|Wed|Wednesday|Jul|July|07/26/23
2023-07-27 2023|23|07|27|27|208|30|30|4|Thu|Thursday|Jul|July|07/27/23
2023-07-28 2023|23|07|28|28|209|30|30|5|Fri|Friday|Jul|July|07/28/23
2023-07-29 2023|23|07|29|29|210|30|30|6|Sat|Saturday|Jul|July|07/29/23
2023-07-30 2023|23|07|30|30|211|31|30|0|Sun|Sunday|Jul|July|07/30/23
2023-07-31 2023|23|07|31|31|212|31|31|1|Mon|Monday|Jul|July|07/31/23
2023-08-01 2023|23|08|01| 1|213|31|31|2|Tue|Tuesday|Aug|August|08/01/23
2023-08-02 2023|23|08|02| 2|214|31|31|3|Wed|Wednesday|Aug|August|08/02/23
2023-08-03 2023|23|08|03| 3|215|31|31|4|Thu|Thursday|Aug|August|08/03/23
2023-08-04 2023|23|08|04| 4|216|31|31|5|Fri|Friday|Aug|August|08/04/23
2023-08-05 2023|23|08|05| 5|217|31|31|6|Sat|Saturday|Aug|August|08/05/23
2023-08-06 2023|23|08|06| 6|218|32|31|0|Sun|Sunday|Aug|August|08/06/23
2023-08-07 2023|23|08|07| 7|219|32|32|1|Mon|Monday|Aug|August|08/07/23
2023-08-08 2023|23|08|08| 8|220|32|32|2|Tue|Tuesday|Aug|August|08/08/23
2023-08-09 2023|23|08|09| 9|221|32|32|3|Wed|Wednesday|Aug|August|08/09/23
2023-08-10 2023|23|08|10|10|222|32|32|4|Thu|Thursday|Aug|August|08/10/23
2023-08-11 2023|23|08|11|11|223|32|32|5|Fri|Friday|Aug|August|08/11/23
2023-08-12 2023|23|08|12|12|224|32|32|6|Sat|Saturday|Aug|August|08/12/23
2023-08-13 2023|23|08|13|13|225|33|32|0|Sun|Sunday|Aug|August|08/13/23
2023-08-14 2023|23|08|14|14|226|33|33|1|Mon|Monday|Aug|August|08/14/23
2023-08-15 2023|23|08|15|15|227|33|33|2|Tue|Tuesday|Aug|August|08/15/23
2023-08-16 2023|23|08|16|16|228|33|33|3|Wed|Wednesday|Aug|August|08/16/23
2023-08-17 2023|23|08|17|17|229|33|33|4|Thu|Thursday|Aug|August|08/17/23
2023-08-18 2023|23|08|18|18|230|33|33|5|Fri|Friday|Aug|August|08/18/23
2023-08-19 2023|23|08|19|19|231|33|33|6|Sat|Saturday|Aug|August|08/19/23
2023-08-20 2023|23|08|20|20|232|34|33|0|Sun|Sunday|Aug|August|08/20/23
2023-08-21 2023|23|08|21|21|233|34|34|1|Mon|Monday|Aug|August|08/21/23
2023-08-22 2023|23|08|22|22|234|34|34|2|Tue|Tuesday|Aug|August|08/22/23
2023-08-23 2023|23|08|23|23|235|34|34|3|Wed|Wednesday|Aug|August|08/23/23
2023-08-24 2023|23|08|24|24|236|34|34|4|Thu|Thursday|Aug|August|08/24/23
2023-08-25 2023|23|08|25|25|237|34|34|5|Fri|Friday|Aug|August|08/25/23
2023-08-26 2023|23|08|26|26|238|34|34|6|Sat|Saturday|Aug|August|08/26/23
2023-08-27 2023|23|08|27|27|239|35|34|0|Sun|Sunday|Aug|August|08/27/23
2023-08-28 2023|23|08|28|28|240|35|35|1|Mon|Monday|Aug|August|08/28/23
2023-08-29 2023|23|08|29|29|241|35|35|2|Tue|Tuesday|Aug|August|08/29/23
2023-08-30 2023|23|08|30|30|242|35|35|3|Wed|Wednesday|Aug|August|08/30/23
2023-08-31 2023|23|08|31|31|243|35|35|4|Thu|Thursday|Aug|August|08/31/23
2023-09-01 2023|23|09|01| 1|244|35|35|5|Fri|Friday|Sep|September|09/01/23
2023-09-02 2023|23|09|02| 2|245|35|35|6|Sat|Saturday|Sep|September|09/02/23
2023-09-03 2023|23|09|03| 3|246|36|35|0|Sun|Sunday|Sep|September|09/03/23
2023-09-04 2023|23|09|04| 4|247|36|36|1|Mon|Monday|Sep|September|09/04/23
2023-09-05 2023|23|09|05| 5|248|36|36|2|Tue|Tuesday|Sep|September|09/05/23
2023-09-06 2023|23|09|06| 6|249|36|36|3|Wed|Wednesday|Sep|September|09/06/23
2023-09-07 2023|23|09|07| 7|250|36|36|4|Thu|Thursday|Sep|September|09/07/23
2023-09-08 2023|23|09|08| 8|251|36|36|5|Fri|Friday|Sep|September|09/08/23
2023-09-09 2023|23|09|09| 9|252|36|36|6|Sat|Saturday|Sep|September|09/09/23
2023-09-10 2023|23|09|10|10|253|37|36|0|Sun|Sunday|Sep|September|09/10/23
2023-09-11 2023|23|09|11|11|254|37|37|1|Mon|Monday|Sep|September|09/11/23
2023-09-12 2023|23|09|12|12|255|37|37|2|Tue|Tuesday|Sep|September|09/12/23
2023-09-13 2023|23|09|13|13|256|37|37|3|Wed|Wednesday|Sep|September|09/13/23
2023-09-14 2023|23|09|14|14|257|37|37|4|Thu|Thursday|Sep|September|09/14/23
2023-09-15 2023|23|09|15|15|258|37|37|5|Fri|Friday|Sep|September|09/15/23
2023-09-16 2023|23|09|16|16|259|37|37|6|Sat|Saturday|Sep|September|09/16/23
2023-09-17 2023|23|09|17|17|260|38|37|0|Sun|Sunday|Sep|September|09/17/23
2023-09-18 2023|23|09|18|18|261|38|38|1|Mon|Monday|Sep|September|09/18/23
2023-09-19 2023|23|09|19|19|262|38|38|2|Tue|Tuesday|Sep|September|09/19/23
2023-09-20 2023|23|09|20|20|263|38|38|3|Wed|Wednesday|Sep|September|09/20/23
2023-09-21 2023|23|09|21|21|264|38|38|4|Thu|Thursday|Sep|September|09/21/23
2023-09-22 2023|23|09|22|22|265|38|38|5|Fri|Friday|Sep|September|09/22/23
2023-09-23 2023|23|09|23|23|266|38|38|6|Sat|Saturday|Sep|September|09/23/23
2023-09-24 2023|23|09|24|24|267|39|38|0|Sun|Sunday|Sep|September|09/24/23
2023-09-25 2023|23|09|25|25|268|39|39|1|Mon|Monday|Sep|September|09/25/23
2023-09-26 2023|23|09|26|26|269|39|39|2|Tue|Tuesday|Sep|September|09/26/23
2023-09-27 2023|23|09|27|27|270|39|39|3|Wed|Wednesday|Sep|September|09/27/23
2023-09-28 2023|23|09|28|28|271|39|39|4|Thu|Thursday|Sep|September|09/28/23
2023-09-29 2023|23|09|29|29|272|39|39|5|Fri|Friday|Sep|September|09/29/23
2023-09-30 2023|23|09|30|30|273|39|39|6|Sat|Saturday|Sep|September|09/30/23
2023-10-01 2023|23|10|01| 1|274|40|39|0|Sun|Sunday|Oct|October|10/01/23
2023-10-02 2023|23|10|02| 2|275|40|40|1|Mon|Monday|Oct|October|10/02/23
2023-10-03 2023|23|10|03| 3|276|40|40|2|Tue|Tuesday|Oct|October|10/03/23
2023-10-04 2023|23|10|04| 4|277|40|40|3|Wed|Wednesday|Oct|October|10/04/23
2023-10-05 2023|23|10|05| 5|278|40|40|4|Thu|Thursday|Oct|October|10/05/23
2023-10-06 2023|23|10|06| 6|279|40|40|5|Fri|Friday|Oct|October|10/06/23
2023-10-07 2023|23|10|07| 7|280|40|40|6|Sat|Saturday|Oct|October|10/07/23
2023-10-08 2023|23|10|08| 8|281|41|40|0|Sun|Sunday|Oct|October|10/08/23
2023-10-09 2023|23|10|09| 9|282|41|41|1|Mon|Monday|Oct|October|10/09/23
2023-10-10 2023|23|10|10|10|283|41|41|2|Tue|Tuesday|Oct|October|10/10/23
2023-10-11 2023|23|10|11|11|284|41|41|3|Wed|Wednesday|Oct|October|10/11/23
2023-10-12 2023|23|10|12|12|285|41|41|4|Thu|Thursday|Oct|October|10/12/23
2023-10-13 2023|23|10|13|13|286|41|41|5|Fri|Friday|Oct|October|10/13/23
2023-10-14 2023|23|10|14|14|287|41|41|6|Sat|Saturday|Oct|October|10/14/23
2023-10-15 2023|23|10|15|15|288|42|41|0|Sun|Sunday|Oct|October|10/15/23
2023-10-16 2023|23|10|16|16|289|42|42|1|Mon|Monday|Oct|October|10/16/23
2023-10-17 2023|23|10|17|17|290|42|42|2|Tue|Tuesday|Oct|October|10/17/23
2023-10-18 2023|23|10|18|18|291|42|42|3|Wed|Wednesday|Oct|October|10/18/23
2023-10-19 2023|23|10|19|19|292|42|42|4|Thu|Thursday|Oct|October|10/19/23
2023-10-20 2023|23|10|20|20|293|42|42|5|Fri|Friday|Oct|October|10/20/23
2023-10-21 2023|23|10|21|21|294|42|42|6|Sat|Saturday|Oct|October|10/21/23
2023-10-22 2023|23|10|22|22|295|43|42|0|Sun|Sunday|Oct|October|10/22/23
2023-10-23 2023|23|10|23|23|296|43|43|1|Mon|Monday|Oct|October|10/23/23
2023-10-24 2023|23|10|24|24|297|43|43|2|Tue|Tuesday|Oct|October|10/24/23
2023-10-25 2023|23|10|25|25|298|43|43|3|Wed|Wednesday|Oct|October|10/25/23
2023-10-26 2023|23|10|26|26|299|43|43|4|Thu|Thursday|Oct|October|10/26/23
2023-10-27 2023|23|10|27|27|300|43|43|5|Fri|Friday|Oct|October|10/27/23
2023-10-28 2023|23|10|28|28|301|43|43|6|Sat|Saturday|Oct|October|10/28/23
2023-10-29 2023|23|10|29|29|302|44|43|0|Sun|Sunday|Oct|October|10/29/23
2023-10-30 2023|23|10|30|30|303|44|44|1|Mon|Monday|Oct|October|10/30/23
2023-10-31 2023|23|10|31|31|304|44|44|2|Tue|Tuesday|Oct|October|10/31/23
2023-11-01 2023|23|11|01| 1|305|44|44|3|Wed|Wednesday|Nov|November|11/01/23
2023-11-02 2023|23|11|02| 2|306|44|44|4|Thu|Thursday|Nov|November|11/02/23
2023-11-03 2023|23|11|03| 3|307|44|44|5|Fri|Friday|Nov|November|11/03/23
2023-11-04 2023|23|11|04| 4|308|44|44|6|Sat|Saturday|Nov|November|11/04/23
2023-11-05 2023|23|11|05| 5|309|45|44|0|Sun|Sunday|Nov|November|11/05/23
2023-11-06 2023|23|11|06| 6|310|45|45|1|Mon|Monday|Nov|November|11/06/23
2023-11-07 2023|23|11|07| 7|311|45|45|2|Tue|Tuesday|Nov|November|11/07/23
2023-11-08 2023|23|11|08| 8|312|45|45|3|Wed|Wednesday|Nov|November|11/08/23
2023-11-09 2023|23|11|09| 9|313|45|45|4|Thu|Thursday|Nov|November|11/09/23
2023-11-10 2023|23|11|10|10|314|45|45|5|Fri|Friday|Nov|November|11/10/23
2023-11-11 2023|23|11|11|11|315|45|45|6|Sat|Saturday|Nov|November|11/11/23
2023-11-12 2023|23|11|12|12|316|46|45|0|Sun|Sunday|Nov|November|11/12/23
2023-11-13 2023|23|11|13|13|317|46|46|1|Mon|Monday|Nov|November|11/13/23
2023-11-14 2023|23|11|14|14|318|46|46|2|Tue|Tuesday|Nov|November|11/14/23
2023-11-15 2023|23|11|15|15|319|46|46|3|Wed|Wednesday|Nov|November|11/15/23
2023-11-16 2023|23|11|16|16|320|46|46|4|Thu|Thursday|Nov|November|11/16/23
2023-11-17 2023|23|11|17|17|321|46|46|5|Fri|Friday|Nov|November|11/17/23
2023-11-18 2023|23|11|18|18|322|46|46|6|Sat|Saturday|Nov|November|11/18/23
2023-11-19 2023|23|11|19|19|323|47|46|0|Sun|Sunday|Nov|November|11/19/23
2023-11-20 2023|23|11|20|20|324|47|47|1|Mon|Monday|Nov|November|11/20/23
2023-11-21 2023|23|11|21|21|325|47|47|2|Tue|Tuesday|Nov|November|11/21/23
2023-11-22 2023|23|11|22|22|326|47|47|3|Wed|Wednesday|Nov|November|11/22/23
2023-11-23 2023|23|11|23|23|327|47|47|4|Thu|Thursday|Nov|November|11/23/23
2023-11-24 2023|23|11|24|24|328|47|47|5|Fri|Friday|Nov|November|11/24/23
2023-11-25 2023|23|11|25|25|329|47|47|6|Sat|Saturday|Nov|November|11/25/23
2023-11-26 2023|23|11|26|26|330|48|47|0|Sun|Sunday|Nov|November|11/26/23
2023-11-27 2023|23|11|27|27|331|48|48|1|Mon|Monday|Nov|November|11/27/23
2023-11-28 2023|23|11|28|28|332|48|48|2|Tue|Tuesday|Nov|November|11/28/23
2023-11-29 2023|23|11|29|29|333|48|48|3|Wed|Wednesday|Nov|November|11/29/23
2023-11-30 2023|23|11|30|30|334|48|48|4|Thu|Thursday|Nov|November|11/30/23
2023-12-01 2023|23|12|01| 1|335|48|48|5|Fri|Friday|Dec|December|12/01/23
2023-12-02 2023|23|12|02| 2|336|48|48|6|Sat|Saturday|Dec|December|12/02/23
2023-12-03 2023|23|12|03| 3|337|49|48|0|Sun|Sunday|Dec|December|12/03/23
2023-12-04 2023|23|12|04| 4|338|49|49|1|Mon|Monday|Dec|December|12/04/23
2023-12-05 2023|23|12|05| 5|339|49|49|2|Tue|Tuesday|Dec|December|12/05/23
2023-12-06 2023|23|12|06| 6|340|49|49|3|Wed|Wednesday|Dec|December|12/06/23
2023-12-07 2023|23|12|07| 7|341|49|49|4|Thu|Thursday|Dec|December|12/07/23
2023-12-08 2023|23|12|08| 8|342|49|49|5|Fri|Friday|Dec|December|12/08/23
2023-12-09 2023|23|12|09| 9|343|49|49|6|Sat|Saturday|Dec|December|12/09/23
2023-12-10 2023|23|12|10|10|344|50|49|0|Sun|Sunday|Dec|December|12/10/23
2023-12-11 2023|23|12|11|11|345|50|50|1|Mon|Monday|Dec|December|12/11/23
2023-12-12 2023|23|12|12|12|346|50|50|2|Tue|Tuesday|Dec|December|12/12/23
2023-12-13 2023|23|12|13|13|347|50|50|3|Wed|Wednesday|Dec|December|12/13/23
2023-12-14 2023|23|12|14|14|348|50|50|4|Thu|Thursday|Dec|December|12/14/23
2023-12-15 2023|23|12|15|15|349|50|50|5|Fri|Friday|Dec|December|12/15/23
2023-12-16 2023|23|12|16|16|350|50|50|6|Sat|Saturday|Dec|December|12/16/23
2023-12-17 2023|23|12|17|17|351|51|50|0|Sun|Sunday|Dec|December|12/17/23
2023-12-18 2023|23|12|18|18|352|51|51|1|Mon|Monday|Dec|December|12/18/23
2023-12-19 2023|23|12|19|19|353|51|51|2|Tue|Tuesday|Dec|December|12/19/23
2023-12-20 2023|23|12|20|20|354|51|51|3|Wed|Wednesday|Dec|December|12/20/23
2023-12-21 2023|23|12|21|21|355|51|51|4|Thu|Thursday|Dec|December|12/21/23
2023-12-22 2023|23|12|22|22|356|51|51|5|Fri|Friday|Dec|December|12/22/23
2023-12-23 2023|23|12|23|23|357|51|51|6|Sat|Saturday|Dec|December|12/23/23
2023-12-24 2023|23|12|24|24|358|52|51|0|Sun|Sunday|Dec|December|12/24/23
2023-12-25 2023|23|12|25|25|359|52|52|1|Mon|Monday|Dec|December|12/25/23
2023-12-26 2023|23|12|26|26|360|52|52|2|Tue|Tuesday|Dec|December|12/26/23
2023-12-27 2023|23|12|27|27|361|52|52|3|Wed|Wednesday|Dec|December|12/27/23
2023-12-28 2023|23|12|28|28|362|52|52|4|Thu|Thursday|Dec|December|12/28/23
2023-12-29 2023|23|12|29|29|363|52|52|5|Fri|Friday|Dec|December|12/29/23
2023-12-30 2023|23|12|30|30|364|52|52|6|Sat|Saturday|Dec|December|12/30/23
2023-12-31 2023|23|12|31|31|365|53|52|0|Sun|Sunday|Dec|December|12/31/23
2024-01-01 2024|24|01|01| 1|001|00|01|1|Mon|Monday|Jan|January|01/01/24
2024-01-02 2024|24|01|02| 2|002|00|01|2|Tue|Tuesday|Jan|January|01/02/24
2024-01-03 2024|24|01|03| 3|003|00|01|3|Wed|Wednesday|Jan|January|01/03/24
2024-01-04 2024|24|01|04| 4|004|00|01|4|Thu|Thursday|Jan|January|01/04/24
2024-01-05 2024|24|01|05| 5|005|00|01|5|Fri|Friday|Jan|January|01/05/24
2024-01-06 2024|24|01|06| 6|006|00|01|6|Sat|Saturday|Jan|January|01/06/24
2024-01-07 2024|24|01|07| 7|007|01|01|0|Sun|Sunday|Jan|January|01/07/24
2024-01-08 2024|24|01|08| 8|008|01|02|1|Mon|Monday|Jan|January|01/08/24
2024-01-09 2024|24|01|09| 9|009|01|02|2|Tue|Tuesday|Jan|January|01/09/24
2024-01-10 2024|24|01|10|10|010|01|02|3|Wed|Wednesday|Jan|January|01/10/24
2024-01-11 2024|24|01|11|11|011|01|02|4|Thu|Thursday|Jan|January|01/11/24
2024-01-12 2024|24|01|12|12|012|01|02|5|Fri|Friday|Jan|January|01/12/24
2024-01-13 2024|24|01|13|13|013|01|02|6|Sat|Saturday|Jan|January|01/13/24
2024-01-14 2024|24|01|14|14|014|02|02|0|Sun|Sunday|Jan|January|01/14/24
2024-01-15 2024|24|01|15|15|015|02|03|1|Mon|Monday|Jan|January|01/15/24
2024-01-16 2024|24|01|16|16|016|02|03|2|Tue|Tuesday|Jan|January|01/16/24
2024-01-17 2024|24|01|17|17|017|02|03|3|Wed|Wednesday|Jan|January|01/17/24
2024-01-18 2024|24|01|18|18|018|02|03|4|Thu|Thursday|Jan|January|01/18/24
2024-01-19 2024|24|01|19|19|019|02|03|5|Fri|Friday|Jan|January|01/19/24
2024-01-20 2024|24|01|20|20|020|02|03|6|Sat|Saturday|Jan|January|01/20/24
2024-01-21 2024|24|01|21|21|021|03|03|0|Sun|Sunday|Jan|January|01/21/24
2024-01-22 2024|24|01|22|22|022|03|04|1|Mon|Monday|Jan|January|01/22/24
2024-01-23 2024|24|01|23|23|023|03|04|2|Tue|Tuesday|Jan|January|01/23/24
2024-01-24 2024|24|01|24|24|024|03|04|3|Wed|Wednesday|Jan|January|01/24/24
2024-01-25 2024|24|01|25|25|025|03|04|4|Thu|Thursday|Jan|January|01/25/24
2024-01-26 2024|24|01|26|26|026|03|04|5|Fri|Friday|Jan|January|01/26/24
2024-01-27 2024|24|01|27|27|027|03|04|6|Sat|Saturday|Jan|January|01/27/24
2024-01-28 2024|24|01|28|28|028|04|04|0|Sun|Sunday|Jan|January|01/28/24
2024-01-29 2024|24|01|29|29|029|04|05|1|Mon|Monday|Jan|January|01/29/24
2024-01-30 2024|24|01|30|30|030|04|05|2|Tue|Tuesday|Jan|January|01/30/24
2024-01-31 2024|24|01|31|31|031|04|05|3|Wed|Wednesday|Jan|January|01/31/24
2024-02-01 2024|24|02|01| 1|032|04|05|4|Thu|Thursday|Feb|February|02/01/24
2024-02-02 2024|24|02|02| 2|033|04|05|5|Fri|Friday|Feb|February|02/02/24
2024-02-03 2024|24|02|03| 3|034|04|05|6|Sat|Saturday|Feb|February|02/03/24
2024-02-04 2024|24|02|04| 4|035|05|05|0|Sun|Sunday|Feb|February|02/04/24
2024-02-05 2024|24|02|05| 5|036|05|06|1|Mon|Monday|Feb|February|02/05/24
2024-02-06 2024|24|02|06| 6|037|05|06|2|Tue|Tuesday|Feb|February|02/06/24
2024-02-07 2024|24|02|07| 7|038|05|06|3|Wed|Wednesday|Feb|February|02/07/24
2024-02-08 2024|24|02|08| 8|039|05|06|4|Thu|Thursday|Feb|February|02/08/24
2024-02-09 2024|24|02|09| 9|040|05|06|5|Fri|Friday|Feb|February|02/09/24
2024-02-10 2024|24|02|10|10|041|05|06|6|Sat|Saturday|Feb|February|02/10/24
2024-02-11 2024|24|02|11|11|042|06|06|0|Sun|Sunday|Feb|February|02/11/24
2024-02-12 2024|24|02|12|12|043|06|07|1|Mon|Monday|Feb|February|02/12/24
2024-02-13 2024|24|02|13|13|044|06|07|2|Tue|Tuesday|Feb|February|02/13/24
2024-02-14 2024|24|02|14|14|045|06|07|3|Wed|Wednesday|Feb|February|02/14/24
2024-02-15 2024|24|02|15|15|046|06|07|4|Thu|Thursday|Feb|February|02/15/24
2024-02-16 2024|24|02|16|16|047|06|07|5|Fri|Friday|Feb|February|02/16/24
2024-02-17 2024|24|02|17|17|048|06|07|6|Sat|Saturday|Feb|February|02/17/24
2024-02-18 2024|24|02|18|18|049|07|07|0|Sun|Sunday|Feb|February|02/18/24
2024-02-19 2024|24|02|19|19|050|07|08|1|Mon|Monday|Feb|February|02/19/24
2024-02-20 2024|24|02|20|20|051|07|08|2|Tue|Tuesday|Feb|February|02/20/24
2024-02-21 2024|24|02|21|21|052|07|08|3|Wed|Wednesday|Feb|February|02/21/24
2024-02-22 2024|24|02|22|22|053|07|08|4|Thu|Thursday|Feb|February|02/22/24
2024-02-23 2024|24|02|23|23|054|07|08|5|Fri|Friday|Feb|February|02/23/24
2024-02-24 2024|24|02|24|24|055|07|08|6|Sat|Saturday|Feb|February|02/24/24
2024-02-25 2024|24|02|25|25|056|08|08|0|Sun|Sunday|Feb|February|02/25/24
2024-02-26 2024|24|02|26|26|057|08|09|1|Mon|Monday|Feb|February|02/26/24
2024-02-27 2024|24|02|27|27|058|08|09|2|Tue|Tuesday|Feb|February|02/27/24
2024-02-28 2024|24|02|28|28|059|08|09|3|Wed|Wednesday|Feb|February|02/28/24
2024-02-29 2024|24|02|29|29|060|08|09|4|Thu|Thursday|Feb|February|02/29/24
2024-03-01 2024|24|03|01| 1|061|08|09|5|Fri|Friday|Mar|March|03/01/24
2024-03-02 2024|24|03|02| 2|062|08|09|6|Sat|Saturday|Mar|March|03/02/24
2024-03-03 2024|24|03|03| 3|063|09|09|0|Sun|Sunday|Mar|March|03/03/24
2024-03-04 2024|24|03|04| 4|064|09|10|1|Mon|Monday|Mar|March|03/04/24
2024-03-05 2024|24|03|05| 5|065|09|10|2|Tue|Tuesday|Mar|March|03/05/24
2024-03-06 2024|24|03|06| 6|066|09|10|3|Wed|Wednesday|Mar|March|03/06/24
2024-03-07 2024|24|03|07| 7|067|09|10|4|Thu|Thursday|Mar|March|03/07/24
2024-03-08 2024|24|03|08| 8|068|09|10|5|Fri|Friday|Mar|March|03/08/24
2024-03-09 2024|24|03|09| 9|069|09|10|6|Sat|Saturday|Mar|March|03/09/24
2024-03-10 2024|24|03|10|10|070|10|10|0|Sun|Sunday|Mar|March|03/10/24
2024-03-11 2024|24|03|11|11|071|10|11|1|Mon|Monday|Mar|March|03/11/24
2024-03-12 2024|24|03|12|12|072|10|11|2|Tue|Tuesday|Mar|March|03/12/24
2024-03-13 2024|24|03|13|13|073|10|11|3|Wed|Wednesday|Mar|March|03/13/24
2024-03-14 2024|24|03|14|14|074|10|11|4|Thu|Thursday|Mar|March|03/14/24
2024-03-15 2024|24|03|15|15|075|10|11|5|Fri|Friday|Mar|March|03/15/24
2024-03-16 2024|24|03|16|16|076|10|11|6|Sat|Saturday|Mar|March|03/16/24
2024-03-17 2024|24|03|17|17|077|11|11|0|Sun|Sunday|Mar|March|03/17/24
2024-03-18 2024|24|03|18|18|078|11|12|1|Mon|Monday|Mar|March|03/18/24
2024-03-19 2024|24|03|19|19|079|11|12|2|Tue|Tuesday|Mar|March|03/19/24
2024-03-20 2024|24|03|20|20|080|11|12|3|Wed|Wednesday|Mar|March|03/20/24
2024-03-21 2024|24|03|21|21|081|11|12|4|Thu|Thursday|Mar|March|03/21/24
2024-03-22 2024|24|03|22|22|082|11|12|5|Fri|Friday|Mar|March|03/22/24
2024-03-23 2024|24|03|23|23|083|11|12|6|Sat|Saturday|Mar|March|03/23/24
2024-03-24 2024|24|03|24|24|084|12|12|0|Sun|Sunday|Mar|March|03/24/24
2024-03-25 2024|24|03|25|25|085|12|13|1|Mon|Monday|Mar|March|03/25/24
2024-03-26 2024|24|03|26|26|086|12|13|2|Tue|Tuesday|Mar|March|03/26/24
2024-03-27 2024|24|03|27|27|087|12|13|3|Wed|Wednesday|Mar|March|03/27/24
2024-03-28 2024|24|03|28|28|088|12|13|4|Thu|Thursday|Mar|March|03/28/24
2024-03-29 2024|24|03|29|29|089|12|13|5|Fri|Friday|Mar|March|03/29/24
2024-03-30 2024|24|03|30|30|090|12|13|6|Sat|Saturday|Mar|March|03/30/24
2024-03-31 2024|24|03|31|31|091|13|13|0|Sun|Sunday|Mar|March|03/31/24
2024-04-01 2024|24|04|01| 1|092|13|14|1|Mon|Monday|Apr|April|04/01/24
2024-04-02 2024|24|04|02| 2|093|13|14|2|Tue|Tuesday|Apr|April|04/02/24
2024-04-03 2024|24|04|03| 3|094|13|14|3|Wed|Wednesday|Apr|April|04/03/24
2024-04-04 2024|24|04|04| 4|095|13|14|4|Thu|Thursday|Apr|April|04/04/24
2024-04-05 2024|24|04|05| 5|096|13|14|5|Fri|Friday|Apr|April|04/05/24
2024-04-06 2024|24|04|06| 6|097|13|14|6|Sat|Saturday|Apr|April|04/06/24
2024-04-07 2024|24|04|07| 7|098|14|14|0|Sun|Sunday|Apr|April|04/07/24
2024-04-08 2024|24|04|08| 8|099|14|15|1|Mon|Monday|Apr|April|04/08/24
2024-04-09 2024|24|04|09| 9|100|14|15|2|Tue|Tuesday|Apr|April|04/09/24
2024-04-10 2024|24|04|10|10|101|14|15|3|Wed|Wednesday|Apr|April|04/10/24
2024-04-11 2024|24|04|11|11|102|14|15|4|Thu|Thursday|Apr|April|04/11/24
2024-04-12 2024|24|04|12|12|103|14|15|5|Fri|Friday|Apr|April|04/12/24
2024-04-13 2024|24|04|13|13|104|14|15|6|Sat|Saturday|Apr|April|04/13/24
2024-04-14 2024|24|04|14|14|105|15|15|0|Sun|Sunday|Apr|April|04/14/24
2024-04-15 2024|24|04|15|15|106|15|16|1|Mon|Monday|Apr|April|04/15/24
2024-04-16 2024|24|04|16|16|107|15|16|2|Tue|Tuesday|Apr|April|04/16/24
2024-04-17 2024|24|04|17|17|108|15|16|3|Wed|Wednesday|Apr|April|04/17/24
2024-04-18 2024|24|04|18|18|109|15|16|4|Thu|Thursday|Apr|April|04/18/24
2024-04-19 2024|24|04|19|19|110|15|16|5|Fri|Friday|Apr|April|04/19/24
2024-04-20 2024|24|04|20|20|111|15|16|6|Sat|Saturday|Apr|April|04/20/24
2024-04-21 2024|24|04|21|21|112|16|16|0|Sun|Sunday|Apr|April|04/21/24
2024-04-22 2024|24|04|22|22|113|16|17|1|Mon|Monday|Apr|April|04/22/24
2024-04-23 2024|24|04|23|23|114|16|17|2|Tue|Tuesday|Apr|April|04/23/24
2024-04-24 2024|24|04|24|24|115|16|17|3|Wed|Wednesday|Apr|April|04/24/24
2024-04-25 2024|24|04|25|25|116|16|17|4|Thu|Thursday|Apr|April|04/25/24
2024-04-26 2024|24|04|26|26|117|16|17|5|Fri|Friday|Apr|April|04/26/24
2024-04-27 2024|24|04|27|27|118|16|17|6|Sat|Saturday|Apr|April|04/27/24
2024-04-28 2024|24|04|28|28|119|17|17|0|Sun|Sunday|Apr|April|04/28/24
2024-04-29 2024|24|04|29|29|120|17|18|1|Mon|Monday|Apr|April|04/29/24
2024-04-30 2024|24|04|30|30|121|17|18|2|Tue|Tuesday|Apr|April|04/30/24
2024-05-01 2024|24|05|01| 1|122|17|18|3|Wed|Wednesday|May|May|05/01/24
2024-05-02 2024|24|05|02| 2|123|17|18|4|Thu|Thursday|May|May|05/02/24
2024-05-03 2024|24|05|03| 3|124|17|18|5|Fri|Friday|May|May|05/03/24
2024-05-04 2024|24|05|04| 4|125|17|18|6|Sat|Saturday|May|May|05/04/24
2024-05-05 2024|24|05|05| 5|126|18|18|0|Sun|Sunday|May|May|05/05/24
2024-05-06 2024|24|05|06| 6|127|18|19|1|Mon|Monday|May|May|05/06/24
2024-05-07 2024|24|05|07| 7|128|18|19|2|Tue|Tuesday|May|May|05/07/24
2024-05-08 2024|24|05|08| 8|129|18|19|3|Wed|Wednesday|May|May|05/08/24
2024-05-09 2024|24|05|09| 9|130|18|19|4|Thu|Thursday|May|May|05/09/24
2024-05-10 2024|24|05|10|10|131|18|19|5|Fri|Friday|May|May|05/10/24
2024-05-11 2024|24|05|11|11|132|18|19|6|Sat|Saturday|May|May|05/11/24
2024-05-12 2024|24|05|12|12|133|19|19|0|Sun|Sunday|May|May|05/12/24
2024-05-13 2024|24|05|13|13|134|19|20|1|Mon|Monday|May|May|05/13/24
2024-05-14 2024|24|05|14|14|135|19|20|2|Tue|Tuesday|May|May|05/14/24
2024-05-15 2024|24|05|15|15|136|19|20|3|Wed|Wednesday|May|May|05/15/24
2024-05-16 2024|24|05|16|16|137|19|20|4|Thu|Thursday|May|May|05/16/24
2024-05-17 2024|24|05|17|17|138|19|20|5|Fri|Friday|May|May|05/17/24
2024-05-18 2024|24|05|18|18|139|19|20|6|Sat|Saturday|May|May|05/18/24
2024-05-19 2024|24|05|19|19|140|20|20|0|Sun|Sunday|May|May|05/19/24
2024-05-20 2024|24|05|20|20|141|20|21|1|Mon|Monday|May|May|05/20/24
2024-05-21 2024|24|05|21|21|142|20|21|2|Tue|Tuesday|May|May|05/21/24
2024-05-22 2024|24|05|22|22|143|20|21|3|Wed|Wednesday|May|May|05/22/24
2024-05-23 2024|24|05|23|23|144|20|21|4|Thu|Thursday|May|May|05/23/24
2024-05-24 2024|24|05|24|24|145|20|21|5|Fri|Friday|May|May|05/24/24
2024-05-25 2024|24|05|25|25|146|20|21|6|Sat|Saturday|May|May|05/25/24
2024-05-26 2024|24|05|26|26|147|21|21|0|Sun|Sunday|May|May|05/26/24
2024-05-27 2024|24|05|27|27|148|21|22|1|Mon|Monday|May|May|05/27/24
2024-05-28 2024|24|05|28|28|149|21|22|2|Tue|Tuesday|May|May|05/28/24
2024-05-29 2024|24|05|29|29|150|21|22|3|Wed|Wednesday|May|May|05/29/24
2024-05-30 2024|24|05|30|30|151|21|22|4|Thu|Thursday|May|May|05/30/24
2024-05-31 2024|24|05|31|31|152|21|22|5|Fri|Friday|May|May|05/31/24
2024-06-01 2024|24|06|01| 1|153|21|22|6|Sat|Saturday|Jun|June|06/01/24
2024-06-02 2024|24|06|02| 2|154|22|22|0|Sun|Sunday|Jun|June|06/02/24
2024-06-03 2024|24|06|03| 3|155|22|23|1|Mon|Monday|Jun|June|06/03/24
2024-06-04 2024|24|06|04| 4|156|22|23|2|Tue|Tuesday|Jun|June|06/04/24
2024-06-05 2024|24|06|05| 5|157|22|23|3|Wed|Wednesday|Jun|June|06/05/24
2024-06-06 2024|24|06|06| 6|158|22|23|4|Thu|Thursday|Jun|June|06/06/24
2024-06-07 2024|24|06|07| 7|159|22|23|5|Fri|Friday|Jun|June|06/07/24
2024-06-08 2024|24|06|08| 8|160|22|23|6|Sat|Saturday|Jun|June|06/08/24
2024-06-09 2024|24|06|09| 9|161|23|23|0|Sun|Sunday|Jun|June|06/09/24
2024-06-10 2024|24|06|10|10|162|23|24|1|Mon|Monday|Jun|June|06/10/24
2024-06-11 2024|24|06|11|11|163|23|24|2|Tue|Tuesday|Jun|June|06/11/24
2024-06-12 2024|24|06|12|12|164|23|24|3|Wed|Wednesday|Jun|June|06/12/24
2024-06-13 2024|24|06|13|13|165|23|24|4|Thu|Thursday|Jun|June|06/13/24
2024-06-14 2024|24|06|14|14|166|23|24|5|Fri|Friday|Jun|June|06/14/24
2024-06-15 2024|24|06|15|15|167|23|24|6|Sat|Saturday|Jun|June|06/15/24
2024-06-16 2024|24|06|16|16|168|24|24|0|Sun|Sunday|Jun|June|06/16/24
2024-06-17 2024|24|06|17|17|169|24|25|1|Mon|Monday|Jun|June|06/17/24
2024-06-18 2024|24|06|18|18|170|24|25|2|Tue|Tuesday|Jun|June|06/18/24
2024-06-19 2024|24|06|19|19|171|24|25|3|Wed|Wednesday|Jun|June|06/19/24
2024-06-20 2024|24|06|20|20|172|24|25|4|Thu|Thursday|Jun|June|06/20/24
2024-06-21 2024|24|06|21|21|173|24|25|5|Fri|Friday|Jun|June|06/21/24
2024-06-22 2024|24|06|22|22|174|24|25|6|Sat|Saturday|Jun|June|06/22/24
2024-06-23 2024|24|06|23|23|175|25|25|0|Sun|Sunday|Jun|June|06/23/24
2024-06-24 2024|24|06|24|24|176|25|26|1|Mon|Monday|Jun|June|06/24/24
2024-06-25 2024|24|06|25|25|177|25|26|2|Tue|Tuesday|Jun|June|06/25/24
2024-06-26 2024|24|06|26|26|178|25|26|3|Wed|Wednesday|Jun|June|06/26/24
2024-06-27 2024|24|06|27|27|179|25|26|4|Thu|Thursday|Jun|June|06/27/24
2024-06-28 2024|24|06|28|28|180|25|26|5|Fri|Friday|Jun|June|06/28/24
2024-06-29 2024|24|06|29|29|181|25|26|6|Sat|Saturday|Jun|June|06/29/24
2024-06-30 2024|24|06|30|30|182|26|26|0|Sun|Sunday|Jun|June|06/30/24
2024-07-01 2024|24|07|01| 1|183|26|27|1|Mon|Monday|Jul|July|07/01/24
2024-07-02 2024|24|07|02| 2|184|26|27|2|Tue|Tuesday|Jul|July|07/02/24
2024-07-03 2024|24|07|03| 3|185|26|27|3|Wed|Wednesday|Jul|July|07/03/24
2024-07-04 2024|24|07|04| 4|186|26|27|4|Thu|Thursday|Jul|July|07/04/24
2024-07-05 2024|24|07|05| 5|187|26|27|5|Fri|Friday|Jul|July|07/05/24
2024-07-06 2024|24|07|06| 6|188|26|27|6|Sat|Saturday|Jul|July|07/06/24
2024-07-07 2024|24|07|07| 7|189|27|27|0|Sun|Sunday|Jul|July|07/07/24
2024-07-08 2024|24|07|08| 8|190|27|28|1|Mon|Monday|Jul|July|07/08/24
2024-07-09 2024|24|07|09| 9|191|27|28|2|Tue|Tuesday|Jul|July|07/09/24
2024-07-10 2024|24|07|10|10|192|27|28|3|Wed|Wednesday|Jul|July|07/10/24
2024-07-11 2024|24|07|11|11|193|27|28|4|Thu|Thursday|Jul|July|07/11/24
2024-07-12 2024|24|07|12|12|194|27|28|5|Fri|Friday|Jul|July|07/12/24
2024-07-13 2024|24|07|13|13|195|27|28|6|Sat|Saturday|Jul|July|07/13/24
2024-07-14 2024|24|07|14|14|196|28|28|0|Sun|Sunday|Jul|July|07/14/24
2024-07-15 2024|24|07|15|15|197|28|29|1|Mon|Monday|Jul|July|07/15/24
2024-07-16 2024|24|07|16|16|198|28|29|2|Tue|Tuesday|Jul|July|07/16/24
2024-07-17 2024|24|07|17|17|199|28|29|3|Wed|Wednesday|Jul|July|07/17/24
2024-07-18 2024|24|07|18|18|200|28|29|4|Thu|Thursday|Jul|July|07/18/24
2024-07-19 2024|24|07|19|19|201|28|29|5|Fri|Friday|Jul|July|07/19/24
2024-07-20 2024|24|07|20|20|202|28|29|6|Sat|Saturday|Jul|July|07/20/24
2024-07-21 2024|24|07|21|21|203|29|29|0|Sun|Sunday|Jul|July|07/21/24
2024-07-22 2024|24|07|22|22|204|29|30|1|Mon|Monday|Jul|July|07/22/24
2024-07-23 2024|24|07|23|23|205|29|30|2|Tue|Tuesday|Jul|July|07/23/24
2024-07-24 2024|24|07|24|24|206|29|30|3|Wed|Wednesday|Jul|July|07/24/24
2024-07-25 2024|24|07|25|25|207|29|30|4|Thu|Thursday|Jul|July|07/25/24
2024-07-26 2024|24|07|26|26|208|29|30|5|Fri|Friday|Jul|July|07/26/24
2024-07-27 2024|24|07|27|27|209|29|30|6|Sat|Saturday|Jul|July|07/27/24
2024-07-28 2024|24|07|28|28|210|30|30|0|Sun|Sunday|Jul|July|07/28/24
2024-07-29 2024|24|07|29|29|211|30|31|1|Mon|Monday|Jul|July|07/29/24
2024-07-30 2024|24|07|30|30|212|30|31|2|Tue|Tuesday|Jul|July|07/30/24
2024-07-31 2024|24|07|31|31|213|30|31|3|Wed|Wednesday|Jul|July|07/31/24
2024-08-01 2024|24|08|01| 1|214|30|31|4|Thu|Thursday|Aug|August|08/01/24
2024-08-02 2024|24|08|02| 2|215|30|31|5|Fri|Friday|Aug|August|08/02/24
2024-08-03 2024|24|08|03| 3|216|30|31|6|Sat|Saturday|Aug|August|08/03/24
2024-08-04 2024|24|08|04| 4|217|31|31|0|Sun|Sunday|Aug|August|08/04/24
2024-08-05 2024|24|08|05| 5|218|31|32|1|Mon|Monday|Aug|August|08/05/24
2024-08-06 2024|24|08|06| 6|219|31|32|2|Tue|Tuesday|Aug|August|08/06/24
2024-08-07 2024|24|08|07| 7|220|31|32|3|Wed|Wednesday|Aug|August|08/07/24
2024-08-08 2024|24|08|08| 8|221|31|32|4|Thu|Thursday|Aug|August|08/08/24
2024-08-09 2024|24|08|09| 9|222|31|32|5|Fri|Friday|Aug|August|08/09/24
2024-08-10 2024|24|08|10|10|223|31|32|6|Sat|Saturday|Aug|August|08/10/24
2024-08-11 2024|24|08|11|11|224|32|32|0|Sun|Sunday|Aug|August|08/11/24
2024-08-12 2024|24|08|12|12|225|32|33|1|Mon|Monday|Aug|August|08/12/24
2024-08-13 2024|24|08|13|13|226|32|33|2|Tue|Tuesday|Aug|August|08/13/24
2024-08-14 2024|24|08|14|14|227|32|33|3|Wed|Wednesday|Aug|August|08/14/24
2024-08-15 2024|24|08|15|15|228|32|33|4|Thu|Thursday|Aug|August|08/15/24
2024-08-16 2024|24|08|16|16|229|32|33|5|Fri|Friday|Aug|August|08/16/24
2024-08-17 2024|24|08|17|17|230|32|33|6|Sat|Saturday|Aug|August|08/17/24
2024-08-18 2024|24|08|18|18|231|33|33|0|Sun|Sunday|Aug|August|08/18/24
2024-08-19 2024|24|08|19|19|232|33|34|1|Mon|Monday|Aug|August|08/19/24
2024-08-20 2024|24|08|20|20|233|33|34|2|Tue|Tuesday|Aug|August|08/20/24
2024-08-21 2024|24|08|21|21|234|33|34|3|Wed|Wednesday|Aug|August|08/21/24
2024-08-22 2024|24|08|22|22|235|33|34|4|Thu|Thursday|Aug|August|08/22/24
2024-08-23 2024|24|08|23|23|236|33|34|5|Fri|Friday|Aug|August|08/23/24
2024-08-24 2024|24|08|24|24|237|33|34|6|Sat|Saturday|Aug|August|08/24/24
2024-08-25 2024|24|08|25|25|238|34|34|0|Sun|Sunday|Aug|August|08/25/24
2024-08-26 2024|24|08|26|26|239|34|35|1|Mon|Monday|Aug|August|08/26/24
2024-08-27 2024|24|08|27|27|240|34|35|2|Tue|Tuesday|Aug|August|08/27/24
2024-08-28 2024|24|08|28|28|241|34|35|3|Wed|Wednesday|Aug|August|08/28/24
2024-08-29 2024|24|08|29|29|242|34|35|4|Thu|Thursday|Aug|August|08/29/24
2024-08-30 2024|24|08|30|30|243|34|35|5|Fri|Friday|Aug|August|08/30/24
2024-08-31 2024|24|08|31|31|244|34|35|6|Sat|Saturday|Aug|August|08/31/24
2024-09-01 2024|24|09|01| 1|245|35|35|0|Sun|Sunday|Sep|September|09/01/24
2024-09-02 2024|24|09|02| 2|246|35|36|1|Mon|Monday|Sep|September|09/02/24
2024-09-03 2024|24|09|03| 3|247|35|36|2|Tue|Tuesday|Sep|September|09/03/24
2024-09-04 2024|24|09|04| 4|248|35|36|3|Wed|Wednesday|Sep|September|09/04/24
2024-09-05 2024|24|09|05| 5|249|35|36|4|Thu|Thursday|Sep|September|09/05/24
2024-09-06 2024|24|09|06| 6|250|35|36|5|Fri|Friday|Sep|September|09/06/24
2024-09-07 2024|24|09|07| 7|251|35|36|6|Sat|Saturday|Sep|September|09/07/24
2024-09-08 2024|24|09|08| 8|252|36|36|0|Sun|Sunday|Sep|September|09/08/24
2024-09-09 2024|24|09|09| 9|253|36|37|1|Mon|Monday|Sep|September|09/09/24
2024-09-10 2024|24|09|10|10|254|36|37|2|Tue|Tuesday|Sep|September|09/10/24
2024-09-11 2024|24|09|11|11|255|36|37|3|Wed|Wednesday|Sep|September|09/11/24
2024-09-12 2024|24|09|12|12|256|36|37|4|Thu|Thursday|Sep|September|09/12/24
2024-09-13 2024|24|09|13|13|257|36|37|5|Fri|Friday|Sep|September|09/13/24
2024-09-14 2024|24|09|14|14|258|36|37|6|Sat|Saturday|Sep|September|09/14/24
2024-09-15 2024|24|09|15|15|259|37|37|0|Sun|Sunday|Sep|September|09/15/24
2024-09-16 2024|24|09|16|16|260|37|38|1|Mon|Monday|Sep|September|09/16/24
2024-09-17 2024|24|09|17|17|261|37|38|2|Tue|Tuesday|Sep|September|09/17/24
2024-09-18 2024|24|09|18|18|262|37|38|3|Wed|Wednesday|Sep|September|09/18/24
2024-09-19 2024|24|09|19|19|263|37|38|4|Thu|Thursday|Sep|September|09/19/24
2024-09-20 2024|24|09|20|20|264|37|38|5|Fri|Friday|Sep|September|09/20/24
2024-09-21 2024|24|09|21|21|265|37|38|6|Sat|Saturday|Sep|September|09/21/24
2024-09-22 2024|24|09|22|22|266|38|38|0|Sun|Sunday|Sep|September|09/22/24
2024-09-23 2024|24|09|23|23|267|38|39|1|Mon|Monday|Sep|September|09/23/24
2024-09-24 2024|24|09|24|24|268|38|39|2|Tue|Tuesday|Sep|September|09/24/24
2024-09-25 2024|24|09|25|25|269|38|39|3|Wed|Wednesday|Sep|September|09/25/24
2024-09-26 2024|24|09|26|26|270|38|39|4|Thu|Thursday|Sep|September|09/26/24
2024-09-27 2024|24|09|27|27|271|38|39|5|Fri|Friday|Sep|September|09/27/24
2024-09-28 2024|24|09|28|28|272|38|39|6|Sat|Saturday|Sep|September|09/28/24
2024-09-29 2024|24|09|29|29|273|39|39|0|Sun|Sunday|Sep|September|09/29/24
2024-09-30 2024|24|09|30|30|274|39|40|1|Mon|Monday|Sep|September|09/30/24
2024-10-01 2024|24|10|01| 1|275|39|40|2|Tue|Tuesday|Oct|October|10/01/24
2024-10-02 2024|24|10|02| 2|276|39|40|3|Wed|Wednesday|Oct|October|10/02/24
2024-10-03 2024|24|10|03| 3|277|39|40|4|Thu|Thursday|Oct|October|10/03/24
2024-10-04 2024|24|10|04| 4|278|39|40|5|Fri|Friday|Oct|October|10/04/24
2024-10-05 2024|24|10|05| 5|279|39|40|6|Sat|Saturday|Oct|October|10/05/24
2024-10-06 2024|24|10|06| 6|280|40|40|0|Sun|Sunday|Oct|October|10/06/24
2024-10-07 2024|24|10|07| 7|281|40|41|1|Mon|Monday|Oct|October|10/07/24
2024-10-08 2024|24|10|08| 8|282|40|41|2|Tue|Tuesday|Oct|October|10/08/24
2024-10-09 2024|24|10|09| 9|283|40|41|3|Wed|Wednesday|Oct|October|10/09/24
2024-10-10 2024|24|10|10|10|284|40|41|4|Thu|Thursday|Oct|October|10/10/24
2024-10-11 2024|24|10|11|11|285|40|41|5|Fri|Friday|Oct|October|10/11/24
2024-10-12 2024|24|10|12|12|286|40|41|6|Sat|Saturday|Oct|October|10/12/24
2024-10-13 2024|24|10|13|13|287|41|41|0|Sun|Sunday|Oct|October|10/13/24
2024-10-14 2024|24|10|14|14|288|41|42|1|Mon|Monday|Oct|October|10/14/24
2024-10-15 2024|24|10|15|15|289|41|42|2|Tue|Tuesday|Oct|October|10/15/24
2024-10-16 2024|24|10|16|16|290|41|42|3|Wed|Wednesday|Oct|October|10/16/24
2024-10-17 2024|24|10|17|17|291|41|42|4|Thu|Thursday|Oct|October|10/17/24
2024-10-18 2024|24|10|18|18|292|41|42|5|Fri|Friday|Oct|October|10/18/24
2024-10-19 2024|24|10|19|19|293|41|42|6|Sat|Saturday|Oct|October|10/19/24
2024-10-20 2024|24|10|20|20|294|42|42|0|Sun|Sunday|Oct|October|10/20/24
2024-10-21 2024|24|10|21|21|295|42|43|1|Mon|Monday|Oct|October|10/21/24
2024-10-22 2024|24|10|22|22|296|42|43|2|Tue|Tuesday|Oct|October|10/22/24
2024-10-23 2024|24|10|23|23|297|42|43|3|Wed|Wednesday|Oct|October|10/23/24
2024-10-24 2024|24|10|24|24|298|42|43|4|Thu|Thursday|Oct|October|10/24/24
2024-10-25 2024|24|10|25|25|299|42|43|5|Fri|Friday|Oct|October|10/25/24
2024-10-26 2024|24|10|26|26|300|42|43|6|Sat|Saturday|Oct|October|10/26/24
2024-10-27 2024|24|10|27|27|301|43|43|0|Sun|Sunday|Oct|October|10/27/24
2024-10-28 2024|24|10|28|28|302|43|44|1|Mon|Monday|Oct|October|10/28/24
2024-10-29 2024|24|10|29|29|303|43|44|2|Tue|Tuesday|Oct|October|10/29/24
2024-10-30 2024|24|10|30|30|304|43|44|3|Wed|Wednesday|Oct|October|10/30/24
2024-10-31 2024|24|10|31|31|305|43|44|4|Thu|Thursday|Oct|October|10/31/24
2024-11-01 2024|24|11|01| 1|306|43|44|5|Fri|Friday|Nov|November|11/01/24
2024-11-02 2024|24|11|02| 2|307|43|44|6|Sat|Saturday|Nov|November|11/02/24
2024-11-03 2024|24|11|03| 3|308|44|44|0|Sun|Sunday|Nov|November|11/03/24
2024-11-04 2024|24|11|04| 4|309|44|45|1|Mon|Monday|Nov|November|11/04/24
2024-11-05 2024|24|11|05| 5|310|44|45|2|Tue|Tuesday|Nov|November|11/05/24
2024-11-06 2024|24|11|06| 6|311|44|45|3|Wed|Wednesday|Nov|November|11/06/24
2024-11-07 2024|24|11|07| 7|312|44|45|4|Thu|Thursday|Nov|November|11/07/24
2024-11-08 2024|24|11|08| 8|313|44|45|5|Fri|Friday|Nov|November|11/08/24
2024-11-09 2024|24|11|09| 9|314|44|45|6|Sat|Saturday|Nov|November|11/09/24
2024-11-10 2024|24|11|10|10|315|45|45|0|Sun|Sunday|Nov|November|11/10/24
2024-11-11 2024|24|11|11|11|316|45|46|1|Mon|Monday|Nov|November|11/11/24
2024-11-12 2024|24|11|12|12|317|45|46|2|Tue|Tuesday|Nov|November|11/12/24
2024-11-13 2024|24|11|13|13|318|45|46|3|Wed|Wednesday|Nov|November|11/13/24
2024-11-14 2024|24|11|14|14|319|45|46|4|Thu|Thursday|Nov|November|11/14/24
2024-11-15 2024|24|11|15|15|320|45|46|5|Fri|Friday|Nov|November|11/15/24
2024-11-16 2024|24|11|16|16|321|45|46|6|Sat|Saturday|Nov|November|11/16/24
2024-11-17 2024|24|11|17|17|322|46|46|0|Sun|Sunday|Nov|November|11/17/24
2024-11-18 2024|24|11|18|18|323|46|47|1|Mon|Monday|Nov|November|11/18/24
2024-11-19 2024|24|11|19|19|324|46|47|2|Tue|Tuesday|Nov|November|11/19/24
2024-11-20 2024|24|11|20|20|325|46|47|3|Wed|Wednesday|Nov|November|11/20/24
2024-11-21 2024|24|11|21|21|326|46|47|4|Thu|Thursday|Nov|November|11/21/24
2024-11-22 2024|24|11|22|22|327|46|47|5|Fri|Friday|Nov|November|11/22/24
2024-11-23 2024|24|11|23|23|328|46|47|6|Sat|Saturday|Nov|November|11/23/24
2024-11-24 2024|24|11|24|24|329|47|47|0|Sun|Sunday|Nov|November|11/24/24
2024-11-25 2024|24|11|25|25|330|47|48|1|Mon|Monday|Nov|November|11/25/24
2024-11-26 2024|24|11|26|26|331|47|48|2|Tue|Tuesday|Nov|November|11/26/24
2024-11-27 2024|24|11|27|27|332|47|48|3|Wed|Wednesday|Nov|November|11/27/24
2024-11-28 2024|24|11|28|28|333|47|48|4|Thu|Thursday|Nov|November|11/28/24
2024-11-29 2024|24|11|29|29|334|47|48|5|Fri|Friday|Nov|November|11/29/24
2024-11-30 2024|24|11|30|30|335|47|48|6|Sat|Saturday|Nov|November|11/30/24
2024-12-01 2024|24|12|01| 1|336|48|48|0|Sun|Sunday|Dec|December|12/01/24
2024-12-02 2024|24|12|02| 2|337|48|49|1|Mon|Monday|Dec|December|12/02/24
2024-12-03 2024|24|12|03| 3|338|48|49|2|Tue|Tuesday|Dec|December|12/03/24
2024-12-04 2024|24|12|04| 4|339|48|49|3|Wed|Wednesday|Dec|December|12/04/24
2024-12-05 2024|24|12|05| 5|340|48|49|4|Thu|Thursday|Dec|December|12/05/24
2024-12-06 2024|24|12|06| 6|341|48|49|5|Fri|Friday|Dec|December|12/06/24
2024-12-07 2024|24|12|07| 7|342|48|49|6|Sat|Saturday|Dec|December|12/07/24
2024-12-08 2024|24|12|08| 8|343|49|49|0|Sun|Sunday|Dec|December|12/08/24
2024-12-09 2024|24|12|09| 9|344|49|50|1|Mon|Monday|Dec|December|12/09/24
2024-12-10 2024|24|12|10|10|345|49|50|2|Tue|Tuesday|Dec|December|12/10/24
2024-12-11 2024|24|12|11|11|346|49|50|3|Wed|Wednesday|Dec|December|12/11/24
2024-12-12 2024|24|12|12|12|347|49|50|4|Thu|Thursday|Dec|December|12/12/24
2024-12-13 2024|24|12|13|13|348|49|50|5|Fri|Friday|Dec|December|12/13/24
2024-12-14 2024|24|12|14|14|349|49|50|6|Sat|Saturday|Dec|December|12/14/24
2024-12-15 2024|24|12|15|15|350|50|50|0|Sun|Sunday|Dec|December|12/15/24
2024-12-16 2024|24|12|16|16|351|50|51|1|Mon|Monday|Dec|December|12/16/24
2024-12-17 2024|24|12|17|17|352|50|51|2|Tue|Tuesday|Dec|December|12/17/24
2024-12-18 2024|24|12|18|18|353|50|51|3|Wed|Wednesday|Dec|December|12/18/24
2024-12-19 2024|24|12|19|19|354|50|51|4|Thu|Thursday|Dec|December|12/19/24
2024-12-20 2024|24|12|20|20|355|50|51|5|Fri|Friday|Dec|December|12/20/24
2024-12-21 2024|24|12|21|21|356|50|51|6|Sat|Saturday|Dec|December|12/21/24
2024-12-22 2024|24|12|22|22|357|51|51|0|Sun|Sunday|Dec|December|12/22/24
2024-12-23 2024|24|12|23|23|358|51|52|1|Mon|Monday|Dec|December|12/23/24
2024-12-24 2024|24|12|24|24|359|51|52|2|Tue|Tuesday|Dec|December|12/24/24
2024-12-25 2024|24|12|25|25|360|51|52|3|Wed|Wednesday|Dec|December|12/25/24
2024-12-26 2024|24|12|26|26|361|51|52|4|Thu|Thursday|Dec|December|12/26/24
2024-12-27 2024|24|12|27|27|362|51|52|5|Fri|Friday|Dec|December|12/27/24
2024-12-28 2024|24|12|28|28|363|51|52|6|Sat|Saturday|Dec|December|12/28/24
2024-12-29 2024|24|12|29|29|364|52|52|0|Sun|Sunday|Dec|December|12/29/24
2024-12-30 2024|24|12|30|30|365|52|53|1|Mon|Monday|Dec|December|12/30/24
2024-12-31 2024|24|12|31|31|366|52|53|2|Tue|Tuesday|Dec|December|12/31/24
`
    .trim()
    .split("\n")
    .map((line) => [
        line.slice(0, line.indexOf(" ")),
        line.slice(line.indexOf(" ") + 1),
    ]);

const SWEEP_FORMAT = "%Y|%y|%m|%d|%e|%j|%U|%W|%w|%a|%A|%b|%B|%x";

/** @type {[string, string][]} */
const DELIBERATE_DEVIATIONS = [
    ["datetime.date(2024,1,31) + relativedelta(day=0)", "day 0 is out of range"],
    ["datetime.date(2024,1,31) + relativedelta(year=0)", "year 0 is out of range"],
];

describe("py_js dates vs CPython", () => {
    test("matches CPython across the generated corpus", () => {
        /** @type {string[]} */
        const divergences = [];
        for (const [expr, kind, expected] of CORPUS) {
            let got;
            let threw = false;
            try {
                got = canon(evaluateExpr(expr));
            } catch (e) {
                threw = true;
                got = e.message;
            }
            if (kind === "err") {
                if (!threw) {
                    divergences.push(`${expr} -> ${got}, CPython raises`);
                }
            } else if (threw) {
                divergences.push(`${expr} -> threw ${got}, CPython gives ${expected}`);
            } else if (got !== expected) {
                divergences.push(`${expr} -> ${got}, CPython gives ${expected}`);
            }
        }
        expect(divergences).toEqual([]);
    });

    test("matches CPython on every date directive, every day of two years", () => {
        /** @type {string[]} */
        const divergences = [];
        for (const [iso, expected] of YEAR_SWEEP) {
            const [y, m, d] = iso.split("-").map(Number);
            const expr = `datetime.date(${y},${m},${d}).strftime('${SWEEP_FORMAT}')`;
            let got;
            try {
                got = canon(evaluateExpr(expr));
            } catch (e) {
                got = `threw ${e.message}`;
            }
            if (got !== "s:" + expected) {
                divergences.push(`${expr} -> ${got}, CPython gives s:${expected}`);
            }
        }
        expect(divergences).toEqual([]);
    });

    test("rejects what CPython accepts, only where documented", () => {
        for (const [expr] of DELIBERATE_DEVIATIONS) {
            expect(() => evaluateExpr(expr)).toThrow();
        }
    });
});
