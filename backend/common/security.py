"""密码哈希与校验。

库里的密码不再存明文。每个密码单独生成 16 字节随机盐，用 PBKDF2-SHA256
迭代 120000 次得到摘要，存成固定格式的字符串：

    pbkdf2_sha256$120000$<盐的十六进制>$<摘要的十六进制>

历史数据里的明文密码仍然能登录（见 verify_password），登录成功后由
account_service 顺手升级成哈希，不需要批量刷库，也不用通知用户改密码。
"""

import hashlib
import hmac
import os

# 哈希算法标识，也是存储格式的第一段。换算法时改这里，needs_rehash 会据此
# 把旧格式的密码挑出来重新哈希
HASH_ALGORITHM = "pbkdf2_sha256"
# 迭代次数。调高会拖慢每次登录，调低会削弱抗离线暴力破解的能力，
# 两边取一个平衡值；改这里之后旧哈希会在下次登录时自动升级
HASH_ITERATIONS = 120000
# 每个密码单独的盐长度，16 字节 = 32 个十六进制字符
SALT_BYTES = 16

# 存储格式里各段之间的分隔符
_SEPARATOR = "$"


def hash_password(raw: str) -> str:
    """把明文密码转成可入库的哈希串。

    每次调用都会生成新的盐，所以同一个密码每次哈希出来的结果都不同，
    库里也看不出两个账号是不是用了同一个密码。
    """
    text = raw or ""
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", text.encode("utf-8"), salt, HASH_ITERATIONS)
    return _SEPARATOR.join(
        (HASH_ALGORITHM, str(HASH_ITERATIONS), salt.hex(), digest.hex()))


def verify_password(raw: str | None, stored: str | None) -> bool:
    """校验明文密码和库里存的值是否匹配。

    库里存的可能是新格式的哈希，也可能是历史数据里的明文：
    - 哈希：按存储里记录的迭代次数重算摘要，用 hmac.compare_digest 做定长比较，
      比较过程不因为第几个字符不同而提前返回，避免从耗时上试探密码；
    - 明文：直接做定长比较，保证老账号在完成升级之前仍然能登录。
    """
    text = raw or ""
    if not stored:
        return False
    if not stored.startswith(HASH_ALGORITHM + _SEPARATOR):
        # 历史数据里的明文密码，保持兼容；登录成功后会被升级成哈希
        return hmac.compare_digest(text, stored)
    parts = stored.split(_SEPARATOR)
    if len(parts) != 4:
        return False
    algorithm, iterations_text, salt_hex, hash_hex = parts
    if algorithm != HASH_ALGORITHM:
        return False
    try:
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (TypeError, ValueError):
        return False
    if iterations <= 0:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", text.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def needs_rehash(stored: str | None) -> bool:
    """判断库里的密码串是否需要按当前配置重新生成哈希。

    旧明文、格式损坏、迭代次数与当前配置不一致，都要升级。
    """
    if not stored or not stored.startswith(HASH_ALGORITHM + _SEPARATOR):
        return True
    parts = stored.split(_SEPARATOR)
    if len(parts) != 4 or parts[0] != HASH_ALGORITHM:
        return True
    try:
        iterations = int(parts[1])
        bytes.fromhex(parts[2])
        bytes.fromhex(parts[3])
    except (TypeError, ValueError):
        return True
    return iterations != HASH_ITERATIONS


def password_fingerprint(stored: str | None) -> str:
    """密码存储值（哈希或历史明文）的短指纹，写进 token 用来做吊销。

    改密码会改变库里的存储值，指纹跟着变，旧 token 里的指纹就对不上，
    get_current_user 一验就能让旧 token 立即失效；换新密码重新登录拿新 token。
    只取摘要前 16 位十六进制：够区分，又不把存储值本身放进可被解码的 token。
    """
    text = stored or ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]