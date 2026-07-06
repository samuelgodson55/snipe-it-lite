from typing import Optional
from pydantic import BaseModel, field_validator
from security import validate_password_strength


class UserCreateRequest(BaseModel):
    name: str
    email: str
    role: str
    password: str
    department: Optional[str] = None
    department_role: Optional[str] = None

    # Data Quality & Usability requirement #3: reject weak passwords at
    # account-creation time (Super Admin or Manager provisioning a new
    # login) before they're ever hashed and stored. See
    # security.validate_password_strength for the exact rule set.
    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        return validate_password_strength(value)
