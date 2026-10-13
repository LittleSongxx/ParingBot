package com.smartlect.api.support;

import com.smartlect.entity.enums.ResponseCodeEnum;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.utils.StringTools;
import org.apache.dubbo.rpc.RpcException;
import org.springframework.stereotype.Component;

/**
 * 跨服务调用响应解包与异常翻译（Dubbo 版）：RpcException 按类型映射为与原
 * Feign 降级一致的业务文案；类名保留 FeignResponseSupport 以避免波及十余个
 * Support 门面与其单测。
 */
@Component
public class FeignResponseSupport {

    public <T> T unwrap(ResponseVO<T> resp, String fallbackMsg) {
        if (resp == null) {
            throw new BusinessException(fallbackMsg);
        }
        if (resp.getCode() != null && !ResponseCodeEnum.CODE_200.getCode().equals(resp.getCode())) {
            throw new BusinessException(StringTools.isEmpty(resp.getInfo()) ? fallbackMsg : resp.getInfo());
        }
        return resp.getData();
    }

    public BusinessException toBusiness(Throwable ex, String fallbackMsg) {
        if (ex instanceof BusinessException biz) {
            return biz;
        }
        if (ex instanceof RpcException rpcEx) {
            if (rpcEx.isTimeout()) {
                return new BusinessException(ResponseCodeEnum.CODE_500.getCode(), "下游服务超时，请稍后重试");
            }
            if (rpcEx.isNetwork()) {
                return new BusinessException(ResponseCodeEnum.CODE_500.getCode(), "下游服务暂不可用，请稍后重试");
            }
            if (rpcEx.isForbidden()) {
                return new BusinessException(ResponseCodeEnum.CODE_500.getCode(), "内部调用被拒绝");
            }
            return new BusinessException(ResponseCodeEnum.CODE_500.getCode(),
                    StringTools.isEmpty(fallbackMsg) ? "服务调用失败，请稍后重试" : fallbackMsg);
        }
        Throwable cause = ex.getCause();
        if (cause != null && cause != ex) {
            return toBusiness(cause, fallbackMsg);
        }
        return new BusinessException(StringTools.isEmpty(fallbackMsg) ? "服务调用失败" : fallbackMsg);
    }

    public <T> T call(FeignCallable<T> callable, String fallbackMsg) {
        try {
            return unwrap(callable.call(), fallbackMsg);
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw toBusiness(e, fallbackMsg);
        }
    }

    public void run(FeignRunnable runnable, String fallbackMsg) {
        try {
            unwrap(runnable.run(), fallbackMsg);
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw toBusiness(e, fallbackMsg);
        }
    }

    @FunctionalInterface
    public interface FeignCallable<T> {
        ResponseVO<T> call() throws Exception;
    }

    @FunctionalInterface
    public interface FeignRunnable {
        ResponseVO<?> run() throws Exception;
    }
}
