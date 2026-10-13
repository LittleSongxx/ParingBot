package com.smartlect.middleware;

import com.smartlect.constants.Constants;
import com.smartlect.redis.LuaScriptLoader;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationVersion;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

@Testcontainers
class MiddlewareIT {

    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4.11")
            .withDatabaseName("smartlect")
            .withUsername("smartlect")
            .withPassword("smartlect");

    @Container
    static final GenericContainer<?> REDIS = new GenericContainer<>(
            DockerImageName.parse("redis:7.2-alpine"))
            .withExposedPorts(6379);

    @Test
    void mysqlEnforcesIdempotencyAndAtomicStockUnderConcurrency() throws Exception {
        try (Connection connection = mysqlConnection();
             Statement statement = connection.createStatement()) {
            statement.executeUpdate("""
                    CREATE TABLE IF NOT EXISTS middleware_request (
                      id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                      user_id BIGINT NOT NULL,
                      command_type VARCHAR(32) NOT NULL,
                      idempotency_key VARCHAR(64) NOT NULL,
                      payload_hash CHAR(64) NOT NULL,
                      UNIQUE KEY uq_request (user_id, command_type, idempotency_key)
                    ) ENGINE=InnoDB
                    """);
            statement.executeUpdate("""
                    CREATE TABLE IF NOT EXISTS middleware_stock (
                      id BIGINT NOT NULL PRIMARY KEY,
                      stock INT NOT NULL
                    ) ENGINE=InnoDB
                    """);
            statement.executeUpdate("DELETE FROM middleware_request");
            statement.executeUpdate("DELETE FROM middleware_stock");
            statement.executeUpdate("INSERT INTO middleware_stock(id, stock) VALUES (1, 1)");
        }

        int workers = 12;
        ExecutorService pool = Executors.newFixedThreadPool(workers);
        CountDownLatch ready = new CountDownLatch(workers);
        CountDownLatch start = new CountDownLatch(1);
        List<Future<Integer>> idempotencyResults = new ArrayList<>();
        List<Future<Integer>> stockResults = new ArrayList<>();
        for (int i = 0; i < workers; i++) {
            idempotencyResults.add(pool.submit(() -> {
                ready.countDown();
                start.await();
                try (Connection connection = mysqlConnection();
                     PreparedStatement insert = connection.prepareStatement("""
                             INSERT INTO middleware_request
                               (user_id, command_type, idempotency_key, payload_hash)
                             VALUES (?, ?, ?, ?)
                             ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
                             """);
                     PreparedStatement select = connection.prepareStatement(
                             "SELECT id FROM middleware_request WHERE user_id=? AND command_type=? AND idempotency_key=?")) {
                    insert.setLong(1, 7L);
                    insert.setString(2, "ORDER");
                    insert.setString(3, "same-request-key");
                    insert.setString(4, "hash-a");
                    insert.executeUpdate();
                    select.setLong(1, 7L);
                    select.setString(2, "ORDER");
                    select.setString(3, "same-request-key");
                    try (ResultSet result = select.executeQuery()) {
                        assertTrue(result.next());
                        return result.getInt(1);
                    }
                }
            }));
            stockResults.add(pool.submit(() -> {
                ready.countDown();
                start.await();
                try (Connection connection = mysqlConnection();
                     PreparedStatement update = connection.prepareStatement(
                             "UPDATE middleware_stock SET stock=stock-1 WHERE id=1 AND stock >= 1")) {
                    return update.executeUpdate();
                }
            }));
        }
        assertTrue(ready.await(10, TimeUnit.SECONDS));
        start.countDown();

        List<Integer> claimedIds = new ArrayList<>();
        int successfulStockUpdates = 0;
        for (Future<Integer> result : idempotencyResults) {
            claimedIds.add(result.get(10, TimeUnit.SECONDS));
        }
        for (Future<Integer> result : stockResults) {
            successfulStockUpdates += result.get(10, TimeUnit.SECONDS);
        }
        pool.shutdownNow();

        assertEquals(1, claimedIds.stream().distinct().count());
        assertEquals(1, successfulStockUpdates);
        try (Connection connection = mysqlConnection();
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery("SELECT stock FROM middleware_stock WHERE id=1")) {
            assertTrue(result.next());
            assertEquals(0, result.getInt(1));
        }
    }

    @Test
    void mysqlRollbackLeavesNoOutboxRecordAndUniqueKeyRejectsDifferentPayload() throws Exception {
        try (Connection connection = mysqlConnection();
             Statement statement = connection.createStatement()) {
            statement.executeUpdate("""
                    CREATE TABLE IF NOT EXISTS middleware_outbox (
                      id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                      idempotency_key VARCHAR(64) NOT NULL,
                      payload_hash CHAR(64) NOT NULL,
                      UNIQUE KEY uq_outbox_key (idempotency_key)
                    ) ENGINE=InnoDB
                    """);
            statement.executeUpdate("DELETE FROM middleware_outbox");
        }

        try (Connection connection = mysqlConnection();
             PreparedStatement insert = connection.prepareStatement(
                     "INSERT INTO middleware_outbox(idempotency_key, payload_hash) VALUES (?, ?)")) {
            connection.setAutoCommit(false);
            insert.setString(1, "rollback-key");
            insert.setString(2, "hash-a");
            insert.executeUpdate();
            connection.rollback();
        }

        try (Connection connection = mysqlConnection();
             PreparedStatement insert = connection.prepareStatement(
                     "INSERT INTO middleware_outbox(idempotency_key, payload_hash) VALUES (?, ?)")) {
            insert.setString(1, "same-key");
            insert.setString(2, "hash-a");
            assertEquals(1, insert.executeUpdate());
            insert.setString(2, "hash-b");
            assertThrows(java.sql.SQLIntegrityConstraintViolationException.class, () -> {
                insert.executeUpdate();
            });
        }

        try (Connection connection = mysqlConnection();
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery(
                     "SELECT COUNT(*) FROM middleware_outbox WHERE idempotency_key='rollback-key'")) {
            assertTrue(result.next());
            assertEquals(0, result.getInt(1));
        }
    }

    @Test
    void javaDomainSchemasMigrateFreshAndRemainRepeatable() throws Exception {
        List<Path> migrations = findCurrentJavaMigrations();
        assertEquals(8, migrations.size(), migrations.toString());

        for (Path migration : migrations) {
            String jdbcUrl = MYSQL.getJdbcUrl();
            Flyway flyway = Flyway.configure()
                    .dataSource(jdbcUrl, MYSQL.getUsername(), MYSQL.getPassword())
                    .locations("filesystem:" + migration.getParent().toAbsolutePath())
                    .baselineOnMigrate(true)
                    .baselineVersion(MigrationVersion.fromVersion("0"))
                    .cleanDisabled(false)
                    .validateOnMigrate(true)
                    .load();

            flyway.clean();
            boolean adminMigration = migration.toString().contains("smartlect-admin");
            if (adminMigration) {
                // Admin's semantic views intentionally read facts owned by other
                // services. Prepare those dependencies as already-migrated schemas;
                // do not replace this with empty placeholder views, because that
                // would hide broken column contracts and definer privileges.
                prepareAnalyticsSourceSchemas();
            }
            flyway.migrate();
            flyway.validate();

            if (adminMigration) {
                assertAnalyticsViewsCreated();
                assertAnalyticsReaderBoundary();
            }

            try (Connection connection = DriverManager.getConnection(
                    jdbcUrl, MYSQL.getUsername(), MYSQL.getPassword());
                 Statement statement = connection.createStatement()) {
                assertEquals(1, statement.executeUpdate(
                        "DELETE FROM flyway_schema_history WHERE version IS NULL"));
            }

            flyway.migrate();
            flyway.validate();
            flyway.clean();
        }
    }

    private static void prepareAnalyticsSourceSchemas() throws Exception {
        try (Connection connection = rootConnection();
             Statement statement = connection.createStatement()) {
            statement.execute("CREATE DATABASE IF NOT EXISTS smartlect_order "
                    + "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci");
            statement.execute("CREATE DATABASE IF NOT EXISTS smartlect_product "
                    + "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci");
            statement.execute("CREATE DATABASE IF NOT EXISTS smartlect_stock "
                    + "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci");

            statement.execute("""
                    CREATE TABLE IF NOT EXISTS smartlect_order.order_info (
                      order_id VARCHAR(32) NOT NULL PRIMARY KEY,
                      order_time DATETIME NOT NULL,
                      order_status INT NOT NULL,
                      amount DECIMAL(18,2) NOT NULL
                    ) ENGINE=InnoDB
                    """);
            statement.execute("""
                    CREATE TABLE IF NOT EXISTS smartlect_order.order_item (
                      order_item_id VARCHAR(32) NOT NULL PRIMARY KEY,
                      order_id VARCHAR(32) NOT NULL,
                      product_id VARCHAR(32) NOT NULL,
                      property_value_id_hash VARCHAR(128) NOT NULL,
                      product_name VARCHAR(255) NOT NULL,
                      buy_count INT NOT NULL,
                      item_amount DECIMAL(18,2) NOT NULL
                    ) ENGINE=InnoDB
                    """);
            statement.execute("""
                    CREATE TABLE IF NOT EXISTS smartlect_order.refund_request (
                      refund_id VARCHAR(32) NOT NULL PRIMARY KEY,
                      created_at DATETIME NOT NULL,
                      completed_at DATETIME NULL,
                      status VARCHAR(32) NOT NULL,
                      refund_amount DECIMAL(18,2) NOT NULL,
                      product_id VARCHAR(32) NOT NULL,
                      order_item_id VARCHAR(32) NOT NULL,
                      buy_count INT NOT NULL
                    ) ENGINE=InnoDB
                    """);
            statement.execute("""
                    CREATE TABLE IF NOT EXISTS smartlect_product.product_info (
                      product_id VARCHAR(32) NOT NULL PRIMARY KEY,
                      product_name VARCHAR(255) NOT NULL,
                      status INT NOT NULL
                    ) ENGINE=InnoDB
                    """);
            statement.execute("""
                    CREATE TABLE IF NOT EXISTS smartlect_stock.sku_stock (
                      product_id VARCHAR(32) NOT NULL,
                      property_value_id_hash VARCHAR(128) NOT NULL,
                      stock INT NOT NULL,
                      PRIMARY KEY (product_id, property_value_id_hash)
                    ) ENGINE=InnoDB
                    """);

            // The migration runs as the application user. A definer view can only
            // be created when that user has privileges on every source table.
            statement.execute("GRANT SELECT ON smartlect_order.* TO 'smartlect'@'%'");
            statement.execute("GRANT SELECT ON smartlect_product.* TO 'smartlect'@'%'");
            statement.execute("GRANT SELECT ON smartlect_stock.* TO 'smartlect'@'%'");
        }
    }

    private static void assertAnalyticsViewsCreated() throws Exception {
        try (Connection connection = mysqlConnection();
             PreparedStatement statement = connection.prepareStatement("""
                     SELECT COUNT(*)
                       FROM information_schema.views
                      WHERE table_schema = DATABASE()
                        AND table_name IN (
                          'analytics_sales_daily',
                          'analytics_product_sales_daily',
                          'analytics_inventory_risk',
                          'analytics_fulfillment_after_sales_daily'
                        )
                     """)) {
            try (ResultSet result = statement.executeQuery()) {
                assertTrue(result.next());
                assertEquals(4, result.getInt(1));
            }
            try (PreparedStatement collation = connection.prepareStatement("""
                    SELECT collation_name
                      FROM information_schema.columns
                     WHERE table_schema = DATABASE()
                       AND table_name = 'analytics_inventory_risk'
                       AND column_name = 'risk_level'
                    """)) {
                try (ResultSet result = collation.executeQuery()) {
                    assertTrue(result.next());
                    assertEquals("utf8mb4_general_ci", result.getString(1));
                }
            }
        }
    }

    private static void assertAnalyticsReaderBoundary() throws Exception {
        String reader = "analytics_reader_it";
        String password = "reader-it-secret";
        String database = MYSQL.getDatabaseName();
        try (Connection root = rootConnection();
             Statement statement = root.createStatement()) {
            statement.execute("DROP USER IF EXISTS '" + reader + "'@'%'");
            statement.execute("CREATE USER '" + reader + "'@'%' IDENTIFIED BY '" + password + "'");
            statement.execute("REVOKE ALL PRIVILEGES, GRANT OPTION FROM '" + reader + "'@'%'");
            statement.execute("GRANT SELECT ON `" + database + "`.analytics_sales_daily TO '"
                    + reader + "'@'%'");
            statement.execute("GRANT SELECT ON `" + database + "`.analytics_product_sales_daily TO '"
                    + reader + "'@'%'");
            statement.execute("GRANT SELECT ON `" + database + "`.analytics_inventory_risk TO '"
                    + reader + "'@'%'");
            statement.execute("GRANT SELECT ON `" + database + "`.analytics_fulfillment_after_sales_daily TO '"
                    + reader + "'@'%'");
        }

        try (Connection connection = DriverManager.getConnection(
                MYSQL.getJdbcUrl(), reader, password);
             Statement statement = connection.createStatement()) {
            try (ResultSet result = statement.executeQuery(
                    "SELECT COUNT(*) FROM `" + database + "`.analytics_sales_daily")) {
                assertTrue(result.next());
            }
            assertThrows(java.sql.SQLException.class, () -> statement.executeQuery(
                    "SELECT COUNT(*) FROM smartlect_order.order_info"));
            assertThrows(java.sql.SQLException.class, () -> statement.executeUpdate(
                    "CREATE TABLE analytics_reader_write_probe (id INT)"));
        } finally {
            try (Connection root = rootConnection();
                 Statement statement = root.createStatement()) {
                statement.execute("DROP USER IF EXISTS '" + reader + "'@'%'");
            }
        }
    }

    @Test
    void redisCompareDeleteOnlyRemovesTheCurrentOwner() throws Exception {
        String key = "middleware:lock:" + UUID.randomUUID();
        try (RedisWire redis = new RedisWire(REDIS.getHost(), REDIS.getMappedPort(6379))) {
            assertEquals("OK", redis.command("SET", key, "owner-a", "NX", "PX", "30000"));
            assertEquals("0", redis.command(
                    "EVAL",
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                    "1", key, "owner-b"));
            assertEquals("owner-a", redis.command("GET", key));
            assertEquals("1", redis.command(
                    "EVAL",
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                    "1", key, "owner-a"));
            assertEquals("(nil)", redis.command("GET", key));
        }
    }

    /**
     * 抢购参与者 SET 清理脚本的真实语义。单测只能验"分了几批"，判定本身要真 Redis：
     * 摘错人的代价是用户白抢一次却拿不到券，而且没有任何报错。
     * <p>脚本文本从 classpath 读，验的是打进包的那份文件，不是测试里另抄一遍的副本。
     */
    @Test
    void redisSweepRemovesOnlyMembersWhoseRushPrepareExpired() throws Exception {
        String script = LuaScriptLoader
                .load("coupon_rush_sweep_dangling_v1.lua", Long.class)
                .getScriptAsString();
        String couponId = "sweep-" + UUID.randomUUID();
        String couponKey = Constants.REDIS_KEY_RUSHING_COUPON + couponId;

        try (RedisWire redis = new RedisWire(REDIS.getHost(), REDIS.getMappedPort(6379))) {
            // live-* 还持有预占 hash（资格有效），dead-* 的 hash 已过期，只剩 SET 成员
            assertEquals("4", redis.command("SADD", couponKey,
                    "live-1", "dead-1", "live-2", "dead-2"));
            for (String userId : List.of("live-1", "live-2")) {
                redis.command("HSET",
                        Constants.REDIS_KEY_RUSHING_USERID + userId + ":coupon:" + couponId,
                        "userCouponId", "uc-" + userId);
            }

            assertEquals("2", redis.command("EVAL", script, "0",
                    couponId, "live-1", "dead-1", "live-2", "dead-2"));

            assertEquals("1", redis.command("SISMEMBER", couponKey, "live-1"),
                    "预占仍在的成员被误删，该用户的抢购资格凭空消失");
            assertEquals("1", redis.command("SISMEMBER", couponKey, "live-2"));
            assertEquals("0", redis.command("SISMEMBER", couponKey, "dead-1"));
            assertEquals("0", redis.command("SISMEMBER", couponKey, "dead-2"));
            assertEquals("2", redis.command("SCARD", couponKey));

            // 重复执行必须是 0：返回值直接进对账日志，把已摘过的再算一次会让数字虚高
            assertEquals("0", redis.command("EVAL", script, "0",
                    couponId, "live-1", "dead-1", "live-2", "dead-2"));

            // 传入根本不在 SET 里的 userId 也不该计数（srem 返回 0）
            assertEquals("0", redis.command("EVAL", script, "0", couponId, "never-joined"));

            // 预占 hash 过期后，同一个成员才变成可清理的
            redis.command("DEL", Constants.REDIS_KEY_RUSHING_USERID + "live-1:coupon:" + couponId);
            assertEquals("1", redis.command("EVAL", script, "0", couponId, "live-1"));
            assertEquals("1", redis.command("SCARD", couponKey));
        }
    }

    /**
     * RocketMQ 真实链路（可选，本机门禁）：SMARTLECT_RUN_ROCKETMQ_INTEGRATION=1 且
     * 本机 compose 的 rocketmq-proxy 已起时执行——Producer 发送 + PushConsumer 消费
     * 端到端断言。RocketMQ 5.x 三容器（namesrv/broker/proxy）无官方 Testcontainers
     * 模块，故沿用本机 broker 门禁式集成（同旧 RabbitMQ confirm 集成测试思路）。
     */
    @Test
    void rocketmqPublishesAndConsumesAnActualMessage() throws Exception {
        org.junit.jupiter.api.Assumptions.assumeTrue(
                "1".equals(System.getenv("SMARTLECT_RUN_ROCKETMQ_INTEGRATION")),
                "set SMARTLECT_RUN_ROCKETMQ_INTEGRATION=1 with local rocketmq-proxy up");
        com.smartlect.mq.RocketMqClientHolder holder = new com.smartlect.mq.RocketMqClientHolder();
        org.springframework.test.util.ReflectionTestUtils.setField(holder, "endpoints", "127.0.0.1:8081");
        org.apache.rocketmq.client.apis.ClientServiceProvider provider =
                org.apache.rocketmq.client.apis.ClientServiceProvider.loadService();
        java.util.concurrent.atomic.AtomicReference<String> received = new java.util.concurrent.atomic.AtomicReference<>();
        java.util.concurrent.CountDownLatch latch = new java.util.concurrent.CountDownLatch(1);
        org.apache.rocketmq.client.apis.consumer.PushConsumer consumer = provider.newPushConsumerBuilder()
                .setClientConfiguration(holder.configuration())
                .setConsumerGroup("G_middleware_it")
                .setSubscriptionExpressions(java.util.Map.of(
                        "smartlect-mw-it", new org.apache.rocketmq.client.apis.consumer.FilterExpression("*",
                                org.apache.rocketmq.client.apis.consumer.FilterExpressionType.TAG)))
                .setMessageListener(view -> {
                    received.set(new String(java.nio.charset.StandardCharsets.UTF_8.decode(view.getBody()).array()));
                    latch.countDown();
                    return org.apache.rocketmq.client.apis.consumer.ConsumeResult.SUCCESS;
                })
                .build();
        try {
            holder.send("smartlect-mw-it", "it", "middleware-message".getBytes(StandardCharsets.UTF_8),
                    java.util.Map.of(), null);
            assertTrue(latch.await(10, TimeUnit.SECONDS), "message not consumed in 10s");
            assertEquals("middleware-message", received.get());
        } finally {
            consumer.close();
            holder.shutdown();
        }
    }

    private static Connection mysqlConnection() throws Exception {
        return DriverManager.getConnection(
                MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
    }

    private static Connection rootConnection() throws Exception {
        return DriverManager.getConnection(
                MYSQL.getJdbcUrl(), "root", MYSQL.getPassword());
    }

    private static List<Path> findCurrentJavaMigrations() throws IOException {
        Path root = Path.of(System.getProperty("maven.multiModuleProjectDirectory", "."))
                .toAbsolutePath()
                .normalize();
        while (root != null
                && (!Files.isDirectory(root.resolve("smartlect-order"))
                || !Files.isDirectory(root.resolve("smartlect-common")))) {
            root = root.getParent();
        }
        if (root == null) {
            throw new IOException("Unable to locate the Smartlect backend root");
        }
        List<String> serviceMigrations = List.of(
                "smartlect-admin/src/main/resources/db/migration/R__current_schema.sql",
                "smartlect-cart/app/src/main/resources/db/migration/R__current_schema.sql",
                "smartlect-coupon/app/src/main/resources/db/migration/R__current_schema.sql",
                "smartlect-order/app/src/main/resources/db/migration/R__current_schema.sql",
                "smartlect-pay/app/src/main/resources/db/migration/R__current_schema.sql",
                "smartlect-product/app/src/main/resources/db/migration/R__current_schema.sql",
                "smartlect-stock/app/src/main/resources/db/migration/R__current_schema.sql",
                "smartlect-user/app/src/main/resources/db/migration/R__current_schema.sql");
        Path backendRoot = root;
        return serviceMigrations.stream()
                .map(backendRoot::resolve)
                .filter(Files::isRegularFile)
                .toList();
    }

    private static final class RedisWire implements AutoCloseable {
        private final Socket socket;
        private final InputStream input;
        private final OutputStream output;

        private RedisWire(String host, int port) throws IOException {
            socket = new Socket();
            socket.connect(new InetSocketAddress(host, port), 3_000);
            input = new BufferedInputStream(socket.getInputStream());
            output = new BufferedOutputStream(socket.getOutputStream());
        }

        private String command(String... args) throws IOException {
            output.write(('*' + String.valueOf(args.length) + "\r\n").getBytes(StandardCharsets.UTF_8));
            for (String arg : args) {
                byte[] bytes = arg.getBytes(StandardCharsets.UTF_8);
                output.write(('$' + String.valueOf(bytes.length) + "\r\n").getBytes(StandardCharsets.UTF_8));
                output.write(bytes);
                output.write("\r\n".getBytes(StandardCharsets.UTF_8));
            }
            output.flush();
            return readReply(input);
        }

        private static String readReply(InputStream input) throws IOException {
            int prefix = input.read();
            if (prefix == -1) {
                throw new IOException("Redis closed the connection");
            }
            String line = readLine(input);
            return switch (prefix) {
                case '+' -> line;
                case ':' -> line;
                case '-' -> throw new IOException(line);
                case '$' -> {
                    int length = Integer.parseInt(line);
                    if (length < 0) {
                        yield "(nil)";
                    }
                    byte[] body = input.readNBytes(length);
                    input.read();
                    input.read();
                    yield new String(body, StandardCharsets.UTF_8);
                }
                default -> throw new IOException("Unsupported Redis response: " + (char) prefix);
            };
        }

        private static String readLine(InputStream input) throws IOException {
            ByteArrayOutputStream line = new ByteArrayOutputStream();
            int current;
            int previous = -1;
            while ((current = input.read()) != -1) {
                if (previous == '\r' && current == '\n') {
                    byte[] bytes = line.toByteArray();
                    return new String(bytes, 0, bytes.length - 1, StandardCharsets.UTF_8);
                }
                line.write(current);
                previous = current;
            }
            throw new IOException("Redis response line ended unexpectedly");
        }

        @Override
        public void close() throws IOException {
            socket.close();
        }
    }
}
