package com.smartlect.utils;
import com.smartlect.constants.Constants;
import com.smartlect.exception.BusinessException;
import jakarta.validation.constraints.NotNull;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.RandomStringUtils;
import org.springframework.util.DigestUtils;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;


@Slf4j
public class StringTools {

    public static void checkParam(Object param) {
        try {
            Field[] fields = param.getClass().getDeclaredFields();
            Boolean notEmpty = false;
            for (Field field : fields) {
                String methodName = "get" + StringTools.upperCaseFirstLetter(field.getName());
                Method method = param.getClass().getMethod(methodName);
                Object object = method.invoke(param);
                if (object != null && object instanceof java.lang.String && !StringTools.isEmpty(object.toString())
                        || object != null && !(object instanceof java.lang.String)) {
                    notEmpty = true;
                    break;
                }
            }
            if (!notEmpty) {
                throw new BusinessException("多参数更新，删除，必须有非空条件");
            }
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("参数非空校验反射失败：{}", param.getClass().getName(), e);
            throw new BusinessException("校验参数是否为空失败");
        }
    }

    public static String upperCaseFirstLetter(String field) {
        if (isEmpty(field)) {
            return field;
        }
        //如果第二个字母是大写，第一个字母不大写
        if (field.length() > 1 && Character.isUpperCase(field.charAt(1))) {
            return field;
        }
        return field.substring(0, 1).toUpperCase() + field.substring(1);
    }

    public static Boolean isEmpty(String str) {
        if (null == str || "".equals(str) || "null".equals(str) || "\u0000".equals(str)) {
            return true;
        } else if ("".equals(str.trim())) {
            return true;
        }
        return false;
    }

    public static String getRandomString(Integer count) {
        return RandomStringUtils.random(count, true, true);
    }

    public static String getFileSuffix(String fileName) {
        if (StringTools.isEmpty(fileName)) {
            return "";
        }
        int lastDotIndex = fileName.lastIndexOf(".");
        if (lastDotIndex == -1 || lastDotIndex == fileName.length() - 1) {
            return "";
        }
        String suffix = fileName.substring(lastDotIndex);
        return suffix;
    }

    /**
     * 安全随机数字串（验证码等安全码专用）：commons-lang3 的默认实例是 ThreadLocalRandom，
     * 不是 CSPRNG（2026-10-16 审计）；安全码必须走 SecureRandom。
     */
    public static String getSecureRandomNumber(int count) {
        java.security.SecureRandom random = new java.security.SecureRandom();
        StringBuilder builder = new StringBuilder(count);
        for (int i = 0; i < count; i++) {
            builder.append(random.nextInt(10));
        }
        return builder.toString();
    }

    public static final String getRandomNumber(Integer count) {
        return RandomStringUtils.random(count, false, true);
    }

    public static String encodeByMD5(String str){
        return StringTools.isEmpty(str) ? null : DigestUtils.md5DigestAsHex(str.getBytes());
    }

    public static Boolean pathIsOK(@NotNull String sourceName) {
        return !sourceName.contains("..") ;
    }

    // 获取时间，精确到秒
    public static Date getCurrentDate() {
        return new Date();
    }

    public static String createOrderId() {
        // 生成时间yyyymmddhhmmsssss到毫秒+15位随机字符串
        return DateUtil.format(new Date(), "yyyyMMddHHmmssSSS") + getRandomString(Constants.LENGTH_15);
    }

    public static final String createPayOrderId() {
        return StringTools.getRandomNumber(Constants.LENGTH_30);
    }

    public static String createCouponId() {
        // 格式CP + yyyyMMdd + 5位随机字符串
        return "CP" + DateUtil.format(new Date(), "yyyyMMdd") + getRandomString(Constants.LENGTH_5);
    }

    public static String createUserCouponId() {
        // 30位的随机字符串
        return getRandomString(Constants.LENGTH_30);
    }

    public static String createStableUserCouponId(
            String namespace, String userId, String businessId) {
        if (isEmpty(namespace) || isEmpty(userId) || isEmpty(businessId)) {
            throw new IllegalArgumentException("稳定用户券ID参数不能为空");
        }
        String source = namespace + ":" + userId + ":" + businessId;
        return UUID.nameUUIDFromBytes(source.getBytes(StandardCharsets.UTF_8))
                .toString()
                .replace("-", "");
    }

    public static String createNotificationId() {
        return "N" + getRandomString(Constants.LENGTH_30);
    }

    public static String createTradeId() {
        return "T" + DateUtil.format(new Date(), "yyyyMMddHHmmssSSS") + getRandomString(Constants.LENGTH_15);
    }
}
