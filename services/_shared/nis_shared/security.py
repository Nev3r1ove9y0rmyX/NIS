"""密码哈希与常量时间比较。

只做两件事：

- 用 bcrypt 做自适应哈希（``docs/requirements.md`` NFR-SEC-001），不落明文、不做可逆加密；
- 提供常量时间比较，供令牌与签名比对使用。

JWT 签发与验签属于 Issue #8（登录认证），不放在这里。
"""

from __future__ import annotations

import hmac
import os
import secrets

import bcrypt

#: bcrypt 单次哈希代价。12 轮在课程环境（单机四终端）延迟约 0.2 秒；
#: 测试用 ``NIS_BCRYPT_ROUNDS=4`` 加速，生产环境不要下调。
BCRYPT_ROUNDS = int(os.environ.get("NIS_BCRYPT_ROUNDS", "12"))

#: bcrypt 只处理前 72 字节，超长口令先截断再由哈希函数加盐，避免静默截断带来的歧义。
_MAX_PASSWORD_BYTES = 72


def _encode(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > _MAX_PASSWORD_BYTES:
        raw = raw[:_MAX_PASSWORD_BYTES]
    return raw


def hash_password(password: str) -> str:
    """返回 bcrypt 哈希字符串（含算法、代价与盐）。"""

    if not password:
        raise ValueError("密码不能为空")
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码；哈希格式非法时返回 False，不抛异常，避免泄露内部信息。"""

    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(_encode(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """代价低于当前基线时建议在下次登录成功后重新哈希。"""

    try:
        rounds = int(password_hash.split("$")[2])
    except (IndexError, ValueError):
        return True
    return rounds < BCRYPT_ROUNDS


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def generate_token(byte_length: int = 32) -> str:
    """生成不可预测的随机串（服务令牌、幂等参考值等）。"""

    return secrets.token_urlsafe(byte_length)
