-- 时区口径：应用侧 use_tz=False，所有时间列都按东八区墙钟写入和读出。
-- 这里把 MySQL 的全局时区固定为 +08:00，保证 CURRENT_TIMESTAMP 生成的默认时间
-- 与 common/times.now() 是同一个时区（容器/CI 的宿主机时区可能是 UTC）。
-- 该设置只影响当前 MySQL 实例，容器重建后由本初始化脚本重新设置。
SET GLOBAL time_zone = '+08:00';
SET time_zone = '+08:00';
