package com.smartlect.controller;

import com.smartlect.annotation.RateLimit;
import com.smartlect.component.RedisComponent;
import com.smartlect.component.UserTempBanService;
import com.smartlect.constants.Constants;
import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.enums.DateTimePatternEnum;
import com.smartlect.api.enums.UserSexEnum;
import com.smartlect.api.enums.UserStatusEnum;
import com.smartlect.entity.po.UserInfo;
import com.smartlect.entity.query.UserInfoQuery;
import com.smartlect.entity.vo.CheckCodeVO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.api.vo.UserVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.biz.EmailService;
import com.smartlect.biz.impl.AliEmailServiceImpl;
import com.smartlect.biz.impl.UserInfoServiceImpl;
import com.smartlect.service.SlideCaptchaVerifier;
import com.smartlect.utils.AuthCookieHelper;
import com.smartlect.utils.CheckCodeGenerator;
import com.smartlect.utils.DateUtil;
import com.smartlect.utils.StringTools;
import com.smartlect.service.PasswordService;
import cn.dev33.satoken.stp.StpUtil;
import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.constraints.*;
import org.springframework.beans.BeanUtils;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.Date;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.TimeUnit;
import cn.dev33.satoken.annotation.SaCheckLogin;

@RequestMapping("/account")
@RestController
@Validated
public class AccountController extends ABaseController{

    @Resource
    private RedisComponent redisComponent;

    @Resource
    private UserInfoServiceImpl userInfoService;

    @Resource
    private AliEmailServiceImpl aliEmailServiceImpl;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Resource
    private UserTempBanService userTempBanService;

    @Resource
    private SlideCaptchaVerifier slideCaptchaVerifier;

    @Resource
    private AuthCookieHelper authCookieHelper;

    @Resource
    private PasswordService passwordService;
    @Resource
    private com.smartlect.component.UserLoginLockService userLoginLockService;

    private UserInfo refreshDisabledAccount(UserInfo userInfo) {
        Long unbanAt = userTempBanService.getUnbanAtMs(userInfo.getUserId());
        if (unbanAt != null) {
            Map<String, Object> data = new HashMap<>();
            data.put("errorType", "ACCOUNT_TEMP_BANNED");
            data.put("unbanAt", unbanAt);
            throw new BusinessException(600, userTempBanService.buildTempBanMessage(unbanAt), data);
        }
        UserInfo refreshed = userInfoService.getUserInfoByUserId(userInfo.getUserId());
        if (refreshed != null
                && UserStatusEnum.ENABLE.getStatus().equals(refreshed.getStatus())) {
            return refreshed;
        }
        throw new BusinessException("账号被禁用！");
    }

    // 自动登录，检验当前token是否有效
    @GetMapping("/autoLogin")
    public ResponseVO autoLogin(){
        // Sa-Token 从 Cookie/header "token" 读取并校验，校验通过会自动续期 token 与账号会话
        if (!StpUtil.isLogin()) {
            return getSuccessResponseVO(null);
        }
        TokenUserInfoDTO validUserInfo = (TokenUserInfoDTO) StpUtil.getSession().get("userInfo");
        if (validUserInfo == null) {
            return getSuccessResponseVO(null);
        }
        // 判断当前用户是否被封禁：status=0为封禁
        UserInfo userInfo = userInfoService.getUserInfoByUserId(validUserInfo.getUserId());
        if (userInfo == null
                || Objects.equals(userInfo.getStatus(), UserStatusEnum.DISABLE.getStatus())){
            return getSuccessResponseVO(null);
        }
        validUserInfo.setEmail(userInfo.getEmail());
        validUserInfo.setNickName(userInfo.getNickName());
        validUserInfo.setAvatar(userInfo.getAvatar());
        validUserInfo.setTrial(TrialIdentities.isTrialUser(userInfo.getUserId(), userInfo.getEmail()));
        StpUtil.getSession().set("userInfo", validUserInfo);
        HttpServletRequest request = currentRequest();
        HttpServletResponse response = currentResponse();
        authCookieHelper.writeWebTokenCookie(request, response, StpUtil.getTokenValue());
        validUserInfo.setToken(null);
        return getSuccessResponseVO(validUserInfo);
    }

    // 获取验证码
    // 4 位数字图片验证码可被低成本 OCR：不限流时等于给登录爆破发免费门票（IP 取 IpUtils 的可信值）
    @GetMapping("/checkCode")
    @RateLimit(limitType = RateLimit.LimitType.IP, windowSeconds = 60, maxCount = 30,
            message = "获取验证码过于频繁，请稍后再试")
    public ResponseVO checkCode(){
        CheckCodeVO checkCodeVO = CheckCodeGenerator.generate(redisComponent);
        return getSuccessResponseVO(checkCodeVO);
    }

    // 注册
    // 邮箱email，昵称nickName，密码password，验证码checkCode，验证码key checkCodeKey
    @PostMapping("/register")
    public ResponseVO register(@NotEmpty @Email @Size(max = 150) String email,
                               @NotEmpty @Size(max = 20) String nickName,
                               @NotEmpty @Pattern(regexp = Constants.REGEX_PASSWORD) String registerPassword,
                               @NotEmpty String checkCode,
                               String checkCodeKey){
            if (!StringTools.isEmpty(checkCodeKey)) {
                if (!checkCode.equalsIgnoreCase(redisComponent.getCheckCode(checkCodeKey))){
                    throw new BusinessException("验证码错误！");
                }
                redisComponent.cleanCheckCode(checkCodeKey);
                userInfoService.registerVerified(email, nickName, registerPassword);
            } else {
                userInfoService.register(email, nickName, registerPassword, checkCode);
            }
            return getSuccessResponseVO(null);
    }

    // 登录
    // 邮箱email，密码password，验证码checkCode，验证码key checkCodeKey
    @PostMapping("/login")
    public ResponseVO login(@NotEmpty @Email @Size(max = 150) String email,
                            @NotEmpty String password,
                            String checkCodeKey,
                            String checkCode
                            ){
        String clientIp = getClientIp();
        userLoginLockService.ensureNotLocked(email, clientIp);
        try {
            if (!TrialIdentities.skipLoginCaptcha(email)
                    && (StringTools.isEmpty(checkCode)
                    || StringTools.isEmpty(checkCodeKey)
                    || !checkCode.equalsIgnoreCase(redisComponent.getCheckCode(checkCodeKey)))) {
                throw new BusinessException("验证码错误！");
            }
            // 检查账号或密码
            // 查询UserInfo
            UserInfo userInfo = userInfoService.getUserInfoByEmail(email);
            if (userInfo == null || !passwordService.matches(password, userInfo.getPassword())){
                userLoginLockService.recordFailure(email, clientIp);
                throw new BusinessException("账号或密码错误！");
            }
            userLoginLockService.clearFailures(email, clientIp);
            if (!passwordService.isBcrypt(userInfo.getPassword())) {
                UserInfo upgrade = new UserInfo();
                upgrade.setPassword(passwordService.encode(password));
                UserInfoQuery upgradeQuery = new UserInfoQuery();
                upgradeQuery.setUserId(userInfo.getUserId());
                userInfoService.updateByParam(upgrade, upgradeQuery);
            }
            if (UserStatusEnum.DISABLE.getStatus().equals(userInfo.getStatus())){
                userInfo = refreshDisabledAccount(userInfo);
            }
            // 登录成功，返回userId,nickName,avatar；token 写入 Sa-Token 会话并由其下发 Cookie
            TokenUserInfoDTO tokenUserInfoDTO = new TokenUserInfoDTO();
            tokenUserInfoDTO.setUserId(userInfo.getUserId());
            tokenUserInfoDTO.setEmail(userInfo.getEmail());
            tokenUserInfoDTO.setNickName(userInfo.getNickName());
            tokenUserInfoDTO.setAvatar(userInfo.getAvatar());
            tokenUserInfoDTO.setTrial(TrialIdentities.isTrialUser(userInfo.getUserId(), userInfo.getEmail()));
            StpUtil.login(userInfo.getUserId());
            StpUtil.getSession().set("userInfo", tokenUserInfoDTO);
            tokenUserInfoDTO.setToken(null);
            // 更新最近登录时间和ip
            Date now = DateUtil.parse(DateUtil.getTimeOnParttern(0, DateTimePatternEnum.YYYY_MM_DD_HH_MM_SS.getPattern()), DateTimePatternEnum.YYYY_MM_DD_HH_MM_SS.getPattern());
            String ip = getClientIp();
            userInfo.setLastLoginTime(now);
            userInfo.setLastLoginIp(ip);
            UserInfoQuery userInfoQuery = new UserInfoQuery();
            userInfoQuery.setUserId(userInfo.getUserId());
            userInfoService.updateByParam(userInfo, userInfoQuery);
            return getSuccessResponseVO(tokenUserInfoDTO);
        }finally {
            if (!StringTools.isEmpty(checkCodeKey)) {
                redisComponent.cleanCheckCode(checkCodeKey);
            }
        }
    }

    // 退出登录（不要求 Redis 中 token 仍有效，始终清除 Cookie）
    @PostMapping("/logout")
    public ResponseVO logout(){
        HttpServletRequest request = currentRequest();
        HttpServletResponse response = currentResponse();
        String token = authCookieHelper.resolveWebToken(request);
        if (!StringTools.isEmpty(token)){
            // StpUtil.logout(Object) 是按 loginId 登出；按 token 登出必须用 logoutByTokenValue
            StpUtil.logoutByTokenValue(token);
        }
        authCookieHelper.clearWebTokenCookie(request, response);
        return getSuccessResponseVO(null);
    }

    // 获取个人信息
    @GetMapping("/getUserInfo")
    @SaCheckLogin
    public ResponseVO getUserInfo(){
        String userId = getTokenUserInfo().getUserId();
        UserInfo userInfo = userInfoService.getUserInfoByUserId(userId);
        UserVO userVO = new UserVO();
        BeanUtils.copyProperties(userInfo, userVO);
        userVO.setTrial(TrialIdentities.isTrialUser(userInfo.getUserId(), userInfo.getEmail()));
        return getSuccessResponseVO(userVO);
    }

    // 修改个人信息
    @PostMapping("/updateUserInfo")
    @SaCheckLogin
    public ResponseVO updateUserInfo(String avatar,@NotEmpty String nickName,@NotNull Integer sex){
        String userId = getTokenUserInfo().getUserId();
        userInfoService.updateUserInfo(userId, avatar, nickName, sex);
        return getSuccessResponseVO(null);
    }

    // 修改密码
    @PostMapping("/updatePassword")
    @SaCheckLogin
    public ResponseVO updatePassword(@NotEmpty String oldPassword,@NotEmpty String password){
        String userId = getTokenUserInfo().getUserId();
        userInfoService.updatePassword(userId, oldPassword, password);
        return getSuccessResponseVO(null);
    }

    private String getClientIp() {
        // 信任模型见 IpUtils：先信 nginx 写的 X-Real-IP，XFF 取最后一跳并做格式校验。
        // 取 XFF 第一段会允许客户端伪造 IP，绕过登录锁定与 IP 限流（2026-10-16 审计）。
        return com.smartlect.utils.IpUtils.resolveClientIp(currentRequest());
    }

    private HttpServletRequest currentRequest() {
        return ((ServletRequestAttributes) RequestContextHolder.getRequestAttributes()).getRequest();
    }

    private HttpServletResponse currentResponse() {
        return ((ServletRequestAttributes) RequestContextHolder.getRequestAttributes()).getResponse();
    }

    // 获取邮件验证码
    @PostMapping("/getEmailCode")
    @RateLimit(limitType = RateLimit.LimitType.IP, windowSeconds = 20, maxCount = 1, message = "获取验证码过于频繁，请稍后再试")
    public ResponseVO getEmailCode(@NotEmpty @Email @Size(max = 150) String email,
                                   @NotEmpty String captchaVerification){
        if (TrialIdentities.isPublishedDemoEmail(email)) {
            throw new BusinessException(TrialIdentities.isShopperEmail(email)
                    ? TrialIdentities.SHOPPER_DENIED : TrialIdentities.USER_DENIED);
        }
        slideCaptchaVerifier.verify(captchaVerification);
        // 60秒内只能获取一次
        String existingCode = redisComponent.getEmailCode(email);
        if (existingCode != null){
            // 获取剩余时间，单位为毫秒
            Long expire = stringRedisTemplate.getExpire(Constants.REDIS_KEY_EMAIL_CODE + email, TimeUnit.MILLISECONDS);
            // 判断是否大于四分钟
            if (expire > 4 * 60 * 1000){
                throw new BusinessException("验证码已发送，请" + ((expire / 1000) - 240) + "秒后再试");
            }
        }
        String code = aliEmailServiceImpl.sendVerificationCode(email);
        // 存入redis，有效期5分钟
        redisComponent.saveEmailCode(email, code);
        return getSuccessResponseVO(null);
    }

    // 找回密码。加 IP 限流：验证码本身已有 5 次失败上限，限流进一步压低分布式穷举速率
    // （2026-10-16 审计：此前该端点无任何限速、验证码可无限次尝试）。
    @PostMapping("/forgetPassword")
    @RateLimit(limitType = RateLimit.LimitType.IP, windowSeconds = 60, maxCount = 5, message = "操作过于频繁，请稍后再试")
    public ResponseVO forgetPassword(@NotEmpty @Email @Size(max = 150) String email, @NotEmpty @Pattern(regexp = Constants.REGEX_PASSWORD) String newPassword, @NotEmpty String checkCode){
        // 更新密码
        userInfoService.forgetPassword(email, newPassword, checkCode);
        return getSuccessResponseVO(null);
    }
}
