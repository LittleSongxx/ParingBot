package com.smartlect.controller;
import com.smartlect.component.RedisComponent;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.enums.ResponseCodeEnum;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.utils.AuthCookieHelper;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;


public class ABaseController {

    @Resource
    protected RedisComponent redisComponent;

    @Resource
    protected AuthCookieHelper authCookieHelper;

    protected static final String STATUS_SUCCESS = "success";

    protected static final String STATUS_ERROR = "error";

    protected <T> ResponseVO getSuccessResponseVO(T t) {
        ResponseVO<T> responseVO = new ResponseVO<>();
        responseVO.setStatus(STATUS_SUCCESS);
        responseVO.setCode(ResponseCodeEnum.CODE_200.getCode());
        responseVO.setInfo(ResponseCodeEnum.CODE_200.getMsg());
        responseVO.setData(t);
        return responseVO;
    }

    // Sa-Token 会话获取 TokenUserInfoDTO（登录时由 AccountController 存入 session）
    public TokenUserInfoDTO getTokenUserInfo() {
        try {
            Object session = cn.dev33.satoken.stp.StpUtil.getSession().get("userInfo");
            return session instanceof TokenUserInfoDTO dto ? dto : null;
        } catch (Exception e) {
            return null;
        }
    }
    protected <T> ResponseVO getBusinessErrorResponseVO(BusinessException e, T t) {
        ResponseVO vo = new ResponseVO();
        vo.setStatus(STATUS_ERROR);
        if (e.getCode() == null) {
            vo.setCode(ResponseCodeEnum.CODE_600.getCode());
        } else {
            vo.setCode(e.getCode());
        }
        vo.setInfo(e.getMessage());
        vo.setData(t);
        return vo;
    }

    protected <T> ResponseVO getServerErrorResponseVO(T t) {
        ResponseVO vo = new ResponseVO();
        vo.setStatus(STATUS_ERROR);
        vo.setCode(ResponseCodeEnum.CODE_500.getCode());
        vo.setInfo(ResponseCodeEnum.CODE_500.getMsg());
        vo.setData(t);
        return vo;
    }
}
