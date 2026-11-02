"""系所聯絡方式：讀 data/contact.json。

這是我們自己維護的檔案，不是模型輸出，所以不經過出處驗證，也不會放進 prompt。
只放系所層級的公開資訊，不放承辦人個人的姓名或個人信箱。
資料有任何問題，整份不使用（卡片退回只顯示「請洽系辦」），伺服器照常啟動。
問題說明只含欄位名稱，不含檔案內容。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

CONTACT_FILE = "contact.json"

_KNOWN_KEYS = {"phones", "emails", "location", "office_hours", "sources", "checked_on"}
_PHONE_RE = re.compile(r"^[0-9+][0-9\-() #]{5,29}$")
_EMAIL_RE = re.compile(r"^[^\s@<>\"']+@[^\s@<>\"']+\.[^\s@<>\"']+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_TEXT = 200
_MAX_ITEMS = 20


@dataclass(frozen=True)
class Phone:
    number: str
    audience: tuple[str, ...]  # 適用對象（檔案裡的 for）


@dataclass(frozen=True)
class Email:
    address: str
    unit: str  # 所屬單位


@dataclass(frozen=True)
class Contact:
    phones: tuple[Phone, ...]
    emails: tuple[Email, ...]
    location: str  # 空字串 = 沒填
    office_hours: str  # 空字串 = 沒填，畫面整行不顯示
    sources: tuple[str, ...]  # 只存在檔案裡供維護核對，畫面不顯示
    checked_on: str  # YYYY-MM-DD


@dataclass(frozen=True)
class ContactLoad:
    contact: Contact | None
    notes: tuple[str, ...] = ()  # 啟動時印在終端機的說明；只含欄位名稱


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text and len(text) <= _MAX_TEXT else None


def _optional_text(value: object) -> str | None:
    """選填字串：沒寫或空字串都算空；型別錯或過長回傳 None 表示有問題。"""
    if value is None or value == "":
        return ""
    return _text(value)


def _parse(raw: dict[str, Any]) -> tuple[Contact | None, list[str]]:
    problems: list[str] = []

    for key in sorted(set(raw) - _KNOWN_KEYS):
        problems.append(f"不認得的欄位 {key}")  # 欄位名稱是我們自己寫的，不是敏感內容

    phones: list[Phone] = []
    raw_phones = raw.get("phones", [])
    if not isinstance(raw_phones, list) or len(raw_phones) > _MAX_ITEMS:
        problems.append("phones 必須是清單")
        raw_phones = []
    for i, item in enumerate(raw_phones):
        if not isinstance(item, dict) or set(item) != {"number", "for"}:
            problems.append(f"phones[{i}] 必須剛好有 number 與 for")
            continue
        number = _text(item["number"])
        if number is None or not _PHONE_RE.match(number):
            problems.append(f"phones[{i}].number 格式不對")
            continue
        audience = item["for"]
        names = [_text(a) for a in audience] if isinstance(audience, list) else []
        if not names or any(n is None for n in names):
            problems.append(f"phones[{i}].for 必須是非空字串的清單")
            continue
        phones.append(Phone(number, tuple(n for n in names if n)))

    emails: list[Email] = []
    raw_emails = raw.get("emails", [])
    if not isinstance(raw_emails, list) or len(raw_emails) > _MAX_ITEMS:
        problems.append("emails 必須是清單")
        raw_emails = []
    for i, item in enumerate(raw_emails):
        if not isinstance(item, dict) or set(item) != {"address", "unit"}:
            problems.append(f"emails[{i}] 必須剛好有 address 與 unit")
            continue
        address = _text(item["address"])
        if address is None or not _EMAIL_RE.match(address):
            problems.append(f"emails[{i}].address 格式不對")
            continue
        unit = _text(item["unit"])
        if unit is None:
            problems.append(f"emails[{i}].unit 必須是非空字串")
            continue
        emails.append(Email(address, unit))

    if not phones and not emails and not problems:
        problems.append("phones 與 emails 至少要有一項")

    location = _optional_text(raw.get("location"))
    if location is None:
        problems.append("location 必須是字串")
    office_hours = _optional_text(raw.get("office_hours"))
    if office_hours is None:
        problems.append("office_hours 必須是字串")

    sources: list[str] = []
    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources or len(raw_sources) > _MAX_ITEMS:
        problems.append("sources 必須是非空的網址清單")
    else:
        for i, url in enumerate(raw_sources):
            text = _text(url)
            if text is None or not re.match(r"^https?://\S+$", text):
                problems.append(f"sources[{i}] 必須是 http 或 https 網址")
            else:
                sources.append(text)

    checked_on = raw.get("checked_on")
    if not isinstance(checked_on, str) or not _DATE_RE.match(checked_on):
        problems.append("checked_on 必須是 YYYY-MM-DD")
    else:
        try:
            date.fromisoformat(checked_on)
        except ValueError:
            problems.append("checked_on 不是真的日期")

    if problems:
        return None, problems
    return (
        Contact(
            phones=tuple(phones),
            emails=tuple(emails),
            location=location or "",
            office_hours=office_hours or "",
            sources=tuple(sources),
            checked_on=checked_on,
        ),
        [],
    )


def load_contact(data_dir: Path) -> ContactLoad:
    """讀聯絡方式。任何問題都不丟例外：回傳沒有聯絡資料，並附上要印在終端機的說明。"""
    path = Path(data_dir) / CONTACT_FILE
    if not path.exists():
        return ContactLoad(None, (f"找不到 data/{CONTACT_FILE}，查不到卡等訊息只會顯示「請洽系辦」。",))
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return ContactLoad(None, (f"data/{CONTACT_FILE} 無法讀取或不是合法的 JSON，聯絡方式整份不顯示。",))
    if not isinstance(raw, dict):
        return ContactLoad(None, (f"data/{CONTACT_FILE} 最外層必須是物件，聯絡方式整份不顯示。",))
    contact, problems = _parse(raw)
    if contact is None:
        notes = tuple(f"data/{CONTACT_FILE} 有問題，聯絡方式整份不顯示：{p}" for p in problems)
        return ContactLoad(None, notes)
    return ContactLoad(contact)
