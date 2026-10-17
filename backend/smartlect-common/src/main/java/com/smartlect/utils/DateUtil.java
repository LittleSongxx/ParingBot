package com.smartlect.utils;

import lombok.extern.slf4j.Slf4j;

import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.HashMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.Map;

@Slf4j
public class DateUtil {

    private static final Object lockObj = new Object();
    // ADR-0009：读在锁外的 HashMap 存在理论竞态，换 ConcurrentHashMap（双检锁保留可简化为 computeIfAbsent）
    private static final Map<String, ThreadLocal<SimpleDateFormat>> sdfMap = new ConcurrentHashMap<>();

    private static SimpleDateFormat getSdf(final String pattern) {
        ThreadLocal<SimpleDateFormat> tl = sdfMap.get(pattern);
        if (tl == null) {
            synchronized (lockObj) {
                tl = sdfMap.get(pattern);
                if (tl == null) {
                    tl = new ThreadLocal<SimpleDateFormat>() {
                        @Override
                        protected SimpleDateFormat initialValue() {
                            return new SimpleDateFormat(pattern);
                        }
                    };
                    sdfMap.put(pattern, tl);
                }
            }
        }

        return tl.get();
    }

    public static String format(Date date, String pattern) {
        return getSdf(pattern).format(date);
    }

    public static Date parse(String dateStr, String pattern) {
        // ADR-0009：旧兜底"解析失败回退当前时间"是危险语义（坏输入变合法时间）。
        // 现调用方均为自格式化字符串回读（format→parse 闭环），解析失败按程序错误抛出。
        try {
            return getSdf(pattern).parse(dateStr);
        } catch (ParseException e) {
            throw new IllegalArgumentException("日期解析失败：dateStr=" + dateStr + ", pattern=" + pattern, e);
        }
    }
    public static String getMinAfter(Integer afterMinute, String pattern) {
        // 获取当前时间
        LocalDateTime now = LocalDateTime.now();
        // 当前时间加上afterMinute分钟
        LocalDateTime after = now.plusMinutes(afterMinute);
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern(pattern);
        // 转换成pattern格式
        return after.format(formatter);
    }

    public static String getTimeOnParttern(Integer beforeDay, String parttern) {
        LocalDateTime now = LocalDateTime.now().minusDays(beforeDay);
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern(parttern);
        return now.format(formatter);
    }

    public static Boolean isAfterOneAM(String time) {
        if (time == null || time.isEmpty()) {
            return false;
        }

        try {
            // 如果包含空格，说明是完整日期时间格式，提取时分秒部分
            if (time.contains(" ")) {
                time = time.split(" ")[1]; // 提取 "HH:mm:ss" 部分
            }

            // 把time转换成LocalTime（只包含时分秒）
            LocalTime timeLocal = LocalTime.parse(time, DateTimeFormatter.ofPattern("HH:mm:ss"));
            LocalTime threshold = LocalTime.of(1, 0, 0); // 01:00:00
            return !timeLocal.isBefore(threshold);
        } catch (Exception e) {
            return false;
        }
    }

    public static Boolean isDayDifferenceAtLeastOne(String time1, String time2) {
        if (time1 == null || time2 == null) {
            return false;
        }

        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        LocalDate date1 = LocalDateTime.parse(time1, formatter).toLocalDate();
        LocalDate date2 = LocalDateTime.parse(time2, formatter).toLocalDate();

        long daysBetween = ChronoUnit.DAYS.between(date2, date1);
        return daysBetween >= 1;
    }
}
