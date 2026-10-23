"""Portable portal rules shared by the Cloudflare D1 adapter.

This module intentionally contains no filesystem, SQLite, or Worker-runtime
imports.  It validates and transforms the same JSON contracts used by the
local FastAPI application so local development and production storage can
evolve independently without changing the frontend API shape.
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

try:
    from .portal_models import (
        COLLECTION_NAMES,
        MAX_COLLECTION_ROWS,
        MAX_PAYLOAD_BYTES,
        ROW_MODELS,
        AMCRate,
        EventItem,
        FixedDeposit,
        LedgerEntry,
        OpeningBalances,
        PaymentRecord,
        PortalModel,
        TallyReconciliation,
        json_record,
        normalize_mobile,
    )
except ImportError:
    from portal_models import (
    COLLECTION_NAMES,
    MAX_COLLECTION_ROWS,
    MAX_PAYLOAD_BYTES,
    ROW_MODELS,
    AMCRate,
    EventItem,
    FixedDeposit,
    LedgerEntry,
    OpeningBalances,
    PaymentRecord,
    PortalModel,
    TallyReconciliation,
    json_record,
    normalize_mobile,
    )


KOLKATA = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
RECEIPT_KINDS = {"Maintenance", "Advance AMC", "AMC Transfer", "Collections", "Membership"}
DEFAULT_AMC_RATES = [
    {"financialYear": "2026–27", "owner": 1000, "tenant": 500},
    {"financialYear": "2027–28", "owner": 1500, "tenant": 800},
]
DEFAULT_EXPENSE_TYPES = [
    "Waterman Charges", "Printing & Stationery", "Office Rent", "Office Expenses",
    "AGM Expenses", "Ganesha Festival Expenses", "Electricity Charges",
    "Cultural Program Expenses", "Repairs & Maintenance", "Bank Charges", "Audit Fees",
]
DEFAULT_OFFICE_BEARERS = [
    {"name": "Sh. K Bhaskarachar", "display": "Sri. K Bhaskarachar", "role": "President", "phone": ""},
    {"name": "Sh. Mahesh Krishnamurthy", "display": "Sri. Mahesh Krishnamurthy", "role": "General Secretary", "phone": ""},
    {"name": "Sh. Krishna Rao", "display": "Sri. Krishna Rao", "role": "Vice President 1", "phone": ""},
    {"name": "Smt. Roopa Rakesh", "display": "Smt. Roopa Rakesh", "role": "Vice President 2", "phone": ""},
    {"name": "Sh. Elangovan", "display": "Sri. Elangovan", "role": "Joint Secretary 1", "phone": ""},
    {"name": "Sh. Sunil Ghorpade", "display": "Sri. Sunil Ghorpade", "role": "Joint Secretary 2", "phone": ""},
    {"name": "Sh. Manjunath B K", "display": "Sri. Manjunath B K", "role": "Organising Secretary", "phone": ""},
    {"name": "Smt. Sowjanya", "display": "Smt. Sowjanya", "role": "Assistant Secretary", "phone": ""},
    {"name": "Sh. Abhilash", "display": "Sri. Abhilash", "role": "Treasurer", "phone": ""},
    {"name": "Sh. Mahesh More", "display": "Sri. Mahesh More", "role": "Office Secretary", "phone": ""},
    {"name": "Sh. Srihari", "display": "Sri. Srihari", "role": "Executive Committee Member", "phone": ""},
    {"name": "Sh. Nagesh Kumble", "display": "Sri. Nagesh Kumble", "role": "Executive Committee Member", "phone": ""},
    {"name": "Sh. Vasudev", "display": "Sri. Vasudev", "role": "Executive Committee Member", "phone": ""},
    {"name": "Sh. Rakesh Naidu", "display": "Sri. Rakesh Naidu", "role": "Executive Committee Member", "phone": ""},
]
OFFICIAL_PUBLIC_CONTACTS = [
    {
        "id": "emergency-112",
        "label": "Emergency response",
        "number": "112",
        "kind": "emergency",
        "source": "Official/public",
        "note": "Pan-India emergency response number for police, fire and medical help.",
    },
    {
        "id": "emergency-108",
        "label": "Ambulance / emergency medical transport",
        "number": "108",
        "kind": "emergency",
        "source": "Official/public",
        "note": "Emergency ambulance service; availability can vary by state and location.",
    },
]


def defaults() -> dict[str, Any]:
    return {
        "residents": [],
        "ledger": [],
        "payments": [],
        "amcRates": copy.deepcopy(DEFAULT_AMC_RATES),
        "openingBalances": None,
        "expenseTypes": list(DEFAULT_EXPENSE_TYPES),
        "fixedDeposits": [],
        "events": [],
        "officeBearers": copy.deepcopy(DEFAULT_OFFICE_BEARERS),
        "tallyReconciliation": None,
    }


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def format_amount(amount: float) -> str:
    whole, _, fractional = f"{amount:.2f}".partition(".")
    tail = whole[-3:]
    head = whole[:-3]
    groups: list[str] = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    formatted = ",".join([*groups, tail])
    return "₹ " + formatted + ("." + fractional if fractional != "00" else "")


def display_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{parsed.day:02d} {months[parsed.month - 1]} {parsed.year}"


def identity_text(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold()


def row_key(name: str, row: Any) -> str:
    if name == "expenseTypes":
        return identity_text(row)
    if name == "officeBearers":
        return identity_text(row["name"])
    return row["financialYear"] if name == "amcRates" else row["id"]


def invalid(label: str) -> ValueError:
    return ValueError(f"Invalid {label} data. Check field names, types, required values, dates and size limits.")


def model(model_type: type[PortalModel], value: Any, label: str) -> PortalModel:
    try:
        return model_type.model_validate(value)
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise invalid(label) from None


def validate_resident_uniqueness(residents: list[dict[str, Any]]) -> None:
    houses: set[str] = set()
    mobiles: set[str] = set()
    for resident in residents:
        house = identity_text(resident["house"])
        mobile = normalize_mobile(resident["mobile"])
        if house in houses or mobile in mobiles:
            raise ValueError("Each resident must have a unique house and registered phone number.")
        houses.add(house)
        mobiles.add(mobile)


def collection(name: str, value: Any, *, deduplicate: bool = False) -> tuple[Any, dict[str, str]]:
    if name not in COLLECTION_NAMES:
        raise ValueError("Unknown portal collection.")
    passwords: dict[str, str] = {}
    if name in {"openingBalances", "tallyReconciliation"}:
        if value is None:
            return None, passwords
        cls = OpeningBalances if name == "openingBalances" else TallyReconciliation
        return json_record(model(cls, value, name)), passwords
    if not isinstance(value, list) or len(value) > MAX_COLLECTION_ROWS:
        raise invalid(name)
    rows: list[Any] = []
    seen: dict[str, Any] = {}
    for raw in value:
        if name == "expenseTypes":
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 240:
                raise invalid(name)
            row: Any = raw.strip()
        else:
            parsed = model(ROW_MODELS[name], raw, name)
            if name == "residents" and parsed.password:
                passwords[parsed.id] = parsed.password
            row = json_record(parsed)
            if name == "payments":
                row["amount"] = format_amount(row["numericAmount"])
                if not row["date"]:
                    row["date"] = display_date(row["transactionDate"])
        key = row_key(name, row)
        if key in seen:
            if deduplicate and seen[key] == row:
                continue
            raise ValueError(f"Duplicate or conflicting identities in {name}.")
        seen[key] = row
        rows.append(row)
    if name == "residents":
        validate_resident_uniqueness(rows)
    return rows, passwords


def bind_records(name: str, rows: list[dict[str, Any]], residents: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["id"]: row for row in residents}
    by_house = {identity_text(row["house"]): row for row in residents}
    by_mobile = {row["mobile"]: row for row in residents}
    previous = {row["id"]: row for row in existing}
    result = copy.deepcopy(rows)
    for row in result:
        old = previous.get(row["id"])
        unchanged_identity = old is not None and row.get("house", "") == old.get("house", "") and (name == "ledger" or row.get("mobile", "") == old.get("mobile", ""))
        if not row.get("residentId") and unchanged_identity and old.get("residentId"):
            row["residentId"] = old["residentId"]
        if name == "payments" and row.get("mobile"):
            row["mobile"] = normalize_mobile(row["mobile"])
        resident_id = row.get("residentId")
        resident = None
        if resident_id:
            resident = by_id.get(resident_id)
            if resident is None:
                if unchanged_identity and old.get("residentId") == resident_id:
                    continue
                raise ValueError("A financial record references an unknown resident ID.")
            if not (unchanged_identity and old.get("residentId") == resident_id):
                if row.get("house") and identity_text(row["house"]) != identity_text(resident["house"]):
                    raise ValueError("The resident ID and house on a financial record disagree.")
                if name == "payments" and row.get("mobile") and row["mobile"] != resident["mobile"]:
                    raise ValueError("The resident ID and phone on a payment disagree.")
        else:
            house_match = by_house.get(identity_text(row.get("house") or ""))
            phone_match = by_mobile.get(row.get("mobile", "")) if name == "payments" else None
            if house_match and phone_match and house_match["id"] != phone_match["id"]:
                raise ValueError("A payment's house and phone identify different residents.")
            resident = None if unchanged_identity else phone_match or house_match
            if resident:
                if row.get("house") and identity_text(row["house"]) != identity_text(resident["house"]):
                    raise ValueError("A financial record's house disagrees with its registered resident.")
                if name == "payments" and row.get("mobile") and row["mobile"] != resident["mobile"]:
                    raise ValueError("A payment's phone disagrees with its registered resident.")
                row["residentId"] = resident["id"]
        if name == "payments" and resident:
            row["resident"] = row["resident"] or resident["name"]
            row["mobile"] = row["mobile"] or resident["mobile"]
            row["house"] = row["house"] or resident["house"]
    return result


def merge_ledger_append_only(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append new ledger IDs without ever replacing an existing record."""
    result = copy.deepcopy(existing)
    indexed = {row["id"]: row for row in existing}
    for row in incoming:
        prior = indexed.get(row["id"])
        if prior is not None:
            if prior != row:
                raise ValueError("An imported ledger identity conflicts with an existing record.")
            continue
        result.append(copy.deepcopy(row))
        indexed[row["id"]] = row
    if len(result) > MAX_COLLECTION_ROWS:
        raise ValueError("The merged ledger collection exceeds the record limit.")
    return result


def financial_year(value: date) -> str:
    start = value.year if value.month >= 4 else value.year - 1
    return f"{start}–{str(start + 1)[-2:]}"


def amc_financial_year(value: date) -> str:
    return f"{value.year}–{str(value.year + 1)[-2:]}" if value.month <= 3 else financial_year(value)


def transfer(advance: dict[str, Any]) -> dict[str, Any]:
    target = advance.get("amcForFinancialYear") or advance["financialYear"]
    start = int(target[:4])
    row = {
        "id": "AMC-XFER-" + advance["id"], "kind": "AMC Transfer", "amount": advance["amount"],
        "description": "Advance AMC transferred to AMC for FY " + target,
        "mode": "Non-cash reclassification", "date": f"{start}-04-01", "financialYear": target,
        "status": "Posted", "bucket": "AMC", "transferOf": advance["id"],
        "createdAt": datetime(start, 4, 1, tzinfo=KOLKATA).astimezone(timezone.utc).isoformat(),
    }
    for key in ("house", "residentId"):
        if key in advance:
            row[key] = advance[key]
    return json_record(model(LedgerEntry, row, "AMC transfer"))


def ensure_transfers(collections: dict[str, Any], today: date) -> None:
    ledger = collections["ledger"]
    by_id = {row["id"]: row for row in ledger}
    linked: set[str] = set()
    for current in [row for row in ledger if row["kind"] == "AMC Transfer"]:
        source_id = current["transferOf"]
        source = by_id.get(source_id)
        if source_id in linked or not source or source["kind"] != "Advance AMC" or source["status"] != "Posted":
            raise ValueError("AMC transfers must reference one posted advance exactly once.")
        expected = transfer(source)
        fields = ("id", "amount", "house", "residentId", "mode", "date", "financialYear", "status", "bucket", "transferOf")
        if any(current.get(key) != expected.get(key) for key in fields):
            raise ValueError("An AMC transfer conflicts with its source advance.")
        if today < date.fromisoformat(expected["date"]):
            raise ValueError("AMC advances cannot be reclassified before April 1 of the target financial year.")
        linked.add(source_id)
    for advance in ledger:
        if advance["kind"] != "Advance AMC" or advance["status"] != "Posted" or advance["id"] in linked:
            continue
        expected = transfer(advance)
        if today < date.fromisoformat(expected["date"]):
            continue
        if expected["id"] in by_id:
            raise ValueError("An AMC transfer ID conflicts with an existing ledger record.")
        ledger.append(expected)
        by_id[expected["id"]] = expected
        linked.add(advance["id"])


def guard_ledger_update(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> None:
    before = {row["id"]: row for row in old}
    after = {row["id"]: row for row in new}
    for row in old:
        if row["kind"] == "AMC Transfer" or row.get("paymentId"):
            if after.get(row["id"]) != row:
                raise ValueError("Payment receipts and automatic AMC transfers must be preserved by general ledger edits.")
    for row in new:
        if (row["kind"] == "AMC Transfer" or row.get("paymentId")) and before.get(row["id"]) != row:
            raise ValueError("Payment receipts and AMC transfers are created by the server.")


def guard_payment_update(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before = {row["id"]: row for row in old}
    if set(before) != {row["id"] for row in new}:
        raise ValueError("Create payment claims through resident submission; claims cannot be deleted through collection replacement.")
    result = copy.deepcopy(new)
    mutable = {"transactionDate", "mode", "details", "date"}
    for row in result:
        previous = before[row["id"]]
        if row["status"] != previous["status"]:
            raise ValueError("Use the payment review endpoint to approve or reject a payment.")
        if any(row.get(key) != previous.get(key) for key in set(row) | set(previous) if key not in mutable):
            raise ValueError("Payment identity, amount, review fields and accounting fields cannot be changed through collection replacement.")
        if previous["status"] == "Approved" and row != previous:
            raise ValueError("Approved payment details are already posted and cannot be edited independently of their receipt.")
        row["date"] = display_date(row["transactionDate"])
        if row["transactionDate"] != previous["transactionDate"]:
            parsed = date.fromisoformat(row["transactionDate"])
            if financial_year(parsed) != row["financialYear"] or (row["type"] == "Maintenance" and (parsed.month > 3 or amc_financial_year(parsed) != row.get("amcForFinancialYear"))):
                raise ValueError("A payment detail edit cannot move the claim to another financial year or AMC window.")
    return result


def amount_due(collections: dict[str, Any], resident: dict[str, Any], target_fy: str) -> float:
    rates = sorted(collections["amcRates"] or DEFAULT_AMC_RATES, key=lambda row: row["financialYear"])
    eligible = [row for row in rates if int(row["financialYear"][:4]) <= int(target_fy[:4])]
    rate = (eligible[-1] if eligible else rates[0])[resident["residentType"].lower()]
    transferred = {row["transferOf"] for row in collections["ledger"] if row["kind"] == "AMC Transfer" and row["status"] == "Posted"}
    paid = 0.0
    for row in collections["ledger"]:
        if row.get("residentId") != resident["id"] or row["status"] != "Posted":
            continue
        if row["kind"] in {"Maintenance", "AMC Transfer"} and row["financialYear"] == target_fy:
            paid += row["amount"]
        elif row["kind"] == "Advance AMC" and row["id"] not in transferred and (row.get("amcForFinancialYear") or row["financialYear"]) == target_fy:
            paid += row["amount"]
    return max(0.0, round(rate - paid, 2))


def posted_receipt(claim: dict[str, Any], now: str) -> dict[str, Any]:
    maintenance = claim["type"] == "Maintenance"
    membership = claim["type"] == "Membership"
    prefix = "REC-" if maintenance else "MEM-" if membership else "DON-"
    row = {
        "id": prefix + claim["id"], "paymentId": claim["id"],
        "kind": ("Advance AMC" if claim.get("amcBucket") == "Advance AMC" else "Maintenance") if maintenance else "Membership" if membership else "Collections",
        "amount": claim["numericAmount"], "house": claim["house"], "description": claim["details"],
        "mode": claim["mode"], "date": claim["transactionDate"], "financialYear": claim["financialYear"],
        "status": "Posted", "createdAt": claim.get("createdAt") or now,
    }
    if claim.get("residentId"):
        row["residentId"] = claim["residentId"]
    if maintenance:
        row.update(amcForFinancialYear=claim.get("amcForFinancialYear") or claim["financialYear"], bucket=claim.get("amcBucket") or "AMC")
    elif not membership:
        row.update(donorName=claim.get("donorName") or claim["resident"] or "Donor", donationType=claim.get("donationType") or "Ganesha Festival")
    return json_record(model(LedgerEntry, row, "posted receipt"))


def validate_storage_limits(collections: dict[str, Any]) -> None:
    for name in COLLECTION_NAMES:
        value = collections[name]
        if isinstance(value, list) and len(value) > MAX_COLLECTION_ROWS:
            raise ValueError(f"The {name} collection exceeds the record limit.")
        if len(json_text(value).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"The {name} collection exceeds the storage size limit.")


def public_resident(resident: dict[str, Any], account: dict[str, Any] | None) -> dict[str, Any]:
    sanitized = json_record(model(ROW_MODELS["residents"], resident, "stored resident"))
    sanitized["hasAccount"] = account is not None
    sanitized["tempPassword"] = bool(account is not None and account.get("must_change_password"))
    return sanitized


def public_contacts(office_bearers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return official numbers plus committee-published association contacts."""
    contacts = copy.deepcopy(OFFICIAL_PUBLIC_CONTACTS)
    for person in office_bearers:
        phone = str(person.get("phone") or "").strip()
        if not phone:
            continue
        role = str(person.get("role") or "Association contact")
        name = str(person.get("display") or person.get("name") or "")
        contacts.append({
            "id": "association-" + str(person.get("id") or person.get("name")),
            "label": role + (" — " + name if name else ""),
            "number": phone,
            "kind": "local",
            "source": "Association-maintained",
            "note": "Published by the APCLRWA committee; please confirm availability.",
        })
    return contacts
