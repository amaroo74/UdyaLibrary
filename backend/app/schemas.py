from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class BookCreate(BaseModel):
    stock_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, max_length=150)
    subcategory: str | None = Field(default=None, max_length=150)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    price_source: str | None = Field(default=None, max_length=100)
    price_confirmed: bool = False

    @field_validator("stock_number", "title")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("author", "publisher", "category", "subcategory", "price_source")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                return None
        return value

class BookUpdate(BaseModel):
    stock_number: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, max_length=150)
    subcategory: str | None = Field(default=None, max_length=150)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    price_source: str | None = Field(default=None, max_length=100)
    price_confirmed: bool | None = None

    @field_validator("stock_number", "title")
    @classmethod
    def strip_required_text(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("This field cannot be blank")
        return value

    @field_validator("author", "publisher", "category", "subcategory", "price_source")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                return None
        return value

class BookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    serial_number: str
    stock_number: str
    title: str
    author: str | None
    publisher: str | None
    category: str | None
    subcategory: str | None
    price: Decimal | None
    price_source: str | None
    price_confirmed: bool
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    deleted_at: datetime | None
    is_complete: bool
    missing_fields: list[str]

class BookList(BaseModel):
    items: list[BookRead]
    total: int
    page: int
    page_size: int

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    parent_id: int | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Category name cannot be blank")
        return value

class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    parent_id: int | None = None

class CategoryHierarchy(BaseModel):
    id: int
    name: str
    subcategories: list[CategoryRead] = []

class UserLoginRequest(BaseModel):
    email: str
    password: str
    device_id: str | None = None

class UserPinLoginRequest(BaseModel):
    email: str
    device_id: str
    pin: str = Field(min_length=4, max_length=8)

class SetPinRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    device_id: str = Field(min_length=1)

class UserCreate(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=6, max_length=128)
    role: str = "librarian"

class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    has_trusted_pin: bool = False
    created_at: datetime

class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead

class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entity_type: str
    entity_id: int | None
    action: str
    details: str
    actor: str
    actor_role: str
    device_id: str | None
    created_at: datetime


