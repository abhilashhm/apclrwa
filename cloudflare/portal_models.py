"""Worker-local copy of the JSON contracts used by the D1 adapter.

The Cloudflare Python bundler packages sibling modules, not arbitrary parent
packages. This file mirrors the backend contracts so the Worker bundle does
not depend on the local ``backend`` package. Local FastAPI continues to use
``backend.portal_models``.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_COLLECTION_ROWS = 25000
MAX_MONEY = 1_000_000_000_000
MAX_MINOR_UNITS = MAX_MONEY * 100
COLLECTION_NAMES = (
    "residents", "ledger", "payments", "amcRates", "openingBalances",
    "expenseTypes", "fixedDeposits", "events", "officeBearers", "tallyReconciliation",
)

StableId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)]
OptionalPrivateText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
DetailsText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
Money = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-MAX_MONEY, le=MAX_MONEY)]
NonnegativeMoney = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=MAX_MONEY)]
PositiveMoney = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0, le=MAX_MONEY)]
Revision = Annotated[int, Field(strict=True, ge=0)]
PaymentMode = Literal["UPI", "Bank transfer", "Cash", "Cheque", "Bank"]


def normalize_mobile(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[+0-9\s().-]+", value):
        raise ValueError("Use a phone number for the resident login.")
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not 3 <= len(digits) <= 15:
        raise ValueError("The phone number must contain between 3 and 15 digits.")
    return digits


def financial_year(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Use a financial year such as 2026–27.")
    match = re.fullmatch(r"(\d{4})[–-](\d{2})", value.strip())
    if not match or not 1900 <= int(match[1]) <= 9998 or int(match[2]) != (int(match[1]) + 1) % 100:
        raise ValueError("Use a consecutive financial year such as 2026–27.")
    return f"{match[1]}–{match[2]}"


def financial_year_for_date(value: date) -> str:
    start = value.year if value.month >= 4 else value.year - 1
    return f"{start}–{str(start + 1)[-2:]}"


def financial_year_bounds(value: str) -> tuple[date, date]:
    canonical = financial_year(value)
    start_year = int(canonical[:4])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def iso_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use an ISO date (YYYY-MM-DD).")
    date.fromisoformat(value)
    return value


def timestamp(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Use an ISO timestamp.")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def safe_image(value: str | None) -> str | None:
    if not value:
        return value
    if not isinstance(value, str):
        raise ValueError("Use an image URL or base64 image.")
    if value.startswith("data:"):
        if len(value) > 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 100:
            raise ValueError("Images must be at most 4 MiB.")
        header, separator, encoded = value.partition(",")
        if not separator or header.lower() not in {
            "data:image/jpeg;base64", "data:image/jpg;base64", "data:image/png;base64",
            "data:image/gif;base64", "data:image/webp;base64",
        }:
            raise ValueError("Use a PNG, JPEG, GIF or WebP base64 image.")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("The base64 image is invalid.") from exc
        if not decoded or len(decoded) > MAX_IMAGE_BYTES:
            raise ValueError("Images must be nonempty and at most 4 MiB.")
        return value
    if len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise ValueError("The image URL is invalid.")
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Use an HTTP(S) image URL or a site-relative path.")
    return value


class PortalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class PaymentDetails(PortalModel):
    date: str
    mode: PaymentMode
    details: DetailsText
    _date = field_validator("date")(iso_date)


class ResidentRecord(PortalModel):
    id: StableId
    house: RequiredText
    cross: ShortText = ""
    name: RequiredText
    mobile: str
    residentType: Literal["Owner", "Tenant", "Unspecified"] = "Unspecified"
    profession: OptionalPrivateText | None = None
    tenantOwnerName: OptionalPrivateText | None = None
    publicProfessionalListing: bool = False
    initialCharge: NonnegativeMoney = 500
    initialChargePaid: bool = False
    membershipPayment: PaymentDetails | None = None
    active: bool = True
    createdAt: str = ""
    password: Annotated[str | None, Field(max_length=1024, exclude=True, repr=False)] = None
    tempPassword: Annotated[bool | None, Field(exclude=True)] = None
    hasAccount: Annotated[bool | None, Field(exclude=True)] = None

    _mobile = field_validator("mobile")(normalize_mobile)
    _created = field_validator("createdAt")(timestamp)

    @field_validator("profession", "tenantOwnerName", mode="before")
    @classmethod
    def blank_private_text_is_missing(cls, value: Any) -> Any:
        # Existing committee forms send an empty string for optional inputs.
        # Store that as an absent value so blank private fields do not become
        # visible directory data on a later snapshot.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        if value and len(value) < 12:
            raise ValueError("A temporary password must have at least 12 characters.")
        return value

    @model_validator(mode="after")
    def membership(self) -> "ResidentRecord":
        if self.initialCharge != 500:
            raise ValueError("The one-time membership charge is 500.")
        if self.initialChargePaid and self.membershipPayment is None:
            raise ValueError("Paid membership requires payment date, mode and details.")
        if not self.initialChargePaid:
            self.membershipPayment = None
        if self.publicProfessionalListing and not self.profession:
            raise ValueError("A public professional listing requires a profession.")
        return self


class LedgerEntry(PortalModel):
    id: StableId
    kind: Literal["Maintenance", "Advance AMC", "AMC Transfer", "Collections", "Expenses", "Bank & Cash", "Membership", "Interest Received", "Other Income"]
    amount: Money
    house: ShortText | None = None
    residentId: StableId | None = None
    paymentId: StableId | None = None
    description: DetailsText
    mode: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    date: str
    financialYear: str
    amcForFinancialYear: str | None = None
    status: Literal["Posted", "Draft", "Pending", "Pending verification", "Rejected", "Approved", "Paid"] = "Posted"
    expenseType: ShortText | None = None
    direction: Literal["Bank → Cash", "Cash → Bank", "Bank → Fixed Deposit", "Fixed Deposit → Bank"] | None = None
    donorName: ShortText | None = None
    donationType: ShortText | None = None
    bucket: ShortText | None = None
    transferOf: StableId | None = None
    createdAt: str | None = None

    _date = field_validator("date")(iso_date)
    _fy = field_validator("financialYear")(financial_year)
    _target_fy = field_validator("amcForFinancialYear")(lambda value: financial_year(value) if value is not None else None)
    _created = field_validator("createdAt")(timestamp)

    @model_validator(mode="after")
    def semantics(self) -> "LedgerEntry":
        if self.amount == 0 or (self.kind != "Expenses" and self.amount < 0):
            raise ValueError("The ledger amount must be positive (expense credits may be negative).")
        if self.kind == "Expenses" and not self.expenseType:
            raise ValueError("Expenses require an expense type.")
        if self.kind == "Bank & Cash" and not self.direction:
            raise ValueError("A bank/cash entry requires a transfer direction.")
        if self.kind == "AMC Transfer" and (not self.transferOf or self.mode != "Non-cash reclassification" or self.status != "Posted"):
            raise ValueError("AMC transfers must be posted non-cash reclassifications linked to an advance.")
        if self.kind == "Advance AMC" and len(self.id) > 500:
            raise ValueError("The advance ID must leave room for its deterministic transfer ID.")
        if self.kind != "AMC Transfer" and self.transferOf:
            raise ValueError("Only an AMC transfer may reference an advance transfer.")
        return self


AccountType = Literal["Asset", "Liability", "Equity", "Income", "Expense"]
JournalStatus = Literal["Draft", "Posted"]
PeriodStatus = Literal["Open", "Closed"]
Paise = Annotated[int, Field(strict=True, ge=0, le=MAX_MINOR_UNITS)]


class AccountCreate(PortalModel):
    id: StableId | None = None
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    name: RequiredText
    accountType: AccountType
    parentId: StableId | None = None
    active: bool = True


class AccountRecord(AccountCreate):
    id: StableId
    createdAt: str
    updatedAt: str
    _created = field_validator("createdAt", "updatedAt")(timestamp)


class AccountingPeriodCreate(PortalModel):
    id: StableId | None = None
    financialYear: str
    startDate: str
    endDate: str
    _fy = field_validator("financialYear")(financial_year)
    _dates = field_validator("startDate", "endDate")(iso_date)

    @model_validator(mode="after")
    def dates_match_year(self) -> "AccountingPeriodCreate":
        expected_start, expected_end = financial_year_bounds(self.financialYear)
        if date.fromisoformat(self.startDate) != expected_start or date.fromisoformat(self.endDate) != expected_end:
            raise ValueError("Accounting periods must cover April 1 through March 31 of their financial year.")
        return self


class AccountingPeriodRecord(AccountingPeriodCreate):
    id: StableId
    status: PeriodStatus
    closedAt: str | None = None
    closedBy: StableId | None = None
    closeReason: ShortText | None = None
    closeAuthorization: ShortText | None = None
    reopenedAt: str | None = None
    reopenedBy: StableId | None = None
    reopenReason: ShortText | None = None
    reopenAuthorization: ShortText | None = None
    createdAt: str
    _timestamps = field_validator("closedAt", "reopenedAt", "createdAt")(timestamp)


class JournalLineInput(PortalModel):
    accountId: StableId
    debitPaise: Paise = Field(validation_alias=AliasChoices("debitPaise", "debitMinorUnits"))
    creditPaise: Paise = Field(validation_alias=AliasChoices("creditPaise", "creditMinorUnits"))
    description: ShortText | None = None

    @model_validator(mode="after")
    def one_side_only(self) -> "JournalLineInput":
        if (self.debitPaise > 0) == (self.creditPaise > 0):
            raise ValueError("Each journal line must contain either a positive debit or a positive credit, not both.")
        return self


class JournalEntryCreate(PortalModel):
    id: StableId | None = None
    date: str = Field(validation_alias=AliasChoices("date", "entryDate"))
    financialYear: str
    periodId: StableId | None = None
    description: DetailsText
    lines: Annotated[list[JournalLineInput], Field(min_length=2, max_length=200)]
    status: Literal["Draft"] = "Draft"
    sourceType: ShortText | None = None
    sourceId: StableId | None = None
    reversalOfEntryId: StableId | None = None
    correctionOfEntryId: StableId | None = None
    _date = field_validator("date")(iso_date)
    _fy = field_validator("financialYear")(financial_year)

    @model_validator(mode="after")
    def balanced_and_consistent(self) -> "JournalEntryCreate":
        parsed = date.fromisoformat(self.date)
        if financial_year_for_date(parsed) != self.financialYear:
            raise ValueError("The journal date must belong to its financial year.")
        debit = sum(line.debitPaise for line in self.lines)
        credit = sum(line.creditPaise for line in self.lines)
        if debit != credit:
            raise ValueError("Journal debits and credits must balance in paise.")
        if debit > MAX_MINOR_UNITS:
            raise ValueError("The journal total exceeds the supported paise limit.")
        if self.reversalOfEntryId and self.correctionOfEntryId:
            raise ValueError("A journal entry cannot be both a reversal and a correction.")
        return self


class JournalLineRecord(JournalLineInput):
    id: StableId
    lineNo: int = Field(strict=True, ge=1, le=200)
    accountCode: str | None = None
    accountName: str | None = None


class JournalEntryRecord(JournalEntryCreate):
    id: StableId
    status: JournalStatus
    createdBy: StableId
    createdAt: str
    postedBy: StableId | None = None
    postedAt: str | None = None
    lines: Annotated[list[JournalLineRecord], Field(min_length=2, max_length=200)]
    _timestamps = field_validator("createdAt", "postedAt")(timestamp)


class JournalPostRequest(PortalModel):
    reason: ShortText | None = None


class PeriodActionRequest(PortalModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    authorization: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]


class JournalReversalRequest(PeriodActionRequest):
    date: str | None = Field(default=None, validation_alias=AliasChoices("date", "entryDate"))
    periodId: StableId | None = None
    description: ShortText | None = None
    _date = field_validator("date")(lambda value: iso_date(value) if value is not None else None)


class JournalCorrectionRequest(PeriodActionRequest):
    date: str | None = Field(default=None, validation_alias=AliasChoices("date", "entryDate"))
    financialYear: str | None = None
    periodId: StableId | None = None
    description: DetailsText | None = None
    lines: Annotated[list[JournalLineInput], Field(min_length=2, max_length=200)]
    _date = field_validator("date")(lambda value: iso_date(value) if value is not None else None)
    _fy = field_validator("financialYear")(lambda value: financial_year(value) if value is not None else None)

    @model_validator(mode="after")
    def balanced(self) -> "JournalCorrectionRequest":
        if self.date is not None and self.financialYear is not None:
            if financial_year_for_date(date.fromisoformat(self.date)) != self.financialYear:
                raise ValueError("The journal date must belong to its financial year.")
        if sum(line.debitPaise for line in self.lines) != sum(line.creditPaise for line in self.lines):
            raise ValueError("Journal debits and credits must balance in paise.")
        return self


class AuditEventRecord(PortalModel):
    id: StableId
    occurredAt: str
    actorUserId: StableId
    actorUsername: RequiredText
    action: RequiredText
    entityType: RequiredText
    entityId: StableId
    financialYear: str | None = None
    periodId: StableId | None = None
    reason: ShortText | None = None
    authorization: ShortText | None = None
    details: dict[str, Any] = {}
    _occurred = field_validator("occurredAt")(timestamp)
    _fy = field_validator("financialYear")(lambda value: financial_year(value) if value is not None else None)


Account = AccountRecord
ChartOfAccount = AccountRecord
AccountingPeriod = AccountingPeriodRecord
FinancialPeriod = AccountingPeriodRecord
JournalLine = JournalLineRecord
JournalEntryLine = JournalLineRecord
JournalEntry = JournalEntryRecord
AuditEvent = AuditEventRecord


class PaymentRecord(PortalModel):
    id: StableId
    residentId: StableId | None = None
    resident: ShortText = ""
    mobile: ShortText = ""
    house: ShortText = ""
    type: Literal["Membership", "Maintenance", "Contribution", "Donation"]
    amount: Annotated[str, StringConstraints(max_length=120)] = ""
    numericAmount: PositiveMoney
    date: ShortText = ""
    transactionDate: str
    createdAt: str | None = None
    status: Literal["Pending verification", "Approved", "Rejected"] = "Pending verification"
    financialYear: str
    amcForFinancialYear: str | None = None
    amcBucket: Literal["Advance AMC", "AMC"] | None = None
    mode: PaymentMode
    details: DetailsText
    donorName: ShortText | None = None
    donationType: ShortText | None = None
    reviewedAt: str | None = None
    reviewedBy: ShortText | None = None
    ledgerId: StableId | None = None

    _date = field_validator("transactionDate")(iso_date)
    _fy = field_validator("financialYear")(financial_year)
    _target_fy = field_validator("amcForFinancialYear")(lambda value: financial_year(value) if value is not None else None)
    _created = field_validator("createdAt", "reviewedAt")(timestamp)

    @field_validator("id")
    @classmethod
    def receipt_id_room(cls, value: str) -> str:
        if len(value) > 500:
            raise ValueError("The claim ID must leave room for its deterministic receipt ID.")
        return value


class AMCRate(PortalModel):
    financialYear: str
    owner: NonnegativeMoney
    tenant: NonnegativeMoney
    _fy = field_validator("financialYear")(financial_year)


class OpeningBalances(PortalModel):
    bank: NonnegativeMoney
    cash: NonnegativeMoney
    financialYear: str
    date: str
    _date = field_validator("date")(iso_date)
    _fy = field_validator("financialYear")(financial_year)


class FixedDeposit(PortalModel):
    id: StableId
    startDate: str
    maturityDate: str
    amount: PositiveMoney
    maturityAmount: NonnegativeMoney
    mode: PaymentMode
    reference: DetailsText
    createdAt: str = ""
    status: Literal["Active", "Matured", "Closed"] = "Active"
    _dates = field_validator("startDate", "maturityDate")(iso_date)
    _created = field_validator("createdAt")(timestamp)

    @model_validator(mode="after")
    def dates(self) -> "FixedDeposit":
        if self.maturityDate <= self.startDate:
            raise ValueError("The maturity date must be after the deposit start date.")
        return self


class EventItem(PortalModel):
    id: StableId
    tag: ShortText = "EVENTS"
    title: RequiredText
    text: DetailsText
    date: ShortText = ""
    location: ShortText = "APC Layout"
    image: str | None = None
    link: Annotated[str | None, Field(max_length=2048)] = None
    residentsOnly: bool = False
    createdAt: str | None = None
    _image = field_validator("image")(safe_image)
    _created = field_validator("createdAt")(timestamp)

    @field_validator("link")
    @classmethod
    def link_url(cls, value: str | None) -> str | None:
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Event links must be HTTP(S) URLs.")
        return value


class OfficeBearer(PortalModel):
    id: StableId | None = None
    name: RequiredText
    display: RequiredText
    role: RequiredText
    phone: ShortText = ""
    image: str | None = None
    _image = field_validator("image")(safe_image)


class BookReconciliation(PortalModel):
    opening: Money
    receipts: Money
    payments: Money
    closing: Money
    calculatedClosing: Money | None = None
    summaryReceipts: Money | None = None
    summaryPayments: Money | None = None
    summaryClosing: Money | None = None


class PriorBalanceSheet(PortalModel):
    asOf: str
    bank: Money
    cash: Money
    _date = field_validator("asOf")(iso_date)


class OpeningBalanceComparison(PortalModel):
    bankDifference: Money
    cashDifference: Money
    priorBalanceSheet: PriorBalanceSheet


class ReconciliationCheck(PortalModel):
    name: RequiredText
    status: RequiredText
    difference: Money = 0
    bookAmount: Money | None = None
    supportAmount: Money | None = None
    supportKnownAmount: Money | None = None
    supportClosingBalance: Money | None = None


class TallyReconciliation(PortalModel):
    financialYear: str
    sourcePeriodThrough: str | None = None
    bank: BookReconciliation
    cash: BookReconciliation
    combined: BookReconciliation | None = None
    openingBalanceComparison: OpeningBalanceComparison | None = None
    checks: Annotated[list[ReconciliationCheck], Field(max_length=200)] = []
    importId: StableId | None = None
    sourceFiles: Annotated[list[RequiredText], Field(max_length=200)] = []
    transactionCount: Annotated[int | None, Field(ge=0, le=MAX_COLLECTION_ROWS)] = None
    importedAt: str | None = None
    _fy = field_validator("financialYear")(financial_year)
    _date = field_validator("sourcePeriodThrough")(lambda value: iso_date(value) if value is not None else None)
    _created = field_validator("importedAt")(timestamp)

    @model_validator(mode="after")
    def book_rolls_forward(self) -> "TallyReconciliation":
        if self.bank.calculatedClosing is None or self.cash.calculatedClosing is None:
            raise ValueError("Bank and cash reconciliation require calculated closing balances.")
        return self


class CollectionWrite(PortalModel):
    revision: Revision
    value: Any


class MigrationPreview(PortalModel):
    collections: dict[str, Any]


class MigrationImport(MigrationPreview):
    revision: Revision


class RevisionRequest(PortalModel):
    revision: Revision


class PaymentReview(RevisionRequest):
    status: Literal["Approved", "Rejected"]


class ResidentPayment(PortalModel):
    type: Literal["Membership", "Maintenance", "Contribution", "Donation"]
    numericAmount: PositiveMoney
    mode: PaymentMode
    details: DetailsText
    idempotencyKey: Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class TallyImport(PortalModel):
    importId: StableId
    financialYear: str
    sourceFiles: Annotated[list[RequiredText], Field(max_length=200)] = []
    openingBalances: OpeningBalances | None = None
    reconciliation: TallyReconciliation
    transactions: Annotated[list[LedgerEntry], Field(max_length=MAX_COLLECTION_ROWS)]
    _fy = field_validator("financialYear")(financial_year)

    @model_validator(mode="after")
    def matching_controls(self) -> "TallyImport":
        if self.reconciliation.financialYear != self.financialYear:
            raise ValueError("Tally reconciliation must match the snapshot financial year.")
        if self.openingBalances is not None and self.openingBalances.financialYear != self.financialYear:
            raise ValueError("Tally opening balances must match the snapshot financial year.")
        return self


class TallyImportApply(PortalModel):
    """A bounded JSON upload containing a Tally snapshot and portal revision."""

    revision: Revision
    snapshot: TallyImport


ROW_MODELS: dict[str, type[PortalModel]] = {
    "residents": ResidentRecord,
    "ledger": LedgerEntry,
    "payments": PaymentRecord,
    "amcRates": AMCRate,
    "fixedDeposits": FixedDeposit,
    "events": EventItem,
    "officeBearers": OfficeBearer,
}


def json_record(model: PortalModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)
