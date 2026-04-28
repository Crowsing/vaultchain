"""Pydantic request/response schemas for the auth API endpoints.

Every model carries `extra="forbid"` and an `examples` configuration so
the OpenAPI gate (AC-phase1-identity-005-02) finds populated examples.

These models live in the delivery layer alongside the routers; they
exist purely as the wire contract for the HTTP boundary. Use cases
return their own dataclasses; routers translate between the two.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from vaultchain.identity.domain.aggregates import MagicLinkMode

#: Strict, no-extra-fields config used by every wire-level model.
_STRICT = ConfigDict(extra="forbid")


# ----------------------------- /auth/request -----------------------------


class AuthRequestBody(BaseModel):
    model_config = _STRICT

    email: str = Field(..., min_length=3, max_length=254, examples=["alice@example.com"])
    mode: MagicLinkMode = Field(..., examples=[MagicLinkMode.SIGNUP])


class AuthRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"message_sent": True}})

    message_sent: bool = Field(..., examples=[True])


# ------------------------------ /auth/verify -----------------------------


class AuthVerifyBody(BaseModel):
    model_config = _STRICT

    token: str = Field(..., min_length=8, examples=["ml-tok-abcdef0123456789"])
    mode: MagicLinkMode = Field(..., examples=[MagicLinkMode.SIGNUP])


class AuthVerifyResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "email": "alice@example.com",
                "is_first_time": True,
                "requires_totp_enrollment": True,
                "requires_totp_challenge": False,
                "pre_totp_token": "pre-totp-abcdef0123456789",
            }
        },
    )

    user_id: UUID = Field(..., examples=["11111111-1111-1111-1111-111111111111"])
    email: str = Field(..., min_length=3, max_length=254, examples=["alice@example.com"])
    is_first_time: bool = Field(..., examples=[True])
    requires_totp_enrollment: bool = Field(..., examples=[True])
    requires_totp_challenge: bool = Field(..., examples=[False])
    pre_totp_token: str = Field(..., examples=["pre-totp-abcdef0123456789"])


# ----------------------------- /auth/totp/* ------------------------------


class TotpEnrollResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "secret_for_qr": "JBSWY3DPEHPK3PXP",
                "qr_payload_uri": "otpauth://totp/VaultChain:alice%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=VaultChain",
                "backup_codes": [
                    "AAAA-BBBB-CCCC",
                    "DDDD-EEEE-FFFF",
                    "GGGG-HHHH-IIII",
                    "JJJJ-KKKK-LLLL",
                    "MMMM-NNNN-OOOO",
                    "PPPP-QQQQ-RRRR",
                    "SSSS-TTTT-UUUU",
                    "VVVV-WWWW-XXXX",
                    "YYYY-ZZZZ-AAAA",
                    "BBBB-CCCC-DDDD",
                ],
            }
        },
    )

    secret_for_qr: str = Field(..., examples=["JBSWY3DPEHPK3PXP"])
    qr_payload_uri: str = Field(
        ...,
        examples=[
            "otpauth://totp/VaultChain:alice%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=VaultChain"
        ],
    )
    backup_codes: list[str] = Field(..., examples=[["AAAA-BBBB-CCCC", "DDDD-EEEE-FFFF"]])


class TotpEnrollConfirmBody(BaseModel):
    model_config = _STRICT
    code: str = Field(..., min_length=6, max_length=8, examples=["123456"])


class TotpVerifyBody(BaseModel):
    model_config = _STRICT
    code: str = Field(..., min_length=6, max_length=64, examples=["123456"])
    use_backup_code: bool = Field(default=False, examples=[False])


class TotpVerifyResponse(BaseModel):
    """Returned both on success and on a wrong-code path. The 403 lockout
    case is signalled via the error envelope, not this body.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"success": True, "attempts_remaining": None},
        },
    )

    success: bool = Field(..., examples=[True])
    attempts_remaining: int | None = Field(default=None, examples=[None])


class BackupCodesRegenerateResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "backup_codes": [
                    "AAAA-BBBB-CCCC",
                    "DDDD-EEEE-FFFF",
                    "GGGG-HHHH-IIII",
                    "JJJJ-KKKK-LLLL",
                    "MMMM-NNNN-OOOO",
                    "PPPP-QQQQ-RRRR",
                    "SSSS-TTTT-UUUU",
                    "VVVV-WWWW-XXXX",
                    "YYYY-ZZZZ-AAAA",
                    "BBBB-CCCC-DDDD",
                ]
            }
        },
    )

    backup_codes: list[str] = Field(
        ...,
        examples=[["AAAA-BBBB-CCCC", "DDDD-EEEE-FFFF"]],
    )


# -------------------------------- /me -----------------------------------


class MeResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "id": "11111111-1111-1111-1111-111111111111",
                "email": "alice@example.com",
                "status": "verified",
                "kyc_tier": 0,
                "totp_enrolled": True,
                "created_at": "2026-04-28T09:00:00+00:00",
            }
        },
    )

    id: UUID = Field(..., examples=["11111111-1111-1111-1111-111111111111"])
    email: str = Field(..., min_length=3, max_length=254, examples=["alice@example.com"])
    status: str = Field(..., examples=["verified"])
    kyc_tier: int = Field(..., examples=[0])
    totp_enrolled: bool = Field(..., examples=[True])
    created_at: datetime = Field(..., examples=["2026-04-28T09:00:00+00:00"])


__all__ = [
    "AuthRequestBody",
    "AuthRequestResponse",
    "AuthVerifyBody",
    "AuthVerifyResponse",
    "BackupCodesRegenerateResponse",
    "MeResponse",
    "TotpEnrollConfirmBody",
    "TotpEnrollResponse",
    "TotpVerifyBody",
    "TotpVerifyResponse",
]
