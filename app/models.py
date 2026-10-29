from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils import utcnow


class UTCDateTime(TypeDecorator):
    """Stores naive UTC in SQLite and returns timezone-aware UTC values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def enum_type(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


class SaleSource(str, enum.Enum):
    website = "website"
    manual = "manual"
    imported = "imported"


class SaleStatus(str, enum.Enum):
    completed = "completed"
    voided = "voided"


class PaymentStatus(str, enum.Enum):
    unpaid = "unpaid"
    partial = "partial"
    paid = "paid"
    voided = "voided"


class PaymentDirection(str, enum.Enum):
    inflow = "in"
    outflow = "out"


class MoneyDirection(str, enum.Enum):
    inflow = "in"
    outflow = "out"


class PaymentKind(str, enum.Enum):
    sale_payment = "sale_payment"
    refund = "refund"
    adjustment = "adjustment"


class MovementType(str, enum.Enum):
    opening = "opening"
    receipt = "receipt"
    sale = "sale"
    return_ = "return"
    damage = "damage"
    correction = "correction"


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    out_for_delivery = "out_for_delivery"
    delivered = "delivered"
    cancelled = "cancelled"


class ReconciliationStatus(str, enum.Enum):
    recorded = "recorded"
    verified = "verified"
    not_found = "not_found"
    needs_review = "needs_review"
    potential_duplicate = "potential_duplicate"


class SyncStatus(str, enum.Enum):
    synced = "synced"
    failed = "failed"
    conflict = "conflict"


class DuplicateReviewStatus(str, enum.Enum):
    dismissed = "dismissed"
    confirmed_duplicate = "confirmed_duplicate"


MONEY = Numeric(12, 2)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("purchase_cost >= 0", name="ck_products_cost_nonnegative"),
        CheckConstraint("selling_price >= 0", name="ck_products_price_nonnegative"),
        CheckConstraint("low_stock_threshold >= 0", name="ck_products_threshold_nonnegative"),
        Index("ix_products_name", "name"),
        Index("ix_products_category", "category"),
        Index("ix_products_sku", "sku", unique=True),
        Index("ix_products_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="Uncategorized")
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purchase_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    selling_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    batch_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    movements: Mapped[list[StockMovement]] = relationship(back_populates="product")

    @property
    def is_low_stock(self) -> bool:
        return self.stock_quantity <= self.low_stock_threshold

    @property
    def stock_value(self) -> Decimal:
        return (Decimal(self.stock_quantity) * self.purchase_cost).quantize(Decimal("0.01"))

    @property
    def retail_value(self) -> Decimal:
        return (Decimal(self.stock_quantity) * self.selling_price).quantize(Decimal("0.01"))


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_name", "name"),
        Index("ix_customers_phone", "phone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    room_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Sale(TimestampMixin, Base):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_sales_subtotal_nonnegative"),
        CheckConstraint("discount >= 0", name="ck_sales_discount_nonnegative"),
        CheckConstraint("total >= 0", name="ck_sales_total_nonnegative"),
        CheckConstraint("returned_value >= 0", name="ck_sales_returned_nonnegative"),
        CheckConstraint("amount_paid >= 0", name="ck_sales_paid_nonnegative"),
        CheckConstraint("refunded_amount >= 0", name="ck_sales_refunded_nonnegative"),
        Index("ix_sales_occurred_at", "occurred_at"),
        Index("ix_sales_source", "source"),
        Index("ix_sales_status", "status"),
        Index("ix_sales_payment_status", "payment_status"),
        Index("ix_sales_reconciliation_status", "reconciliation_status"),
        Index("ix_sales_external_order_id", "external_order_id", unique=True),
        Index("ix_sales_idempotency_key", "idempotency_key", unique=True),
        Index("ix_sales_uuid", "uuid", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[SaleSource] = mapped_column(enum_type(SaleSource, "sale_source"), nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    subtotal: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    discount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    returned_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    amount_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    refunded_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        enum_type(PaymentStatus, "payment_status"), nullable=False, default=PaymentStatus.unpaid
    )
    status: Mapped[SaleStatus] = mapped_column(
        enum_type(SaleStatus, "sale_status"), nullable=False, default=SaleStatus.completed
    )
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    customer_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciliation_status: Mapped[ReconciliationStatus] = mapped_column(
        enum_type(ReconciliationStatus, "reconciliation_status"),
        nullable=False,
        default=ReconciliationStatus.recorded,
    )
    void_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    items: Mapped[list[SaleItem]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", order_by="SaleItem.id"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", order_by="Payment.paid_at"
    )
    returns: Mapped[list[SaleReturn]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", order_by="SaleReturn.returned_at"
    )
    delivery: Mapped[Delivery | None] = relationship(
        back_populates="sale", uselist=False, cascade="all, delete-orphan"
    )
    customer: Mapped[Customer | None] = relationship()
    reconciliation_records: Mapped[list[ReconciliationRecord]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", order_by="ReconciliationRecord.created_at"
    )

    @property
    def outstanding(self) -> Decimal:
        if self.status == SaleStatus.voided:
            return Decimal("0.00")
        due = self.total - self.returned_value - (self.amount_paid - self.refunded_amount)
        return max(Decimal("0.00"), due.quantize(Decimal("0.01")))

    @property
    def net_paid(self) -> Decimal:
        return (self.amount_paid - self.refunded_amount).quantize(Decimal("0.01"))


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sale_items_quantity_positive"),
        CheckConstraint("returned_quantity >= 0", name="ck_sale_items_returned_nonnegative"),
        CheckConstraint("unit_price >= 0", name="ck_sale_items_price_nonnegative"),
        CheckConstraint("unit_cost >= 0", name="ck_sale_items_cost_nonnegative"),
        CheckConstraint("line_total >= 0", name="ck_sale_items_total_nonnegative"),
        UniqueConstraint("sale_id", "product_id", name="ux_sale_items_sale_product"),
        Index("ix_sale_items_sale_id", "sale_id"),
        Index("ix_sale_items_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    line_discount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    returned_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    sale: Mapped[Sale] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.returned_quantity


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        Index("ix_payments_sale_id", "sale_id"),
        Index("ix_payments_paid_at", "paid_at"),
        Index("ix_payments_method", "method"),
        Index("ix_payments_direction", "direction"),
        Index("ix_payments_idempotency_key", "idempotency_key", unique=True),
        Index("ix_payments_uuid", "uuid", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    direction: Mapped[PaymentDirection] = mapped_column(
        enum_type(PaymentDirection, "payment_direction"), nullable=False
    )
    kind: Mapped[PaymentKind] = mapped_column(enum_type(PaymentKind, "payment_kind"), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    sale: Mapped[Sale | None] = relationship(back_populates="payments")


class SaleReturn(TimestampMixin, Base):
    __tablename__ = "sale_returns"
    __table_args__ = (
        CheckConstraint("refund_amount >= 0", name="ck_sale_returns_refund_nonnegative"),
        Index("ix_sale_returns_sale_id", "sale_id"),
        Index("ix_sale_returns_returned_at", "returned_at"),
        Index("ix_sale_returns_idempotency_key", "idempotency_key", unique=True),
        Index("ix_sale_returns_uuid", "uuid", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    returned_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    restock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    refund_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    refund_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    returned_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    cost_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))

    sale: Mapped[Sale] = relationship(back_populates="returns")
    items: Mapped[list[SaleReturnItem]] = relationship(
        back_populates="return_", cascade="all, delete-orphan", order_by="SaleReturnItem.id"
    )


class SaleReturnItem(Base):
    __tablename__ = "sale_return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_return_items_quantity_positive"),
        UniqueConstraint("return_id", "sale_item_id", name="ux_return_items_return_sale_item"),
        Index("ix_return_items_return_id", "return_id"),
        Index("ix_return_items_sale_item_id", "sale_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False)
    sale_item_id: Mapped[int] = mapped_column(ForeignKey("sale_items.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    line_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))

    return_: Mapped[SaleReturn] = relationship(back_populates="items")
    sale_item: Mapped[SaleItem] = relationship()


class Expense(TimestampMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        Index("ix_expenses_occurred_at", "occurred_at"),
        Index("ix_expenses_category", "category"),
        Index("ix_expenses_method", "method"),
        Index("ix_expenses_idempotency_key", "idempotency_key", unique=True),
        Index("ix_expenses_uuid", "uuid", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    paid_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    stock_receipt: Mapped[StockReceipt | None] = relationship(
        back_populates="expense", uselist=False, foreign_keys="StockReceipt.expense_id"
    )


class StockReceipt(Base):
    __tablename__ = "stock_receipts"
    __table_args__ = (
        CheckConstraint("total_cost >= 0", name="ck_stock_receipts_cost_nonnegative"),
        Index("ix_stock_receipts_received_at", "received_at"),
        Index("ix_stock_receipts_uuid", "uuid", unique=True),
        Index("ix_stock_receipts_expense_id", "expense_id", unique=True),
        Index("ix_stock_receipts_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    supplier_ref: Mapped[str | None] = mapped_column(String(150), nullable=True)
    total_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    payment_method: Mapped[str] = mapped_column(String(40), nullable=False, default="cash")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    items: Mapped[list[StockReceiptItem]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="StockReceiptItem.id"
    )
    expense: Mapped[Expense | None] = relationship(
        back_populates="stock_receipt", foreign_keys=[expense_id]
    )


class StockReceiptItem(Base):
    __tablename__ = "stock_receipt_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_receipt_items_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_receipt_items_cost_nonnegative"),
        Index("ix_stock_receipt_items_receipt_id", "receipt_id"),
        Index("ix_stock_receipt_items_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("stock_receipts.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    receipt: Mapped[StockReceipt] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_change <> 0", name="ck_movements_quantity_nonzero"),
        Index("ix_movements_product_id", "product_id"),
        Index("ix_movements_occurred_at", "occurred_at"),
        Index("ix_movements_type", "movement_type"),
        Index("ix_movements_idempotency_key", "idempotency_key", unique=True),
        Index(
            "ux_movements_sale_item_sale",
            "sale_item_id",
            unique=True,
            sqlite_where=text("movement_type = 'sale'"),
        ),
        Index(
            "ux_movements_return_item",
            "sale_return_item_id",
            unique=True,
            sqlite_where=text("sale_return_item_id IS NOT NULL"),
        ),
        Index(
            "ux_movements_receipt_item",
            "stock_receipt_item_id",
            unique=True,
            sqlite_where=text("stock_receipt_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(
        enum_type(MovementType, "movement_type"), nullable=False
    )
    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="SET NULL"), nullable=True)
    sale_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("sale_items.id", ondelete="SET NULL"), nullable=True
    )
    sale_return_id: Mapped[int | None] = mapped_column(
        ForeignKey("sale_returns.id", ondelete="SET NULL"), nullable=True
    )
    sale_return_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("sale_return_items.id", ondelete="SET NULL"), nullable=True
    )
    stock_receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_receipts.id", ondelete="SET NULL"), nullable=True
    )
    stock_receipt_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_receipt_items.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    product: Mapped[Product] = relationship(back_populates="movements")
    sale: Mapped[Sale | None] = relationship(foreign_keys=[sale_id])
    stock_receipt: Mapped[StockReceipt | None] = relationship(foreign_keys=[stock_receipt_id])
    sale_return: Mapped[SaleReturn | None] = relationship(foreign_keys=[sale_return_id])


class Delivery(TimestampMixin, Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_status", "status"),
        Index("ix_deliveries_sale_id", "sale_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(
        enum_type(DeliveryStatus, "delivery_status"), nullable=False, default=DeliveryStatus.pending
    )
    delivery_person: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    sale: Mapped[Sale] = relationship(back_populates="delivery")


class CashSession(TimestampMixin, Base):
    __tablename__ = "cash_sessions"
    __table_args__ = (
        CheckConstraint("opening_cash >= 0", name="ck_cash_sessions_opening_nonnegative"),
        CheckConstraint("counted_cash IS NULL OR counted_cash >= 0", name="ck_cash_sessions_counted_nonnegative"),
        Index("ix_cash_sessions_date", "session_date", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    opening_cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    counted_cash: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CashHandover(Base):
    __tablename__ = "cash_handovers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_handovers_amount_positive"),
        Index("ix_handovers_handed_at", "handed_at"),
        Index("ix_handovers_method", "method"),
        Index("ix_handovers_idempotency_key", "idempotency_key", unique=True),
        Index("ix_handovers_uuid", "uuid", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    handed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False, default="cash")
    recipient: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class MoneyTransaction(TimestampMixin, Base):
    __tablename__ = "money_transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_money_transactions_amount_positive"),
        Index("ix_money_transactions_occurred_at", "occurred_at"),
        Index("ix_money_transactions_direction", "direction"),
        Index("ix_money_transactions_category", "category"),
        Index("ix_money_transactions_method", "method"),
        Index("ix_money_transactions_idempotency_key", "idempotency_key", unique=True),
        Index("ix_money_transactions_uuid", "uuid", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    direction: Mapped[MoneyDirection] = mapped_column(
        enum_type(MoneyDirection, "money_direction"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    person: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    void_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ReconciliationRecord(Base):
    __tablename__ = "reconciliation_records"
    __table_args__ = (
        Index("ix_reconciliation_sale_id", "sale_id"),
        Index("ix_reconciliation_status", "status"),
        Index("ix_reconciliation_external_id", "external_order_id"),
        Index("ix_reconciliation_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[ReconciliationStatus] = mapped_column(
        enum_type(ReconciliationStatus, "reconciliation_record_status"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_total: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    sale: Mapped[Sale] = relationship(back_populates="reconciliation_records")


class DuplicateReview(Base):
    __tablename__ = "duplicate_reviews"
    __table_args__ = (
        UniqueConstraint("sale_a_id", "sale_b_id", name="ux_duplicate_reviews_pair"),
        Index("ix_duplicate_reviews_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_a_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    sale_b_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[DuplicateReviewStatus] = mapped_column(
        enum_type(DuplicateReviewStatus, "duplicate_review_status"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_changed_at", "changed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncOperation(Base):
    __tablename__ = "sync_operations"
    __table_args__ = (
        Index("ix_sync_operations_operation_id", "operation_id", unique=True),
        Index("ix_sync_operations_entity", "entity_type", "entity_id"),
        Index("ix_sync_operations_status", "status"),
        Index("ix_sync_operations_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    operation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    local_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[SyncStatus] = mapped_column(enum_type(SyncStatus, "sync_status"), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)
