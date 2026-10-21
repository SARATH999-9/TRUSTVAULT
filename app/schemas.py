from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
Portal = Literal["admin", "owner", "viewer"]


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    portal: Portal | None = None

    @field_validator("email")
    @classmethod
    def norm(cls, v):
        return v.strip().lower()


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=EMAIL_RE, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["owner", "viewer"]                 # nobody can self-register as an administrator

    @field_validator("email")
    @classmethod
    def norm(cls, v):
        return v.strip().lower()

    @field_validator("name")
    @classmethod
    def clean_name(cls, v):
        return " ".join(v.split())

    @model_validator(mode="after")
    def not_the_email(self):
        if self.password.lower() == self.email:
            raise ValueError("Password must not be your email address")
        return self


class GoogleIn(BaseModel):
    credential: str = Field(min_length=20, max_length=8192)
    portal: Portal


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class UserCreateIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["admin", "owner", "viewer"]

    @field_validator("email")
    @classmethod
    def norm(cls, v):
        return v.strip().lower()


class UserUpdateIn(BaseModel):
    role: Literal["admin", "owner", "viewer"] | None = None
    status: Literal["active", "rejected", "suspended"] | None = None
    is_active: bool | None = None                    # kept for older clients: False = suspended, True = active
    reason: str | None = Field(default=None, max_length=500)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    status: str
    email_verified: bool
    auth_provider: str
    created_at: datetime | None = None
    decision_reason: str | None = None

    model_config = {"from_attributes": True}


class AdminUserOut(UserOut):
    registered_ip: str | None = None
    last_login_at: datetime | None = None
    decided_at: datetime | None = None
