package com.smartlect.middleware;

import com.smartlect.mappers.LocalMessageOutboxMapper;
import com.smartlect.entity.po.LocalMessageOutbox;
import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 自查回归网（2026-10-15）：批次六把租约时间改为 SQL 侧 DATE_ADD 计算时误用了
 * MySQL 不存在的 MILLISECOND 区间单位——单元测试 mock mapper、MiddlewareIT 又不经过
 * 该 mapper，语法错误完全没被测到（生产上每次认领都会抛错）。本 IT 用真 MySQL 直接执行
 * 认领/失败/批量选取三条语句，锁住 SQL 方言正确性。
 */
@Testcontainers
class OutboxLeaseSqlIT {
    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4.11")
            .withDatabaseName("smartlect_outbox_sql_it").withUsername("smartlect").withPassword("smartlect");
    private static SqlSessionFactory sessions;

    @BeforeAll
    static void migrate() {
        var dataSource = new UnpooledDataSource("com.mysql.cj.jdbc.Driver", MYSQL.getJdbcUrl(),
                MYSQL.getUsername(), MYSQL.getPassword());
        // 复用 order 域迁移（含 local_message_outbox 表；批注同 MiddlewareIT 的 8 库回归）
        Flyway.configure().dataSource(dataSource)
                .locations("filesystem:../smartlect-order/app/src/main/resources/db/migration")
                .baselineOnMigrate(true).baselineVersion("0").load().migrate();
        Configuration config = new Configuration(
                new Environment("outbox-sql", new JdbcTransactionFactory(), dataSource));
        config.setMapUnderscoreToCamelCase(true);
        config.addMapper(LocalMessageOutboxMapper.class);
        sessions = new SqlSessionFactoryBuilder().build(config);
    }

    @BeforeEach
    void cleanTable() {
        // 两用例共用容器表；selectDispatchBatch 计数断言要求各自从空表开始（互不干扰）
        try (SqlSession session = sessions.openSession(true);
             Statement statement = session.getConnection().createStatement()) {
            statement.executeUpdate("delete from local_message_outbox");
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Test
    void claimMarkFailedAndBatchSelectExecuteAgainstRealMysql() {
        try (SqlSession session = sessions.openSession(true)) {
            LocalMessageOutboxMapper mapper = session.getMapper(LocalMessageOutboxMapper.class);
            LocalMessageOutbox row = new LocalMessageOutbox();
            row.setIdempotencyKey("lease-sql-it-1");
            row.setExchangeName("smartlect-pay");
            row.setRoutingKey("pay-success");
            row.setPayloadJson("{}");
            row.setReliabilityLevel("STANDARD");
            row.setStatus(0);
            row.setRetryCount(0);
            row.setCreateTime(new Date());
            row.setUpdateTime(new Date());
            mapper.insert(row);

            // 认领：租约由 DATE_ADD(NOW(), INTERVAL ... MICROSECOND) 计算——MILLISECOND 写法在此行抛 1064
            assertEquals(1, mapper.claimForDispatch(row.getId(), 0, 2, 1, "worker-a", 30_000_000L));
            // 租约未到期不可重认领
            assertEquals(0, mapper.claimForDispatch(row.getId(), 0, 2, 1, "worker-b", 30_000_000L));
            // 失败：退避由 DATE_ADD(NOW(), INTERVAL ... SECOND) 计算
            assertEquals(1, mapper.markFailed(row.getId(), 1, 2, "worker-a", "boom", 60L));
            // 批量选取：next_retry_time 在未来 → 不入选
            assertEquals(0, mapper.selectDispatchBatch(0, 2, 1, new Date(), 10, 10).size());
            assertNotNull(mapper.selectByIdempotencyKey("lease-sql-it-1"));
        }
    }

    @Test
    void parkUntilTimerHorizonParksFarFutureButNotNearFuture() {
        long horizon = 86_400_000L;
        long wakeBefore = 60_000L;
        try (SqlSession session = sessions.openSession(true)) {
            LocalMessageOutboxMapper mapper = session.getMapper(LocalMessageOutboxMapper.class);

            // 7 天后到期：命中驻留，next_retry_time 应 ≈ 到期 - 24h + 60s（from_unixtime 秒级）
            LocalMessageOutbox far = insertTimed(mapper, "park-it-far", System.currentTimeMillis() + 7 * 86_400_000L);
            assertEquals(1, mapper.parkUntilTimerHorizon(far.getId(), 0, 2, horizon, wakeBefore));
            // 重复驻留等价幂等：再次写入同一唤醒时刻，值不变（不产生累计漂移）
            assertEquals(1, mapper.parkUntilTimerHorizon(far.getId(), 0, 2, horizon, wakeBefore));
            long expectedEpochSec = (far.getDeliveryExpireAt() - horizon + wakeBefore) / 1000;
            long actualEpochSec = queryEpochSec(session, far.getId());
            assertTrue(Math.abs(actualEpochSec - expectedEpochSec) <= 1,
                    "next_retry_time 应为 from_unixtime(到期 - 上限 + 余量)，实际差 "
                            + (actualEpochSec - expectedEpochSec) + "s");

            // 1 小时后到期：剩余延迟在上限内，不驻留（0 行，调用方继续正常投递）
            LocalMessageOutbox near = insertTimed(mapper, "park-it-near", System.currentTimeMillis() + 3_600_000L);
            assertEquals(0, mapper.parkUntilTimerHorizon(near.getId(), 0, 2, horizon, wakeBefore));
            assertEquals(1, mapper.selectDispatchBatch(0, 2, 1, new Date(), 10, 10).size(),
                    "未驻留的 near 行可被兜底批量选中（far 行驻留到未来被排除）");
        }
    }

    private LocalMessageOutbox insertTimed(LocalMessageOutboxMapper mapper, String key, long expireAt) {
        LocalMessageOutbox row = new LocalMessageOutbox();
        row.setIdempotencyKey(key);
        row.setExchangeName("smartlect-delay");
        row.setRoutingKey("confirm-receipt");
        row.setPayloadJson("{}");
        row.setReliabilityLevel("STANDARD");
        row.setStatus(0);
        row.setRetryCount(0);
        row.setDeliveryExpireAt(expireAt);
        row.setCreateTime(new Date());
        row.setUpdateTime(new Date());
        mapper.insert(row);
        return row;
    }

    /** 用数据库自身的会话读回 epoch 秒，避免 JDBC 会话时区在本断言里制造假失败。 */
    private long queryEpochSec(SqlSession session, Long id) {
        try (Statement statement = session.getConnection().createStatement();
             ResultSet rs = statement.executeQuery(
                     "select unix_timestamp(next_retry_time) from local_message_outbox where id = " + id)) {
            if (!rs.next()) {
                throw new IllegalStateException("row missing: " + id);
            }
            return rs.getLong(1);
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }
}
