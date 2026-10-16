package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.entity.dto.*;
import com.smartlect.redis.RedisUtils;
import com.smartlect.utils.JsonUtils;
import com.smartlect.utils.StringTools;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import lombok.extern.slf4j.Slf4j;
import com.smartlect.exception.BusinessException;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;

@Component("redisComponent")
@Slf4j
public class RedisComponent {

    @Resource
    private RedisTemplate redisTemplate;
    @Resource
    private RedisUtils redisUtils;
    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private AppConfig appConfig;

    @Resource
    private ObjectMapper objectMapper;

    public void saveCategory2Redis(List<?> list) {
        redisUtils.set(Constants.REDIS_KEY_CATEGORY_LIST, list);
    }

    public String saveCheckCode(String code){
        // 1.对code生成UUID
        String codeKey = UUID.randomUUID().toString();
        // 2.将code和UUID保存到Redis中，设置5分钟过期时间
        redisUtils.setex(Constants.REDIS_KEY_CHECK_CODE + codeKey, code, Constants.LENGTH_5 * 60);
        // 3.返回UUID
        return codeKey;
    }

    public String getCheckCode(@NotEmpty String checkCodeKey) {
        return (String) redisTemplate.opsForValue().get(Constants.REDIS_KEY_CHECK_CODE + checkCodeKey);
    }

    public void cleanCheckCode(@NotEmpty String checkCodeKey) {
        redisTemplate.delete(Constants.REDIS_KEY_CHECK_CODE + checkCodeKey);
    }

    // ===== 管理端 Sa-Token 会话（ADR-0011 Step 2）=====
    // common 不引 Sa-Token SDK，按 Sa-Token 1.39 键布局裸读写：
    //   {tokenName}:{loginType}:token:{token}     -> adminId 裸字符串
    //   {tokenName}:{loginType}:session:{adminId} -> Account-Session JSON，dataMap.adminPrincipal 即 AdminPrincipalDTO
    // 管理端 loginType=admin、tokenName=adminToken（StpAdminLogic），实测键为 adminToken:admin:*；
    // 2026-10-04 修正：此前误写 login 段（adminToken:login:*）导致跨服务内省永远 401。
    private static final String SA_TOKEN_ADMIN_TOKEN_PREFIX = "adminToken:admin:token:";
    private static final String SA_TOKEN_ADMIN_SESSION_PREFIX = "adminToken:admin:session:";

    public AdminPrincipalDTO getAdminPrincipal(String token) {
        if (StringTools.isEmpty(token)) {
            return null;
        }
        String adminId = stringRedisTemplate.opsForValue().get(SA_TOKEN_ADMIN_TOKEN_PREFIX + token);
        if (StringTools.isEmpty(adminId)) {
            return null;
        }
        // 从 Sa-Token session JSON 的 dataMap 提取 adminPrincipal。
        // Sa-Token redis-jackson 写入的是带 @class 元数据的纯 JSON 字符串；本类的
        // redisTemplate 值序列化器会按 @class 还原成 SaSession 对象（不是 Map），
        // 所以必须走 stringRedisTemplate 取原始 JSON 再解析，不能依赖模板反序列化。
        String sessionRaw = stringRedisTemplate.opsForValue().get(SA_TOKEN_ADMIN_SESSION_PREFIX + adminId);
        if (StringTools.isEmpty(sessionRaw)) {
            return null;
        }
        Map<?, ?> session;
        try {
            session = JsonUtils.mapper().readValue(sessionRaw, Map.class);
        } catch (Exception e) {
            return null;
        }
        Object dataMap = session.get("dataMap");
        if (!(dataMap instanceof Map<?, ?> map)) {
            return null;
        }
        AdminPrincipalDTO principal = parseAdminPrincipal(map.get("adminPrincipal"));
        if (principal == null || StringTools.isEmpty(principal.getAdminId())
                || principal.getSessionVersion() == null) {
            return null;
        }
        // 版本检查（角色变更时由 invalidateAdminSessions 升版踢人）。
        // 该键只由 invalidateAdminSessions 写入：键缺失 = 全新部署从未升版踢人，
        // 放行；键存在且不匹配才拒绝——否则全新环境管理端内省永远 401。
        String currentVersion = stringRedisTemplate.opsForValue().get(
                Constants.REDIS_KEY_ADMIN_SESSION_VERSION + principal.getAdminId());
        if (currentVersion != null && !String.valueOf(principal.getSessionVersion()).equals(currentVersion)) {
            stringRedisTemplate.delete(SA_TOKEN_ADMIN_TOKEN_PREFIX + token);
            return null;
        }
        return principal;
    }

    public void invalidateAdminSessions(String adminId, long sessionVersion) {
        if (StringTools.isEmpty(adminId)) {
            return;
        }
        // 升版踢人：token 侧由版本检查在下次 getAdminPrincipal 时失效，
        // 同时清掉该 admin 的 Sa-Token session（即时踢出，不等下次访问）。
        stringRedisTemplate.delete(SA_TOKEN_ADMIN_SESSION_PREFIX + adminId);
        stringRedisTemplate.opsForValue().set(
                Constants.REDIS_KEY_ADMIN_SESSION_VERSION + adminId,
                String.valueOf(sessionVersion));
    }

    private AdminPrincipalDTO parseAdminPrincipal(Object value) {
        if (value instanceof AdminPrincipalDTO principal) {
            return principal;
        }
        if (!(value instanceof Map<?, ?> map)) {
            // String-only sessions are deliberately rejected after the RBAC migration.
            return null;
        }
        Object adminId = map.get("adminId");
        Object account = map.get("account");
        Object displayName = map.get("displayName");
        Object version = map.get("sessionVersion");
        if (adminId == null || version == null) {
            return null;
        }
        AdminPrincipalDTO principal = new AdminPrincipalDTO();
        principal.setAdminId(String.valueOf(adminId));
        principal.setAccount(account == null ? null : String.valueOf(account));
        principal.setDisplayName(displayName == null ? null : String.valueOf(displayName));
        try {
            principal.setSessionVersion(Long.parseLong(String.valueOf(version)));
        } catch (NumberFormatException e) {
            return null;
        }
        principal.setRoles(toStringSet(map.get("roles")));
        principal.setPermissions(toStringSet(map.get("permissions")));
        return principal;
    }

    private Set<String> toStringSet(Object value) {
        if (!(value instanceof Collection<?> collection)) {
            return Collections.emptySet();
        }
        Set<String> values = new LinkedHashSet<>();
        for (Object item : collection) {
            if (item != null && !StringTools.isEmpty(String.valueOf(item))) {
                values.add(String.valueOf(item));
            }
        }
        return values;
    }

    // ===== 用户端 web 会话（Sa-Token 键布局，ADR-0011 Step 1）=====
    // 登录态由 user 服务 StpUtil 写入；common 不依赖 Sa-Token SDK，按下述格式裸读写：
    //   token:login:token:{token}     -> loginId 裸字符串
    //   token:login:session:{loginId} -> Account-Session JSON，dataMap.userInfo 即 TokenUserInfoDTO

    // 根据token获取TokenUserInfoDTO
    public TokenUserInfoDTO getTokenUserInfo(String token) {
        String loginId = getUserIdByToken(token);
        if (loginId == null) {
            return null;
        }
        String sessionJson = stringRedisTemplate.opsForValue()
                .get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + loginId);
        TokenUserInfoDTO tokenUserInfoDTO = parseSessionUserInfo(sessionJson);
        if (tokenUserInfoDTO == null) {
            return null;
        }
        tokenUserInfoDTO.setToken(token);
        return tokenUserInfoDTO;
    }

    // 根据userId获取TokenUserInfoDTO（取账号会话里登记的任一有效token）
    public TokenUserInfoDTO getTokenUserInfoByUserId(String userId) {
        String sessionJson = stringRedisTemplate.opsForValue()
                .get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + userId);
        TokenUserInfoDTO tokenUserInfoDTO = parseSessionUserInfo(sessionJson);
        if (tokenUserInfoDTO != null) {
            tokenUserInfoDTO.setToken(parseFirstTokenSign(sessionJson));
        }
        return tokenUserInfoDTO;
    }

    public String getUserIdByToken(String token) {
        if (StringTools.isEmpty(token)) {
            return null;
        }
        String loginId = stringRedisTemplate.opsForValue().get(Constants.REDIS_KEY_TOKEN_WEB + token);
        return StringTools.isEmpty(loginId) ? null : loginId;
    }

    // 修改个人资料后无需重新登录：资料字段以库为准（autoLogin 每次用库值覆盖会话），
    // 这里只把 token 与账号会话续期一天，等价旧实现的"改资料不掉线"。
    public void updateUser(String userId) {
        TokenUserInfoDTO tokenUserInfoDTO = getTokenUserInfoByUserId(userId);
        if (tokenUserInfoDTO == null || StringTools.isEmpty(tokenUserInfoDTO.getToken())) {
            return;
        }
        stringRedisTemplate.expire(Constants.REDIS_KEY_TOKEN_WEB + tokenUserInfoDTO.getToken(),
                Duration.ofSeconds(Constants.REDIS_KEY_EXPIRES_DAY));
        stringRedisTemplate.expire(Constants.REDIS_KEY_TOKEN_WEB_SESSION + userId,
                Duration.ofSeconds(Constants.REDIS_KEY_EXPIRES_DAY));
    }

    // 踢掉 userId 的全部登录设备（Sa-Token 账号会话的 tokenSignList 覆盖所有在线 token）
    public void cleanAllToken(@NotNull String userId) {
        String sessionKey = Constants.REDIS_KEY_TOKEN_WEB_SESSION + userId;
        String sessionJson = stringRedisTemplate.opsForValue().get(sessionKey);
        if (StringTools.isEmpty(sessionJson)) {
            return;
        }
        for (String token : parseAllTokenSigns(sessionJson)) {
            stringRedisTemplate.delete(Constants.REDIS_KEY_TOKEN_WEB + token);
        }
        stringRedisTemplate.delete(sessionKey);
    }

    private TokenUserInfoDTO parseSessionUserInfo(String sessionJson) {
        if (StringTools.isEmpty(sessionJson)) {
            return null;
        }
        try {
            JsonNode userInfo = objectMapper.readTree(sessionJson).path("dataMap").path("userInfo");
            if (!userInfo.isObject() || StringTools.isEmpty(userInfo.path("userId").asText(null))) {
                return null;
            }
            TokenUserInfoDTO dto = new TokenUserInfoDTO();
            dto.setUserId(userInfo.path("userId").asText());
            dto.setEmail(textOrNull(userInfo, "email"));
            dto.setNickName(textOrNull(userInfo, "nickName"));
            dto.setAvatar(textOrNull(userInfo, "avatar"));
            JsonNode trial = userInfo.path("trial");
            dto.setTrial(trial.isBoolean() ? trial.asBoolean() : null);
            return dto;
        } catch (Exception e) {
            log.warn("解析 Sa-Token 账号会话失败：{}", e.getMessage());
            return null;
        }
    }

    private String parseFirstTokenSign(String sessionJson) {
        JsonNode signs = tokenSignArray(sessionJson);
        return signs == null || signs.isEmpty() ? null : signs.get(0).path("value").asText(null);
    }

    private List<String> parseAllTokenSigns(String sessionJson) {
        JsonNode signs = tokenSignArray(sessionJson);
        if (signs == null) {
            return Collections.emptyList();
        }
        List<String> tokens = new ArrayList<>();
        for (JsonNode sign : signs) {
            String token = sign.path("value").asText(null);
            if (!StringTools.isEmpty(token)) {
                tokens.add(token);
            }
        }
        return tokens;
    }

    // tokenSignList 由 GenericJackson2JsonRedisSerializer 序列化为 ["java.util.Vector",[{...}]]
    private JsonNode tokenSignArray(String sessionJson) {
        if (StringTools.isEmpty(sessionJson)) {
            return null;
        }
        try {
            JsonNode list = objectMapper.readTree(sessionJson).path("tokenSignList");
            if (list.isArray() && list.size() == 2 && list.get(0).isTextual()) {
                list = list.get(1);
            }
            return list.isArray() ? list : null;
        } catch (Exception e) {
            // ADR-0022：解析失败此前静默 null（故障不可观测），升级为 warn 留痕
            log.warn("解析 Sa-Token 账号会话失败：{}", e.getMessage());
            return null;
        }
    }

    private String textOrNull(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.asText();
    }

    public void saveLogistics(LogisticsSendDTO logisticsSendDTO) {
        redisUtils.set(Constants.REDIS_KEY_SETTING_LOGISTICS, logisticsSendDTO);
    }

    public LogisticsSendDTO getLogisticsInfo() {
        LogisticsSendDTO current = (LogisticsSendDTO) redisUtils.get(Constants.REDIS_KEY_SETTING_LOGISTICS);
        if (current != null && !StringTools.isEmpty(current.getSenderName())) {
            return current;
        }
        LogisticsSendDTO seeded = new LogisticsSendDTO();
        seeded.setSenderName("智选商城");
        seeded.setSenderPhone("400-000-0000");
        seeded.setSenderAddress("演示仓（作品集默认发货地址）");
        redisUtils.set(Constants.REDIS_KEY_SETTING_LOGISTICS, seeded);
        return seeded;
    }

    public void saveUserLocationCoords(String userId, UserLocationCoordsDTO coords) {
        if (StringTools.isEmpty(userId) || coords == null) {
            return;
        }
        redisUtils.setex(Constants.REDIS_KEY_USER_LOCATION + userId, coords, appConfig.getUserLocationExpireDay() * 24L * 3600);
    }

    // 支付单生命周期的锁与一次性标记搬到 PayOrderRedisComponent。
    // 抢购预占（库存计数 + 参与者 SET + 预占 hash 的联动 Lua）搬到 CouponRushRedisComponent。

    public boolean setIfAbsent(String key, String value, long timeout, TimeUnit unit) {
        Boolean ok = stringRedisTemplate.opsForValue().setIfAbsent(key, value, timeout, unit);
        return Boolean.TRUE.equals(ok);
    }

    // 邮件验证码
    public void saveEmailCode(String email, String code){
        // 将email和code保存到Redis中，设置5分钟过期时间
        redisUtils.setex(Constants.REDIS_KEY_EMAIL_CODE + email, code, Constants.LENGTH_5 * 60);
    }

    // 获取邮件验证码
    public String getEmailCode(@NotEmpty String email) {
        return (String) redisTemplate.opsForValue().get(Constants.REDIS_KEY_EMAIL_CODE + email);
    }

    // 清理邮件验证码
    public void cleanEmailCode(@NotEmpty String email) {
        redisTemplate.delete(Constants.REDIS_KEY_EMAIL_CODE + email);
    }

    /**
     * 校验邮件验证码：失败累计，超过 {@code maxAttempts} 次即作废验证码。
     *
     * <p>6 位数字空间 10^6，若不限次数，5 分钟有效期内可被穷举（2026-10-16 审计）。
     * 计数器随验证码同周期过期，成功后一并清理。</p>
     */
    public void verifyEmailCode(@NotEmpty String email, String provided, int maxAttempts) {
        String expected = getEmailCode(email);
        if (expected == null) {
            throw new BusinessException("验证码已过期，请重新获取！");
        }
        if (expected.equals(provided)) {
            cleanEmailCode(email);
            cleanEmailCodeAttempts(email);
            return;
        }
        long attempts = increaseEmailCodeAttempts(email);
        if (attempts >= maxAttempts) {
            // 作废验证码，逼迫重新获取（同时把累计窗口收敛到这一次验证码的生命周期内）
            cleanEmailCode(email);
            cleanEmailCodeAttempts(email);
            throw new BusinessException("验证码错误次数过多，请重新获取验证码");
        }
        throw new BusinessException("验证码错误！");
    }

    private long increaseEmailCodeAttempts(String email) {
        String key = Constants.REDIS_KEY_EMAIL_CODE_ATTEMPTS + email;
        Long attempts = redisTemplate.opsForValue().increment(key);
        redisTemplate.expire(key, Constants.LENGTH_5 * 60, java.util.concurrent.TimeUnit.SECONDS);
        return attempts == null ? 1L : attempts;
    }

    private void cleanEmailCodeAttempts(String email) {
        redisTemplate.delete(Constants.REDIS_KEY_EMAIL_CODE_ATTEMPTS + email);
    }
}
