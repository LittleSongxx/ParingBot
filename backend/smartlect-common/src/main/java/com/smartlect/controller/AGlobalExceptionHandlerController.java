package com.smartlect.controller;

import com.smartlect.entity.enums.ResponseCodeEnum;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.exception.HttpBusinessException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.validation.BindException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.NoHandlerFoundException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.Objects;

@RestControllerAdvice(name = "globalExceptionHandler")
public class AGlobalExceptionHandlerController extends ABaseController {

    private static final Logger logger = LoggerFactory.getLogger(AGlobalExceptionHandlerController.class);

    @ExceptionHandler(value = Exception.class)
    Object handleException(Exception e, HttpServletRequest request, HttpServletResponse response) {
        ResponseVO ajaxResponse = new ResponseVO();
        //404
        if (e instanceof NoHandlerFoundException || e instanceof NoResourceFoundException) {
            logger.debug("请求资源不存在, url={}, message={}", request.getRequestURL(), e.getMessage());
            ajaxResponse.setCode(ResponseCodeEnum.CODE_404.getCode());
            ajaxResponse.setInfo(ResponseCodeEnum.CODE_404.getMsg());
            ajaxResponse.setStatus(STATUS_ERROR);
        } else if (e instanceof BusinessException) {
            //业务错误
            BusinessException biz = (BusinessException) e;
            logger.warn("业务请求未完成, url={}, code={}, message={}",
                    request.getRequestURL(), biz.getCode(), biz.getMessage());
            if (biz instanceof HttpBusinessException httpBusinessException) {
                response.setStatus(httpBusinessException.getHttpStatus());
            } else if (biz.getCode() != null
                    && (Objects.equals(biz.getCode(), 400)
                    || Objects.equals(biz.getCode(), 401)
                    || Objects.equals(biz.getCode(), 403)
                    || Objects.equals(biz.getCode(), 409)
                    || Objects.equals(biz.getCode(), 410)
                    || Objects.equals(biz.getCode(), 429))) {
                response.setStatus(biz.getCode());
            }
            ajaxResponse.setCode(biz.getCode() == null ? ResponseCodeEnum.CODE_600.getCode() : biz.getCode());
            ajaxResponse.setInfo(biz.getMessage());
            ajaxResponse.setData(biz.getData());
            ajaxResponse.setStatus(STATUS_ERROR);
        } else if (e instanceof BindException || e instanceof MethodArgumentTypeMismatchException
                || e instanceof HandlerMethodValidationException) {
            //参数类型错误 / 字段校验失败：此前吞成 CODE_600 通用文案，前端拿不到字段级提示
            logger.warn("请求参数无效, url={}, type={}, message={}",
                    request.getRequestURL(), e.getClass().getSimpleName(), e.getMessage());
            ajaxResponse.setCode(ResponseCodeEnum.CODE_600.getCode());
            ajaxResponse.setInfo(ResponseCodeEnum.CODE_600.getMsg());
            if (e instanceof BindException bindException) {
                // 字段级校验错误（@Valid/@Validated 的 BindingResult）随 data 返回：
                // [{field, message}]，无绑定错误时（纯类型不匹配）data 保持为空
                if (bindException.getBindingResult().hasFieldErrors()) {
                    ajaxResponse.setData(bindException.getBindingResult().getFieldErrors().stream()
                            .map(error -> java.util.Map.of(
                                    "field", error.getField(),
                                    "message", error.getDefaultMessage() == null ? "" : error.getDefaultMessage()))
                            .toList());
                }
            }
            ajaxResponse.setStatus(STATUS_ERROR);
        } else if (e instanceof DuplicateKeyException) {
            //主键冲突
            logger.warn("请求触发唯一键冲突, url={}, message={}", request.getRequestURL(), e.getMessage());
            ajaxResponse.setCode(ResponseCodeEnum.CODE_601.getCode());
            ajaxResponse.setInfo(ResponseCodeEnum.CODE_601.getMsg());
            ajaxResponse.setStatus(STATUS_ERROR);
        } else {
            logger.error("请求处理异常, url={}", request.getRequestURL(), e);
            ajaxResponse.setCode(ResponseCodeEnum.CODE_500.getCode());
            ajaxResponse.setInfo(ResponseCodeEnum.CODE_500.getMsg());
            ajaxResponse.setStatus(STATUS_ERROR);
        }
        return ajaxResponse;
    }
}
