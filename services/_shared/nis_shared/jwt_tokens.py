"""JWT 签发与验签（RS256）。

规则（docs/architecture.md 第 10 节、service-contracts 第 7 节）：

- 私钥只在 IAM Service，业务服务只持有公钥；
- 业务服务独立验签，不接受「Gateway 说是谁就是谁」；
- 令牌里只放身份与角色，权限每次向 IAM 取，保证改权限后立即生效；
- 访问令牌与刷新令牌用 ``typ`` 区分，刷新令牌不能当访问令牌用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    roles: tuple[str, ...]
    organization_id: str | None
    jti: str
    token_type: str

    @property
    def is_access(self) -> bool:
        return self.token_type == ACCESS_TOKEN_TYPE


class TokenError(Exception):
    """令牌无效、过期或类型不符。"""


class SigningKey:
    """IAM 的签名材料：优先读 PEM 文件，开发环境生成临时密钥。"""

    def __init__(self, private_key_pem: str, kid: str) -> None:
        self._private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"), password=None
        )
        self.kid = kid
        if not isinstance(self._private_key, rsa.RSAPrivateKey):
            raise TypeError("JWT 私钥必须是 RSA 私钥（RS256）")
        self.public_key_pem = (
            self._private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("utf-8")
        )

    @classmethod
    def from_files(cls, private_path: str, kid: str) -> "SigningKey":
        return cls(Path(private_path).read_text(encoding="utf-8"), kid)

    @classmethod
    def generate_dev(cls, kid: str = "nis-key-1") -> "SigningKey":
        """开发/测试用临时密钥：每次进程启动都不同，重启后旧令牌自然失效。"""

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        return cls(pem, kid)


def load_signing_key() -> SigningKey:
    """按环境变量加载私钥：有 PEM 就用 PEM，否则仅在开发环境生成临时密钥。"""

    kid = os.environ.get("JWT_KID", "nis-key-1")
    path = os.environ.get("JWT_PRIVATE_KEY_PATH", "").strip()
    if path and Path(path).is_file():
        return SigningKey.from_files(path, kid)

    env = os.environ.get("APP_ENV", "development").lower()
    if env in {"development", "dev", "local", "test"}:
        return SigningKey.generate_dev(kid)
    raise RuntimeError(
        "缺少 JWT 私钥：请挂载 JWT_PRIVATE_KEY_PATH 指向的 PEM（生产环境不允许临时密钥）"
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(
    *,
    signing_key: SigningKey,
    user_id: str,
    roles: list[str],
    organization_id: str | None,
    token_type: str,
    expires_minutes: int,
    jti: str,
    role_context: str | None = None,
) -> str:
    issued = _now()
    payload: dict[str, object] = {
        "sub": user_id,
        "roles": roles,
        "org": organization_id,
        "typ": token_type,
        "jti": jti,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=expires_minutes)).timestamp()),
        "iss": "nis-iam",
    }
    if role_context:
        payload["role_context"] = role_context
    return pyjwt.encode(payload, signing_key._private_key, algorithm="RS256", headers={"kid": signing_key.kid})


def decode_token(
    token: str,
    public_key_pem: str,
    *,
    expected_type: str | None = ACCESS_TOKEN_TYPE,
    leeway_seconds: int = 10,
) -> TokenPayload:
    """验签 + 校验声明；失败一律抛 :class:`TokenError`，不泄露内部原因。"""

    try:
        claims = pyjwt.decode(
            token,
            public_key_pem,
            algorithms=["RS256"],
            leeway=leeway_seconds,
            options={"require": ["exp", "iat", "sub", "typ"]},
        )
    except pyjwt.PyJWTError as exc:
        raise TokenError(type(exc).__name__) from exc

    if expected_type is not None and claims.get("typ") != expected_type:
        raise TokenError("token_type_mismatch")

    roles = claims.get("roles") or []
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        raise TokenError("invalid_roles")

    return TokenPayload(
        user_id=str(claims["sub"]),
        roles=tuple(roles),
        organization_id=claims.get("org"),
        jti=str(claims.get("jti", "")),
        token_type=str(claims["typ"]),
    )
