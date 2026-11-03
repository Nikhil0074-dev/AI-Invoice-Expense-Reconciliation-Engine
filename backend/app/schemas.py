from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, field_validator

from app.processors.normalize import ISO_CURRENCIES, currency_decimals

Money = Annotated[Decimal, PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json")]
MAX_AMOUNT = Decimal("999999999999")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth / orgs
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    organization_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: str
    email: str
    display_name: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class OrgOut(ORM):
    id: str
    name: str
    default_currency: str
    locale: str
    date_format: str
    max_upload_mb: int
    match_high_threshold: float
    match_review_threshold: float
    amount_tolerance_pct: float
    date_window_days: int
    retention_days: int | None
    role: str | None = None


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    default_currency: str = "INR"


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    default_currency: str | None = None
    locale: str | None = Field(default=None, max_length=20)
    date_format: Literal["DMY", "MDY", "ISO"] | None = None
    max_upload_mb: int | None = Field(default=None, ge=1, le=50)
    match_high_threshold: float | None = Field(default=None, ge=0.5, le=1)
    match_review_threshold: float | None = Field(default=None, ge=0.1, le=1)
    amount_tolerance_pct: float | None = Field(default=None, ge=0, le=0.2)
    date_window_days: int | None = Field(default=None, ge=1, le=365)
    retention_days: int | None = Field(default=None, ge=30, le=3650)

    @field_validator("default_currency")
    @classmethod
    def _cur(cls, v):
        if v is not None and v.upper() not in ISO_CURRENCIES:
            raise ValueError("unsupported currency code")
        return v.upper() if v else v


class MemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    display_name: str
    role: str


class MemberAdd(BaseModel):
    email: EmailStr
    role: Literal["ADMIN", "ACCOUNTANT", "CONTRIBUTOR", "VIEWER"]


class MemberUpdate(BaseModel):
    role: Literal["ADMIN", "ACCOUNTANT", "CONTRIBUTOR", "VIEWER"]


# ---- documents / invoices
class DocumentOut(ORM):
    id: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    content_sha256: str
    processing_status: str
    language: str | None
    page_count: int | None
    extraction_method: str | None
    ocr_confidence: float | None
    created_at: datetime
    invoice_id: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    currency: str | None = None
    total_amount: Money | None = None
    invoice_date: date | None = None
    open_duplicate_flags: int = 0


class JobOut(ORM):
    id: str
    document_id: str
    status: str
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


class UploadOut(BaseModel):
    document_id: str
    job_id: str
    processing_status: str
    message: str = "Document uploaded successfully."


class LineItemIn(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    quantity: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    unit_price: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    tax_amount: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    line_total: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)


class LineItemOut(ORM):
    id: str
    position: int
    description: str | None
    quantity: Money | None
    unit_price: Money | None
    tax_amount: Money | None
    line_total: Money | None


class InvoiceUpdate(BaseModel):
    vendor_name: str | None = Field(default=None, max_length=255)
    invoice_number: str | None = Field(default=None, max_length=100)
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    tax_amount: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    discount_amount: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    total_amount: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    tax_id: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=80)
    payment_status: Literal["UNKNOWN", "UNPAID", "PAID"] | None = None
    line_items: list[LineItemIn] | None = Field(default=None, max_length=200)

    @field_validator("currency")
    @classmethod
    def _cur(cls, v):
        if v is None or v == "":
            return None
        if v.upper() not in ISO_CURRENCIES:
            raise ValueError("unsupported currency code")
        return v.upper()

    @field_validator("invoice_date", "due_date")
    @classmethod
    def _date(cls, v):
        if v and not (1990 <= v.year <= 2100):
            raise ValueError("date out of range")
        return v


class InvoiceOut(ORM):
    id: str
    document_id: str
    vendor_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    due_date: date | None
    currency: str | None
    subtotal: Money | None
    tax_amount: Money | None
    discount_amount: Money | None
    total_amount: Money | None
    tax_id: str | None
    description: str | None
    category: str | None
    payment_status: str
    extraction_status: str
    review_status: str
    reconciliation_status: str
    field_confidence: dict | None
    uncertain_fields: list | None
    warnings: list | None
    extraction_original: dict | None
    line_items: list[LineItemOut] = []
    review_reasons: list[str] = []
    document_status: str | None = None
    original_filename: str | None = None
    mime_type: str | None = None
    allocated_amount: Money | None = None
    updated_at: datetime


class VerifyIn(BaseModel):
    acknowledge_warnings: bool = False


# ---- transactions / reconciliation
class TransactionOut(ORM):
    id: str
    transaction_date: date
    description: str
    amount: Money
    currency: str
    reference: str | None
    account: str | None
    allocated: Money = Decimal(0)
    remaining: Money = Decimal(0)
    status: str = "UNMATCHED"


class MatchOut(ORM):
    id: str
    invoice_id: str
    kind: str
    match_status: str
    match_score: float | None
    match_explanation: str
    signals: dict | None
    transaction_ids: list | None
    confirmed_at: datetime | None
    transactions: list[TransactionOut] = []


class AllocationIn(BaseModel):
    transaction_id: str
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT)


class MatchCreate(BaseModel):
    match_id: str | None = None
    invoice_id: str | None = None
    allocations: list[AllocationIn] | None = None


class MatchPatch(BaseModel):
    action: Literal["confirm", "unlink"]


class DuplicateOut(ORM):
    id: str
    document_id: str
    possible_duplicate_document_id: str
    detection_method: str
    category: str
    confidence_score: float
    evidence: str
    review_status: str
    review_note: str | None
    created_at: datetime
    document_filename: str | None = None
    possible_duplicate_filename: str | None = None


class DuplicateReview(BaseModel):
    decision: Literal["confirm_duplicate", "dismiss"]
    note: str | None = Field(default=None, max_length=500)


class ExportColumn(BaseModel):
    source: str
    header: str = Field(min_length=1, max_length=80)


class ExportIn(BaseModel):
    export_type: Literal["expense", "invoice_register", "bank_reconciliation", "line_items", "duplicate_review", "unmatched_transactions"]
    date_from: date | None = None
    date_to: date | None = None
    invoice_ids: list[str] | None = None
    template: Literal["generic", "simple_ledger"] = "generic"
    columns: list[ExportColumn] | None = None


class ExportOut(ORM):
    id: str
    export_type: str
    row_count: int
    content_sha256: str
    created_at: datetime
    filters: dict | None
    download_url: str | None = None


class AuditOut(ORM):
    id: str
    actor_user_id: str | None
    actor_name: str | None = None
    entity_type: str
    entity_id: str
    action: str
    before_state: dict | None
    after_state: dict | None
    created_at: datetime
