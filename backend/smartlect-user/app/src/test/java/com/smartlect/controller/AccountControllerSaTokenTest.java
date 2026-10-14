package com.smartlect.controller;

import cn.dev33.satoken.SaManager;
import cn.dev33.satoken.config.SaCookieConfig;
import cn.dev33.satoken.config.SaTokenConfig;
import cn.dev33.satoken.spring.SaTokenContextForSpringInJakartaServlet;
import cn.dev33.satoken.stp.StpUtil;
import com.smartlect.biz.impl.AliEmailServiceImpl;
import com.smartlect.biz.impl.UserInfoServiceImpl;
import com.smartlect.component.RedisComponent;
import com.smartlect.component.UserTempBanService;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.po.UserInfo;
import com.smartlect.service.PasswordService;
import com.smartlect.service.SlideCaptchaVerifier;
import com.smartlect.utils.AuthCookieHelper;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.hamcrest.Matchers.nullValue;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 登录/登出/autoLogin 的 Sa-Token 行为（ADR-0011 Step 1）。
 * standalone MockMvc + Sa-Token 内存 dao：MVC 上下文经 RequestContextHolder 生效，
 * 断言 Cookie 下发、会话建立与登出后的会话清除。
 */
class AccountControllerSaTokenTest {

    private static final String USER_ID = "u-satoken-1";

    private final RedisComponent redisComponent = mock(RedisComponent.class);
    private final UserInfoServiceImpl userInfoService = mock(UserInfoServiceImpl.class);
    private final AliEmailServiceImpl aliEmailService = mock(AliEmailServiceImpl.class);
    private final StringRedisTemplate stringRedisTemplate = mock(StringRedisTemplate.class);
    private final UserTempBanService userTempBanService = mock(UserTempBanService.class);
    private final SlideCaptchaVerifier slideCaptchaVerifier = mock(SlideCaptchaVerifier.class);
    private final PasswordService passwordService = mock(PasswordService.class);

    private MockMvc mvc;
    private UserInfo enabledUser;

    @BeforeAll
    static void initSaToken() {
        SaTokenConfig config = new SaTokenConfig();
        config.setTokenName("token");
        config.setTimeout(86400);
        config.setIsConcurrent(true);
        config.setIsShare(false);
        config.setCookie(new SaCookieConfig().setPath("/").setHttpOnly(true).setSameSite("Lax"));
        SaManager.setConfig(config);
        SaManager.setSaTokenContext(new SaTokenContextForSpringInJakartaServlet());
    }

    @AfterAll
    static void resetSaToken() {
        SaManager.setSaTokenContext(null);
        SaManager.setConfig(null);
    }

    @BeforeEach
    void setUp() {
        AccountController controller = new AccountController();
        org.springframework.test.util.ReflectionTestUtils.setField(controller, "userLoginLockService",
                org.mockito.Mockito.mock(com.smartlect.component.UserLoginLockService.class));
        AuthCookieHelper authCookieHelper = new AuthCookieHelper();
        ReflectionTestUtils.setField(controller, "redisComponent", redisComponent);
        ReflectionTestUtils.setField(controller, "userInfoService", userInfoService);
        ReflectionTestUtils.setField(controller, "aliEmailServiceImpl", aliEmailService);
        ReflectionTestUtils.setField(controller, "stringRedisTemplate", stringRedisTemplate);
        ReflectionTestUtils.setField(controller, "userTempBanService", userTempBanService);
        ReflectionTestUtils.setField(controller, "slideCaptchaVerifier", slideCaptchaVerifier);
        ReflectionTestUtils.setField(controller, "authCookieHelper", authCookieHelper);
        ReflectionTestUtils.setField(controller, "passwordService", passwordService);
        mvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new AGlobalExceptionHandlerController())
                .build();

        enabledUser = new UserInfo();
        enabledUser.setUserId(USER_ID);
        enabledUser.setEmail("satoken@x.test");
        enabledUser.setNickName("satoken-nick");
        enabledUser.setAvatar("satoken.png");
        enabledUser.setPassword("bcrypt-hash");
        enabledUser.setStatus(1);
    }

    private String loginAndGetToken() throws Exception {
        when(redisComponent.getCheckCode("captcha-key")).thenReturn("1234");
        when(userInfoService.getUserInfoByEmail("satoken@x.test")).thenReturn(enabledUser);
        when(passwordService.matches("Passw0rd", "bcrypt-hash")).thenReturn(true);
        when(passwordService.isBcrypt("bcrypt-hash")).thenReturn(true);

        MvcResult result = mvc.perform(post("/account/login")
                        .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                        .param("email", "satoken@x.test")
                        .param("password", "Passw0rd")
                        .param("checkCodeKey", "captcha-key")
                        .param("checkCode", "1234"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("success"))
                .andExpect(jsonPath("$.data.userId").value(USER_ID))
                .andExpect(jsonPath("$.data.token").value(nullValue()))
                .andReturn();

        String setCookie = result.getResponse().getHeader("Set-Cookie");
        assertTrue(setCookie != null && setCookie.startsWith("token="), "应通过 Sa-Token 下发 token Cookie: " + setCookie);
        assertTrue(setCookie.contains("HttpOnly") && setCookie.contains("SameSite=Lax"), setCookie);
        String token = setCookie.substring("token=".length(), setCookie.indexOf(';'));
        assertEquals(USER_ID, StpUtil.getLoginIdByToken(token), "登录后应建立 Sa-Token 会话");
        return token;
    }

    @Test
    void loginIssuesSaTokenSessionCookieThenAutoLoginReadsIt() throws Exception {
        String token = loginAndGetToken();

        when(userInfoService.getUserInfoByUserId(USER_ID)).thenReturn(enabledUser);
        mvc.perform(get("/account/autoLogin").cookie(new Cookie("token", token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.userId").value(USER_ID))
                .andExpect(jsonPath("$.data.nickName").value("satoken-nick"))
                .andExpect(jsonPath("$.data.token").value(nullValue()));

        TokenUserInfoDTO stored = (TokenUserInfoDTO) StpUtil.getSessionByLoginId(USER_ID).get("userInfo");
        assertEquals("satoken@x.test", stored.getEmail());
    }

    @Test
    void autoLoginWithoutTokenOrWithUnknownTokenReturnsNullData() throws Exception {
        mvc.perform(get("/account/autoLogin"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").value(nullValue()));
        mvc.perform(get("/account/autoLogin").cookie(new Cookie("token", "never-issued")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").value(nullValue()));
    }

    @Test
    void disabledUserSessionIsRejectedByAutoLogin() throws Exception {
        String token = loginAndGetToken();
        enabledUser.setStatus(0);
        when(userInfoService.getUserInfoByUserId(USER_ID)).thenReturn(enabledUser);

        mvc.perform(get("/account/autoLogin").cookie(new Cookie("token", token)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").value(nullValue()));
    }

    @Test
    void logoutClearsSaTokenSessionAndCookieEvenForUnknownTokens() throws Exception {
        String token = loginAndGetToken();

        MvcResult result = mvc.perform(post("/account/logout").cookie(new Cookie("token", token)))
                .andExpect(status().isOk())
                .andReturn();
        assertNull(StpUtil.getLoginIdByToken(token), "登出后 Sa-Token 会话应被删除");
        String setCookie = result.getResponse().getHeader("Set-Cookie");
        assertTrue(setCookie != null && setCookie.contains("Max-Age=0"), setCookie);

        // 未知 token 登出不抛错且仍清理 Cookie
        MvcResult stranger = mvc.perform(post("/account/logout").cookie(new Cookie("token", "stranger-token")))
                .andExpect(status().isOk())
                .andReturn();
        assertTrue(stranger.getResponse().getHeader("Set-Cookie").contains("Max-Age=0"));
    }

    @Test
    void wrongCaptchaNeverIssuesCookieOrSession() throws Exception {
        when(redisComponent.getCheckCode("captcha-key")).thenReturn("1234");
        when(userInfoService.getUserInfoByEmail("satoken@x.test")).thenReturn(enabledUser);
        when(passwordService.matches("Passw0rd", "bcrypt-hash")).thenReturn(true);
        when(passwordService.isBcrypt("bcrypt-hash")).thenReturn(true);

        MvcResult result = mvc.perform(post("/account/login")
                        .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                        .param("email", "satoken@x.test")
                        .param("password", "Passw0rd")
                        .param("checkCodeKey", "captcha-key")
                        .param("checkCode", "0000"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("error"))
                .andReturn();
        assertNull(result.getResponse().getHeader("Set-Cookie"), "验证码错误时不得下发会话 Cookie");
    }
}
