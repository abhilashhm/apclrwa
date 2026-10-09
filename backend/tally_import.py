"""Read-only Tally Excel export normalizer and book reconciliation.

The importer reads the Tally cash and bank books as the primary transaction
source. Separate ledger exports are used only as control checks because they
overlap the books. It writes a private JSON snapshot under data/ and never
modifies the source workbooks.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import xlrd


FISCAL_YEAR = "2026–27"
SOURCE_FILES = {
    "bank": "TALLY.xls",
    "cash": "TALLY1.xls",
    "prior_months": [
        "TALLY - 2025-2026 - Jan.xls",
        "TALLY - 2025-2026 - Feb.xls",
        "TALLY - 2025-2026 - Mar.xls",
    ],
}


def as_money(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def fy_for(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}–{str(start + 1)[-2:]}"


def cell_date(value: Any, datemode: int) -> date | None:
    if not isinstance(value, (int, float)) or value < 30000:
        return None
    try:
        return xlrd.xldate_as_datetime(value, datemode).date()
    except (ValueError, OverflowError):
        return None


def find_header(sheet: Any) -> tuple[int, list[str]]:
    for r in range(min(sheet.nrows, 15)):
        values = [str(v).strip().lower() for v in sheet.row_values(r)]
        if "date" in values and "particulars" in values:
            return r, values
    raise ValueError(f"Could not locate Date / Particulars header in {sheet.name}")


def row_text(row: list[Any]) -> str:
    return " ".join(str(v).strip() for v in row if isinstance(v, str) and v.strip())


def transaction_rows(book: Any, sheet: Any) -> list[dict[str, Any]]:
    header_row, headers = find_header(sheet)
    vch_i = next((i for i, v in enumerate(headers) if "vch type" in v or "voucher type" in v), None)
    debit_i = next((i for i, v in enumerate(headers) if v == "debit"), None)
    credit_i = next((i for i, v in enumerate(headers) if v == "credit"), None)
    if vch_i is None or debit_i is None or credit_i is None:
        raise ValueError(f"Missing voucher/debit/credit columns in {sheet.name}")
    vno_i = next((i for i, v in enumerate(headers) if "vch no" in v or "voucher no" in v), None)
    output: list[dict[str, Any]] = []
    allowed = {"receipt", "payment", "contra", "journal"}

    for r in range(header_row + 1, sheet.nrows):
        row = sheet.row_values(r)
        vch_type = str(row[vch_i]).strip() if vch_i < len(row) else ""
        if vch_type.casefold() not in allowed:
            continue
        txn_date = cell_date(row[0], book.datemode)
        if txn_date is None or fy_for(txn_date) != FISCAL_YEAR:
            continue
        side = str(row[1]).strip() if len(row) > 1 else ""
        label = str(row[2]).strip() if len(row) > 2 else ""
        debit = as_money(row[debit_i]) if debit_i < len(row) else 0.0
        credit = as_money(row[credit_i]) if credit_i < len(row) else 0.0
        voucher_no = str(row[vno_i]).strip() if vno_i is not None and vno_i < len(row) else ""
        details: list[str] = []
        components: list[dict[str, Any]] = []

        # Tally's compound receipts show the bank total followed by account
        # allocations. Use the allocations so AMC and membership aren't merged.
        if label.casefold() == "(as per details)":
            j = r + 1
            while j < sheet.nrows:
                sub = sheet.row_values(j)
                if cell_date(sub[0], book.datemode) is not None:
                    break
                sub_debit = as_money(sub[debit_i]) if debit_i < len(sub) else 0.0
                sub_credit = as_money(sub[credit_i]) if credit_i < len(sub) else 0.0
                sub_label = str(sub[1]).strip() if len(sub) > 1 else ""
                if sub_label.casefold() in {"to", "by", ""} and len(sub) > 2:
                    sub_label = str(sub[2]).strip()
                if sub_label and sub_label.casefold() not in {"to", "by"} and (sub_debit or sub_credit):
                    components.append({"side": "To" if sub_debit else "By", "ledger": sub_label, "amount": sub_debit or sub_credit})
                else:
                    txt = row_text(sub)
                    if txt and not re.fullmatch(r"[\d,. ]+", txt):
                        details.append(txt)
                j += 1
            if not components:
                components = [{"side": side, "ledger": label, "amount": debit or credit}]
        else:
            components = [{"side": side, "ledger": label, "amount": debit or credit}]
            j = r + 1
            while j < sheet.nrows:
                sub = sheet.row_values(j)
                if cell_date(sub[0], book.datemode) is not None:
                    break
                txt = row_text(sub)
                if txt and not re.fullmatch(r"[\d,. ]+", txt):
                    details.append(txt)
                j += 1

        output.append({
            "date": txn_date.isoformat(),
            "side": side,
            "voucherType": vch_type,
            "voucherNo": voucher_no,
            "debit": debit,
            "credit": credit,
            "details": " • ".join(dict.fromkeys(details)),
            "components": components,
        })
    return output


def identify_mode(book_name: str, details: str) -> str:
    if book_name == "cash":
        return "Cash"
    lower = details.casefold()
    if "upi" in lower:
        return "UPI"
    if "cheque" in lower or "ch. no" in lower or "chq" in lower:
        return "Cheque"
    if "neft" in lower or "imps" in lower:
        return "Bank transfer"
    return "Bank"


def classify(book_name: str, side: str, ledger: str, details: str, amount: float, voucher: dict[str, Any], index: int) -> dict[str, Any] | None:
    label = ledger.strip()
    key = re.sub(r"\s+", " ", label.casefold())
    if not amount:
        return None
    if book_name == "cash" and "cash at bank" in key:
        # The corresponding bank-book line is imported once as the transfer.
        return None

    entry: dict[str, Any] = {
        "amount": amount,
        "date": voucher["date"],
        "financialYear": fy_for(date.fromisoformat(voucher["date"])),
        "mode": identify_mode(book_name, details),
        "status": "Posted",
        "description": details or f"Tally {voucher['voucherType']} voucher {voucher['voucherNo']}",
    }
    if book_name == "bank" and "cash on hand" in key:
        entry.update(kind="Bank & Cash", direction="Bank → Cash" if side.casefold() == "by" else "Cash → Bank")
    elif "interest received" in key:
        entry.update(kind="Interest Received")
    elif book_name == "bank" and "fixed deposit" in key:
        entry.update(kind="Bank & Cash", direction="Bank → Fixed Deposit" if side.casefold() == "by" else "Fixed Deposit → Bank")
    elif "advance annual maintenance" in key or "advance amc" in key:
        target = 2027 if "2027" in key or "2027" in details else 2027
        entry.update(kind="Advance AMC", amcForFinancialYear=f"{target}–{str(target + 1)[-2:]}")
    elif "annual maintenance" in key:
        entry.update(kind="Maintenance")
    elif "membership" in key:
        entry.update(kind="Membership")
    elif "ganesha" in key and "collection" in key:
        entry.update(kind="Collections", donationType="Ganesha Festival")
    elif ("rama navami" in key or "rama navami" in details.casefold()) and "collection" in key:
        entry.update(kind="Collections", donationType="Sri Rama Navami")
    elif book_name == "bank" and side.casefold() == "to" and (
        "repair" in key or "maintenance" in key or "expense" in key or "fee" in key
    ):
        # A receipt credited to an expense ledger is a reduction of that cost.
        entry.update(kind="Expenses", amount=-amount, expenseType="Repairs & Maintenance", description=(details or label) + " • credit to expense ledger")
    elif side.casefold() == "by":
        expense_map = {
            "agm expenses": "AGM Expenses",
            "audit fee": "Audit Fees",
            "bank charges": "Bank Charges",
            "borewell repair & maintenance": "Repairs & Maintenance",
            "cultural programme expenses": "Cultural Program Expenses",
            "electricity charges": "Electricity Charges",
            "ganesha festival expenses": "Ganesha Festival Expenses",
            "office expenses": "Office Expenses",
            "office rent": "Office Rent",
            "printing & stationery": "Printing & Stationery",
            "service charges for waterman": "Waterman Charges",
        }
        entry.update(kind="Expenses", expenseType=expense_map.get(key, label))
    else:
        entry.update(kind="Other Income", description=f"{label}: {details}".strip(": "))

    source_key = f"{book_name}-{voucher['date']}-{voucher['voucherType']}-{voucher['voucherNo']}-{index}-{key}"
    entry["id"] = "TALLY-" + re.sub(r"[^A-Za-z0-9]+", "-", source_key).strip("-")
    if entry["kind"] == "Collections" and entry.get("donationType"):
        entry["description"] = details or label
    return entry


def parse_prior_year_receipts(source_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    categories = {
        "advance annual maintenance charges": ("Advance AMC", "2026–27", None),
        "membership collections": ("Membership", None, None),
        "rama navami receipts": ("Collections", None, "Sri Rama Navami"),
    }
    for filename in SOURCE_FILES["prior_months"]:
        book = xlrd.open_workbook(str(source_dir / filename), on_demand=True)
        sheet = book.sheet_by_index(0)
        header_row = next((r for r in range(min(sheet.nrows, 10)) if "date" in [str(v).strip().lower() for v in sheet.row_values(r)]), None)
        if header_row is None:
            continue
        headers = [str(v).strip().lower() for v in sheet.row_values(header_row)]
        particulars_i = headers.index("particulars")
        vtype_i = next(i for i, v in enumerate(headers) if "voucher type" in v)
        vno_i = next((i for i, v in enumerate(headers) if "vch no" in v or "voucher no" in v), None)
        narration_i = headers.index("narration") if "narration" in headers else None
        gross_i = headers.index("gross total") if "gross total" in headers else None
        fy = "2025–26"
        for r in range(header_row + 1, sheet.nrows):
            raw = sheet.row_values(r)
            d = cell_date(raw[0], book.datemode)
            if d is None or str(raw[vtype_i]).strip().casefold() != "receipt":
                continue
            particulars = str(raw[particulars_i]).strip()
            narration = str(raw[narration_i]).strip() if narration_i is not None else ""
            vno = str(raw[vno_i]).strip() if vno_i is not None else str(r)
            for ci, label in enumerate(headers):
                spec = categories.get(label)
                if not spec:
                    continue
                amount = as_money(raw[ci])
                if amount <= 0:
                    continue
                kind, target_fy, donation = spec
                entry: dict[str, Any] = {
                    "id": f"TALLY-PRIOR-{d.isoformat()}-{vno}-{kind.replace(' ', '-')}",
                    "kind": kind,
                    "amount": amount,
                    "date": d.isoformat(),
                    "financialYear": fy,
                    "mode": "Cash" if particulars.casefold() == "cash" else "Bank",
                    "status": "Posted",
                    "description": narration or f"{filename} receipt {vno}",
                }
                if target_fy:
                    entry["amcForFinancialYear"] = target_fy
                if donation:
                    entry["donationType"] = donation
                rows.append(entry)
    return rows


def extract_controls(source_dir: Path) -> dict[str, Any]:
    bank_book = xlrd.open_workbook(str(source_dir / SOURCE_FILES["bank"]), on_demand=True)
    bank_sheet = bank_book.sheet_by_name("Sheet1")
    cash_book = xlrd.open_workbook(str(source_dir / SOURCE_FILES["cash"]), on_demand=True)
    cash_sheet = cash_book.sheet_by_name("Cash on Hand  Book")

    def control(book: Any, sheet: Any) -> dict[str, float]:
        header_row, headers = find_header(sheet)
        debit_i, credit_i = headers.index("debit"), headers.index("credit")
        vch_i = next(i for i, v in enumerate(headers) if "vch type" in v or "voucher type" in v)
        opening = debit = credit = closing = 0.0
        for r in range(header_row + 1, sheet.nrows):
            raw = sheet.row_values(r)
            text = row_text(raw).casefold()
            if "opening balance" in text:
                opening = as_money(raw[debit_i]) + as_money(raw[credit_i])
            elif "closing balance" in text:
                closing = as_money(raw[debit_i]) + as_money(raw[credit_i])
            elif str(raw[vch_i]).strip().casefold() in {"receipt", "payment", "contra", "journal"}:
                debit += as_money(raw[debit_i])
                credit += as_money(raw[credit_i])
        return {"opening": opening, "receipts": debit, "payments": credit, "closing": closing, "calculatedClosing": opening + debit - credit}

    bank = control(bank_book, bank_sheet)
    cash = control(cash_book, cash_sheet)

    summary_book = bank_book
    summary = summary_book.sheet_by_name("Cash at Bank 2615101006555")
    summary_row = next((summary.row_values(r) for r in range(summary.nrows) if "Grand Total" in [str(x).strip() for x in summary.row_values(r)]), None)
    if summary_row:
        bank["summaryReceipts"] = as_money(summary_row[1])
        bank["summaryPayments"] = as_money(summary_row[2])
        bank["summaryClosing"] = as_money(summary_row[3])

    bsheet = xlrd.open_workbook(str(source_dir / "BSheet.xls"), on_demand=True).sheet_by_index(0)
    prior_cash = prior_bank = 0.0
    for r in range(bsheet.nrows):
        raw = bsheet.row_values(r)
        label = str(raw[3]).strip().casefold() if len(raw) > 3 else ""
        if label == "cash-in-hand":
            prior_cash = as_money(raw[4])
        elif label == "bank accounts":
            prior_bank = as_money(raw[4])

    return {
        "bank": bank,
        "cash": cash,
        "priorBalanceSheet": {"asOf": "2026-03-29", "bank": prior_bank, "cash": prior_cash},
    }


def ledger_support_checks(source_dir: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_income = defaultdict(float)
    for x in entries:
        if x["financialYear"] == FISCAL_YEAR:
            all_income[x.get("kind") + ":" + str(x.get("expenseType") or x.get("donationType") or x.get("kind"))] += x["amount"]
    checks: list[dict[str, Any]] = []
    amc_files = ["AMC 26 Apr.xls", "AMC 26 May.xls", "AMC 26 June.xls", "AMC 26 July.xls"]
    support_total = 0.0
    for filename in amc_files:
        book = xlrd.open_workbook(str(source_dir / filename), on_demand=True)
        sheet = book.sheet_by_index(0)
        _, headers = find_header(sheet)
        vch_i = next(i for i, v in enumerate(headers) if "vch type" in v or "voucher type" in v)
        credit_i = headers.index("credit")
        for r in range(3, sheet.nrows):
            raw = sheet.row_values(r)
            if str(raw[vch_i]).strip().casefold() == "receipt":
                support_total += as_money(raw[credit_i])
    main_amc = sum(x["amount"] for x in entries if x["financialYear"] == FISCAL_YEAR and x["kind"] == "Maintenance")
    checks.append({"name": "Annual AMC detail exports vs current bank/cash books", "bookAmount": main_amc, "supportAmount": support_total, "difference": main_amc - support_total, "status": "MATCH" if main_amc == support_total else "SUPPORT_EXPORTS_INCOMPLETE"})

    agm_book = xlrd.open_workbook(str(source_dir / "agm.xls"), on_demand=True)
    sheet = agm_book.sheet_by_index(0)
    _, headers = find_header(sheet)
    vch_i, debit_i = next(i for i, v in enumerate(headers) if "vch type" in v), headers.index("debit")
    known_transactions = opening = reported_close = 0.0
    for r in range(3, sheet.nrows):
        raw = sheet.row_values(r)
        text = row_text(raw).casefold()
        if "opening balance" in text:
            opening = as_money(raw[debit_i])
        elif "closing balance" in text:
            reported_close = as_money(raw[headers.index("credit")])
        elif str(raw[vch_i]).strip().casefold() == "payment":
            known_transactions += as_money(raw[debit_i])
    book_agm = sum(x["amount"] for x in entries if x["financialYear"] == FISCAL_YEAR and x.get("expenseType") == "AGM Expenses")
    support_known = opening + known_transactions
    checks.append({"name": "AGM ledger voucher detail vs cash book", "bookAmount": book_agm, "supportKnownAmount": support_known, "supportClosingBalance": reported_close, "difference": book_agm - support_known, "status": "MATCH" if book_agm == support_known else "MISSING_VOUCHER_AMOUNT_IN_SUPPORT_EXPORT"})
    return checks


def build_import(source_dir: Path) -> dict[str, Any]:
    bank_book = xlrd.open_workbook(str(source_dir / SOURCE_FILES["bank"]), on_demand=True)
    cash_book = xlrd.open_workbook(str(source_dir / SOURCE_FILES["cash"]), on_demand=True)
    bank_rows = transaction_rows(bank_book, bank_book.sheet_by_name("Sheet1"))
    cash_rows = transaction_rows(cash_book, cash_book.sheet_by_name("Cash on Hand  Book"))
    entries: list[dict[str, Any]] = []
    for book_name, transactions in (("bank", bank_rows), ("cash", cash_rows)):
        for txn_index, voucher in enumerate(transactions, start=1):
            for component_index, comp in enumerate(voucher["components"], start=1):
                entry = classify(book_name, comp["side"], comp["ledger"], voucher["details"], comp["amount"], voucher, txn_index * 10 + component_index)
                if entry:
                    entries.append(entry)

    prior = parse_prior_year_receipts(source_dir)
    entries.extend(prior)
    controls = extract_controls(source_dir)
    reconciliation = {
        "financialYear": FISCAL_YEAR,
        "sourcePeriodThrough": max((x["date"] for x in entries if x["financialYear"] == FISCAL_YEAR), default=""),
        "bank": controls["bank"],
        "cash": controls["cash"],
        "combined": {
            "opening": controls["bank"]["opening"] + controls["cash"]["opening"],
            "receipts": controls["bank"]["receipts"] + controls["cash"]["receipts"],
            "payments": controls["bank"]["payments"] + controls["cash"]["payments"],
            "closing": controls["bank"]["closing"] + controls["cash"]["closing"],
        },
        "openingBalanceComparison": {
            "bankDifference": controls["bank"]["opening"] - controls["priorBalanceSheet"]["bank"],
            "cashDifference": controls["cash"]["opening"] - controls["priorBalanceSheet"]["cash"],
            "priorBalanceSheet": controls["priorBalanceSheet"],
        },
        "checks": [
            {"name": "Bank book roll-forward", "difference": controls["bank"]["calculatedClosing"] - controls["bank"]["closing"], "status": "MATCH" if controls["bank"]["calculatedClosing"] == controls["bank"]["closing"] else "UNMATCHED"},
            {"name": "Cash book roll-forward", "difference": controls["cash"]["calculatedClosing"] - controls["cash"]["closing"], "status": "MATCH" if controls["cash"]["calculatedClosing"] == controls["cash"]["closing"] else "UNMATCHED"},
            {"name": "Opening bank vs 2025–26 balance sheet", "difference": controls["bank"]["opening"] - controls["priorBalanceSheet"]["bank"], "status": "MATCH" if controls["bank"]["opening"] == controls["priorBalanceSheet"]["bank"] else "DATE_GAP_OR_VARIANCE"},
            {"name": "Opening cash vs 2025–26 balance sheet", "difference": controls["cash"]["opening"] - controls["priorBalanceSheet"]["cash"], "status": "MATCH" if controls["cash"]["opening"] == controls["priorBalanceSheet"]["cash"] else "DATE_GAP_OR_VARIANCE"},
        ],
    }
    reconciliation["checks"].extend(ledger_support_checks(source_dir, entries))
    return {
        "importId": "TALLY-2026-10-04-v1",
        "financialYear": FISCAL_YEAR,
        "sourceFiles": [SOURCE_FILES["bank"], SOURCE_FILES["cash"], "BSheet.xls", *SOURCE_FILES["prior_months"]],
        "openingBalances": {"financialYear": FISCAL_YEAR, "date": "2026-04-01", "bank": controls["bank"]["opening"], "cash": controls["cash"]["opening"]},
        "reconciliation": reconciliation,
        "transactions": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Tally Excel books and reconcile cash/bank control totals.")
    parser.add_argument("--source-dir", type=Path, default=Path(r"C:\Tally.ERP9"))
    parser.add_argument("--output", type=Path, default=Path("data/tally-import.json"))
    args = parser.parse_args()
    result = build_import(args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(result['transactions'])} records to {args.output}")
    print(json.dumps(result["reconciliation"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
