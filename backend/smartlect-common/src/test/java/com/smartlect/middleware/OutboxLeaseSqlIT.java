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
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

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
}
