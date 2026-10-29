from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    DeliveryStatus,
    DuplicateReviewStatus,
    MoneyDirection,
    MovementType,
    PaymentDirection,
    PaymentKind,
    PaymentStatus,
    ReconciliationStatus,
    SaleSource,
    SaleStatus,
    SyncStatus,
)
from app.utils import ensure_utc

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class AuthUserOut(BaseModel):
    id: str
    email: str
    is_owner: bool
    created_at: datetime


class AuthStatusOut(BaseModel):
    has_accounts: bool
    allow_signup: bool
    authenticated: bool


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Uncategorized", max_length=80)
    sku: str | None = Field(default=None, max_length=64)
    purchase_cost: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    selling_price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    low_stock_threshold: int = Field(default=5, ge=0, le=1000000)
    expiry_date: date | None = None
    batch_note: str | None = Field(default=None, max_length=200)
    is_active: bool = True

    @field_validator("name", "category", "sku", "batch_note")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @model_validator(mode="after")
    def non_empty(self):
        if not self.name:
            raise ValueError("Product name is required")
        if not self.category:
            self.category = "Uncategorized"
        return self


class ProductCreate(ProductBase):
    opening_stock: int = Field(default=0, ge=0, le=1000000)


class ProductUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    sku: str | None = Field(default=None, max_length=64)
    purchase_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    selling_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=1000000)
    expiry_date: date | None = None
    batch_note: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None

    @field_validator("name", "category", "sku", "batch_note")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)


class ProductOut(ORMModel):
    id: int
    name: str
    category: str
    sku: str | None
    purchase_cost: Decimal
    selling_price: Decimal
    stock_quantity: int
    low_stock_threshold: int
    expiry_date: date | None
    batch_note: str | None
    is_active: bool
    version: int
    is_low_stock: bool
    stock_value: Decimal
    retail_value: Decimal
    created_at: datetime
    updated_at: datetime


class ProductListOut(BaseModel):
    items: list[ProductOut]
    total: int
    limit: int
    offset: int
    categories: list[str]


class SaleItemIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    line_discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)


class InitialPaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: str = Field(min_length=1, max_length=40)
    paid_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None

    @field_validator("method")
    @classmethod
    def clean_method(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("paid_at")
    @classmethod
    def normalize_paid_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None


class SaleCreate(BaseModel):
    occurred_at: datetime | None = None
    source: SaleSource = SaleSource.manual
    external_order_id: str | None = Field(default=None, max_length=120)
    items: list[SaleItemIn] = Field(min_length=1, max_length=100)
    discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    initial_payment: InitialPaymentIn | None = None
    initial_payments: list[InitialPaymentIn] | None = Field(default=None, max_length=5)
    customer_id: int | None = Field(default=None, gt=0)
    customer_name: str | None = Field(default=None, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=30)
    customer_room_ref: str | None = Field(default=None, max_length=120)
    customer_ref: str | None = Field(default=None, max_length=120)
    delivery_status: DeliveryStatus | None = None
    delivery_person: str | None = Field(default=None, max_length=120)
    delivery_notes: str | None = None
    notes: str | None = None
    allow_negative_stock: bool = False
    negative_stock_reason: str | None = Field(default=None, max_length=300)
    client_uuid: str | None = Field(default=None, max_length=36)
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("external_order_id", "customer_name", "customer_phone", "customer_room_ref", "customer_ref", "negative_stock_reason")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None

    @model_validator(mode="after")
    def no_duplicate_products(self):
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each product may appear only once. Increase its quantity instead.")
        if self.delivery_person is not None:
            self.delivery_person = _clean(self.delivery_person)
        return self


class CustomerOut(ORMModel):
    id: int
    name: str
    phone: str | None
    room_ref: str | None
    notes: str | None


class SaleItemOut(ORMModel):
    id: int
    product_id: int
    product_name: str
    sku: str | None
    quantity: int
    unit_price: Decimal
    unit_cost: Decimal
    line_discount: Decimal
    line_total: Decimal
    cost_total: Decimal
    returned_quantity: int
    remaining_quantity: int


class PaymentOut(ORMModel):
    id: int
    uuid: str
    sale_id: int | None
    amount: Decimal
    direction: PaymentDirection
    kind: PaymentKind
    method: str
    paid_at: datetime
    reference: str | None
    notes: str | None
    created_at: datetime


class SaleReturnItemOut(ORMModel):
    id: int
    sale_item_id: int
    quantity: int
    unit_price: Decimal
    line_value: Decimal
    cost_total: Decimal
    product_name: str | None = None


class SaleReturnOut(ORMModel):
    id: int
    uuid: str
    sale_id: int
    returned_at: datetime
    reason: str
    restock: bool
    refund_amount: Decimal
    refund_method: str | None
    notes: str | None
    returned_value: Decimal
    cost_value: Decimal
    items: list[SaleReturnItemOut]


class DeliveryOut(ORMModel):
    id: int
    sale_id: int
    status: DeliveryStatus
    delivery_person: str | None
    notes: str | None
    dispatched_at: datetime | None
    delivered_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class DeliveryRowOut(DeliveryOut):
    sale_uuid: str
    occurred_at: datetime
    customer_name: str | None
    total: Decimal
    outstanding: Decimal
    payment_status: PaymentStatus
    item_count: int


class SaleOut(BaseModel):
    id: int
    uuid: str
    occurred_at: datetime
    source: SaleSource
    external_order_id: str | None
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    returned_value: Decimal
    amount_paid: Decimal
    refunded_amount: Decimal
    net_paid: Decimal
    outstanding: Decimal
    payment_status: PaymentStatus
    status: SaleStatus
    customer_id: int | None
    customer_name: str | None
    customer_ref: str | None
    notes: str | None
    delivery_status: str
    delivery_person: str | None
    reconciliation_status: ReconciliationStatus
    item_count: int
    items_summary: str | None = None
    payment_methods_summary: str | None = None
    version: int
    is_pending_sync: bool = False
    created_at: datetime
    updated_at: datetime


class SaleDetailOut(SaleOut):
    items: list[SaleItemOut]
    payments: list[PaymentOut]
    returns: list[SaleReturnOut]
    delivery: DeliveryOut | None
    customer: CustomerOut | None
    void_reason: str | None
    voided_at: datetime | None


class SalePage(BaseModel):
    items: list[SaleOut]
    total: int
    limit: int
    offset: int
    aggregates: dict[str, Decimal | int]


class PaymentWithSaleOut(BaseModel):
    payment: PaymentOut
    sale: SaleDetailOut


class ReturnWithSaleOut(BaseModel):
    return_: SaleReturnOut = Field(alias="return")
    sale: SaleDetailOut

    model_config = ConfigDict(populate_by_name=True)


class SaleUpdate(BaseModel):
    version: int = Field(ge=1)
    notes: str | None = None
    customer_ref: str | None = Field(default=None, max_length=120)
    external_order_id: str | None = Field(default=None, max_length=120)
    reconciliation_status: ReconciliationStatus | None = None

    @field_validator("customer_ref", "external_order_id")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)


class SaleVoidIn(BaseModel):
    version: int | None = None
    reason: str = Field(min_length=2, max_length=300)
    restock: bool = True
    refund_paid: bool = True
    refund_method: str | None = Field(default=None, max_length=40)


class ReturnItemIn(BaseModel):
    sale_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)


class SaleReturnCreate(BaseModel):
    returned_at: datetime | None = None
    items: list[ReturnItemIn] = Field(min_length=1, max_length=100)
    restock: bool = False
    refund_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    refund_method: str | None = Field(default=None, max_length=40)
    reason: str = Field(min_length=2, max_length=300)
    notes: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("returned_at")
    @classmethod
    def normalize_returned_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None

    @field_validator("refund_method")
    @classmethod
    def clean_method(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return value.strip()


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: str = Field(min_length=1, max_length=40)
    paid_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("method")
    @classmethod
    def clean_method(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("paid_at")
    @classmethod
    def normalize_paid_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None


class AdjustmentCreate(PaymentCreate):
    direction: Literal["in", "out"] = "in"
    occurred_at: datetime | None = None


class ExpenseCreate(BaseModel):
    occurred_at: datetime | None = None
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: str = Field(min_length=1, max_length=40)
    paid_to: str | None = Field(default=None, max_length=120)
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("category", "method")
    @classmethod
    def clean_lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("paid_to", "reference")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None


class ExpenseUpdate(BaseModel):
    version: int = Field(ge=1)
    occurred_at: datetime | None = None
    category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    method: str | None = Field(default=None, max_length=40)
    paid_to: str | None = Field(default=None, max_length=120)
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None

    @field_validator("category", "method")
    @classmethod
    def clean_lower(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None

    @field_validator("paid_to", "reference")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None


class ExpenseVoid(BaseModel):
    version: int | None = None
    reason: str = Field(min_length=2, max_length=300)


class ExpenseOut(ORMModel):
    id: int
    uuid: str
    occurred_at: datetime
    category: str
    description: str
    amount: Decimal
    method: str
    paid_to: str | None = None
    kind: str = "ordinary"
    linked_receipt_id: int | None = None
    reference: str | None
    notes: str | None
    is_void: bool
    void_reason: str | None
    voided_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class ExpensePage(BaseModel):
    items: list[ExpenseOut]
    total: int
    limit: int
    offset: int
    totals: dict[str, Decimal | int]


class StockReceiptItemIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)
    unit_cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class StockReceiptCreate(BaseModel):
    received_at: datetime | None = None
    supplier_ref: str | None = Field(default=None, max_length=150)
    payment_method: str = Field(default="cash", max_length=40)
    notes: str | None = None
    items: list[StockReceiptItemIn] = Field(min_length=1, max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("payment_method")
    @classmethod
    def clean_method(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None

    @model_validator(mode="after")
    def no_duplicate_products(self):
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each product may appear only once per receipt.")
        return self


class StockReceiptItemOut(ORMModel):
    id: int
    product_id: int
    product_name: str | None = None
    quantity: int
    unit_cost: Decimal
    line_total: Decimal


class StockReceiptOut(BaseModel):
    id: int
    uuid: str
    received_at: datetime
    supplier_ref: str | None
    total_cost: Decimal
    payment_method: str
    notes: str | None
    expense_id: int | None
    items: list[StockReceiptItemOut]


class MovementCreate(BaseModel):
    product_id: int = Field(gt=0)
    movement_type: Literal["opening", "damage", "correction"]
    quantity_change: int = Field(le=1000000)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    occurred_at: datetime | None = None
    reason: str = Field(min_length=2, max_length=300)
    notes: str | None = None
    allow_negative_stock: bool = False
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("occurred_at")
    @classmethod
    def normalize(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None

    @model_validator(mode="after")
    def nonzero(self):
        if self.quantity_change == 0:
            raise ValueError("quantity_change must not be zero")
        if self.movement_type == "damage" and self.quantity_change > 0:
            raise ValueError("Damage movements must be negative")
        if self.movement_type == "opening" and self.quantity_change <= 0:
            raise ValueError("Opening stock must be positive")
        return self


class MovementOut(ORMModel):
    id: int
    uuid: str
    product_id: int
    product_name: str | None = None
    movement_type: MovementType
    quantity_change: int
    unit_cost: Decimal | None
    occurred_at: datetime
    reason: str
    sale_id: int | None
    sale_return_id: int | None
    stock_receipt_id: int | None
    notes: str | None
    created_at: datetime


class MovementPage(BaseModel):
    items: list[MovementOut]
    total: int
    limit: int
    offset: int


class InventorySummary(BaseModel):
    product_count: int
    active_product_count: int
    low_stock_count: int
    out_of_stock_count: int
    total_units: int
    stock_value: Decimal
    retail_value: Decimal
    low_stock_products: list[ProductOut]


class CashHandoverCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: str = Field(default="cash", max_length=40)
    recipient: str | None = Field(default=None, max_length=120)
    handed_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("method")
    @classmethod
    def clean_method(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("handed_at")
    @classmethod
    def normalize(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None


class CashHandoverOut(ORMModel):
    id: int
    uuid: str
    amount: Decimal
    method: str
    recipient: str | None
    handed_at: datetime
    reference: str | None
    notes: str | None
    created_at: datetime


class MoneyTransactionCreate(BaseModel):
    direction: MoneyDirection
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    person: str | None = Field(default=None, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    method: str = Field(min_length=1, max_length=40)
    occurred_at: datetime | None = None
    description: str = Field(min_length=2, max_length=200)
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("category", "method")
    @classmethod
    def clean_lower(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "_")

    @field_validator("person", "reference")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Description must be at least 2 characters")
        return value

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None


class MoneyTransactionUpdate(BaseModel):
    version: int = Field(ge=1)
    direction: MoneyDirection | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    person: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    method: str | None = Field(default=None, max_length=40)
    occurred_at: datetime | None = None
    description: str | None = Field(default=None, min_length=2, max_length=200)
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None

    @field_validator("category", "method")
    @classmethod
    def clean_lower(cls, value: str | None) -> str | None:
        return value.strip().lower().replace(" ", "_") if value else None

    @field_validator("person", "reference", "description")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value else None


class MoneyTransactionVoid(BaseModel):
    version: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=2, max_length=300)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return value.strip()


class MoneyTransactionOut(ORMModel):
    id: int
    uuid: str
    direction: MoneyDirection
    amount: Decimal
    person: str | None
    category: str
    method: str
    occurred_at: datetime
    description: str
    reference: str | None
    notes: str | None
    is_void: bool
    void_reason: str | None
    voided_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class LedgerRow(BaseModel):
    key: str
    source: str
    record_id: int
    occurred_at: datetime
    direction: Literal["in", "out"]
    amount: Decimal
    method: str
    person: str | None = None
    category: str
    category_label: str
    description: str
    reference: str | None = None
    notes: str | None = None
    sale_id: int | None = None
    sale_external_order_id: str | None = None
    expense_id: int | None = None
    receipt_id: int | None = None
    handover_id: int | None = None
    money_id: int | None = None
    is_void: bool = False
    editable: bool = False
    voidable: bool = False
    version: int | None = None
    link: str | None = None
    created_at: datetime | None = None
    cash_balance_after: Decimal | None = None
    upi_balance_after: Decimal | None = None
    other_balance_after: Decimal | None = None


class MoneySummaryOut(BaseModel):
    label: str
    date_from: date | None
    date_to: date | None
    money_in: Decimal
    money_out: Decimal
    cash_in: Decimal
    cash_out: Decimal
    upi_in: Decimal
    upi_out: Decimal
    other_in: Decimal
    other_out: Decimal
    count: int
    sale_payments_in: Decimal
    other_money_in: Decimal
    ordinary_expenses: Decimal
    stock_purchases: Decimal
    opening_cash: Decimal
    opening_upi: Decimal
    closing_cash: Decimal
    closing_upi: Decimal
    current_cash: Decimal
    current_upi: Decimal
    balance_complete: bool
    opening_effective_date: date | None


class MoneyDailyRow(BaseModel):
    date: date
    money_in: Decimal
    money_out: Decimal
    cash_in: Decimal
    cash_out: Decimal
    upi_in: Decimal
    upi_out: Decimal
    count: int


class LedgerPage(BaseModel):
    items: list[LedgerRow]
    total: int
    limit: int
    offset: int
    summary: MoneySummaryOut
    daily: list[MoneyDailyRow]


class MoneyMonthlyRow(BaseModel):
    month: int
    label: str
    money_in: Decimal
    money_out: Decimal
    cash_in: Decimal
    cash_out: Decimal
    upi_in: Decimal
    upi_out: Decimal
    count: int


class MoneyMonthlyOut(BaseModel):
    year: int
    months: list[MoneyMonthlyRow]


class CashSessionUpsert(BaseModel):
    opening_cash: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    counted_cash: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    notes: str | None = None
    version: int | None = Field(default=None, ge=1)


class CashSessionOut(ORMModel):
    id: int
    session_date: date
    opening_cash: Decimal
    counted_cash: Decimal | None
    notes: str | None
    version: int
    updated_at: datetime


class PaymentMethodBucket(BaseModel):
    method: str
    inflow: Decimal
    outflow: Decimal
    net: Decimal


class CashOverview(BaseModel):
    session_date: date
    opening_cash: Decimal
    cash_in: Decimal
    upi_in: Decimal
    other_in: Decimal
    cash_refunds: Decimal
    cash_expenses: Decimal
    cash_handovers: Decimal
    expected_closing_cash: Decimal
    counted_cash: Decimal | None
    difference: Decimal | None
    total_collected: Decimal
    total_refunds: Decimal
    net_collected: Decimal
    pending_balances: Decimal
    methods: list[PaymentMethodBucket]
    handovers: list[CashHandoverOut]
    session: CashSessionOut | None
    payment_count: int


class DeliveryUpdate(BaseModel):
    status: DeliveryStatus
    delivery_person: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    version: int | None = Field(default=None, ge=1)


class DeliveryCreate(BaseModel):
    sale_id: int = Field(gt=0)
    status: DeliveryStatus = DeliveryStatus.pending
    delivery_person: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class DeliveryPage(BaseModel):
    items: list[DeliveryRowOut]
    total: int
    limit: int
    offset: int
    counts: dict[str, int]


class ReconciliationUpdate(BaseModel):
    status: ReconciliationStatus
    notes: str | None = None
    website_total: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    version: int | None = Field(default=None, ge=1)


class ReconciliationLink(BaseModel):
    sale_id: int = Field(gt=0)
    external_order_id: str = Field(min_length=1, max_length=120)
    notes: str | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("external_order_id")
    @classmethod
    def clean(cls, value: str) -> str:
        return value.strip()


class DuplicateReviewIn(BaseModel):
    sale_a_id: int = Field(gt=0)
    sale_b_id: int = Field(gt=0)
    status: DuplicateReviewStatus
    notes: str | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.sale_a_id == self.sale_b_id:
            raise ValueError("A sale cannot be paired with itself")
        if self.sale_a_id > self.sale_b_id:
            self.sale_a_id, self.sale_b_id = self.sale_b_id, self.sale_a_id
        return self


class ReconciliationRecordOut(ORMModel):
    id: int
    sale_id: int
    external_order_id: str | None
    status: ReconciliationStatus
    notes: str | None
    website_total: Decimal | None
    reviewed_at: datetime | None
    created_at: datetime


class DuplicateCandidate(BaseModel):
    sale_a: SaleOut
    sale_b: SaleOut
    score: int
    reasons: list[str]
    review_status: DuplicateReviewStatus | None = None


class ReconciliationQueue(BaseModel):
    items: list[SaleOut]
    total: int
    counts: dict[str, int]
    candidates: list[DuplicateCandidate]
    reviewed_pairs: list[dict[str, Any]]


class SettingsOut(BaseModel):
    business_name: str
    payment_methods: list[str]
    expense_categories: list[str]
    money_in_categories: list[str] = []
    money_out_categories: list[str] = []
    default_low_stock_threshold: int = 5
    opening_cash_balance: Decimal | None = None
    opening_upi_balance: Decimal | None = None
    opening_balance_date: date | None = None
    currency: str = "INR"
    business_timezone: str
    inventory_category: str = "inventory_purchase"


class SettingsUpdate(BaseModel):
    business_name: str = Field(min_length=1, max_length=120)
    payment_methods: list[str] = Field(min_length=1)
    expense_categories: list[str] = Field(min_length=1)
    money_in_categories: list[str] | None = None
    money_out_categories: list[str] | None = None
    default_low_stock_threshold: int | None = Field(default=None, ge=0, le=1000000)
    opening_cash_balance: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    opening_upi_balance: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    opening_balance_date: date | None = None
    clear_opening_balances: bool = False

    @field_validator("payment_methods", "expense_categories", "money_in_categories", "money_out_categories")
    @classmethod
    def clean_list(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned: list[str] = []
        for value in values:
            item = value.strip().lower().replace(" ", "_").replace("-", "_")
            if item and item not in cleaned:
                cleaned.append(item)
        if not cleaned:
            raise ValueError("At least one value is required")
        return cleaned


class AuditOut(ORMModel):
    id: int
    entity_type: str
    entity_id: str
    action: str
    changed_at: datetime
    before_json: str | None
    after_json: str | None
    note: str | None


class SyncOperationOut(ORMModel):
    id: int
    operation_id: str
    entity_type: str
    entity_id: str | None
    operation_type: str
    local_created_at: datetime | None
    synced_at: datetime | None
    status: SyncStatus
    attempts: int
    error: str | None
    created_at: datetime


class BackupInfo(BaseModel):
    database_path: str
    size_bytes: int
    last_modified: datetime | None
    table_counts: dict[str, int]


class ReportSummaryOut(BaseModel):
    date_from: date
    date_to: date
    sales_count: int
    gross_sales: Decimal
    returns_value: Decimal
    net_sales: Decimal
    collected: Decimal
    refunds: Decimal
    ordinary_expenses: Decimal
    stock_purchases: Decimal
    total_expenses: Decimal
    money_in: Decimal
    money_out: Decimal
    outstanding: Decimal
    average_sale: Decimal
    cash_in: Decimal
    cash_out: Decimal
    upi_in: Decimal
    upi_out: Decimal
    cash_balance: Decimal
    upi_balance: Decimal
    balance_complete: bool
    daily: list[dict[str, Any]]
    top_products: list[dict[str, Any]]
    payment_methods: list[dict[str, Any]]
    expense_categories: list[dict[str, Any]]


class MonthlyReportRow(BaseModel):
    month: int
    label: str
    sales_count: int
    net_sales: Decimal
    collected: Decimal
    refunds: Decimal
    ordinary_expenses: Decimal
    stock_purchases: Decimal
    money_in: Decimal
    money_out: Decimal
    outstanding: Decimal


class MonthlyReportOut(BaseModel):
    year: int
    months: list[MonthlyReportRow]


class DashboardOut(BaseModel):
    range: str
    date_from: date
    date_to: date
    summary: ReportSummaryOut
    money_received: Decimal
    sale_payments_received: Decimal
    other_money_received: Decimal
    ordinary_expenses: Decimal
    total_money_in: Decimal
    total_money_out: Decimal
    cash_available: Decimal
    upi_available: Decimal
    balance_complete: bool
    opening_cash: Decimal
    opening_upi: Decimal
    opening_effective_date: date | None
    outstanding_total: Decimal
    low_stock_count: int
    out_of_stock_count: int
    unverified_website_orders: int
    potential_duplicates: int
    recent_activity: list[dict[str, Any]]
    recent_money: list[LedgerRow]
    pending_payments: list[SaleOut]
    low_stock_products: list[ProductOut]
