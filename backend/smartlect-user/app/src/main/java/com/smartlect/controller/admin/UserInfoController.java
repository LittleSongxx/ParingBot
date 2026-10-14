package com.smartlect.controller.admin;

import com.smartlect.entity.query.UserInfoQuery;
import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.UserInfoService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("userInfoController")
@RequestMapping("/admin/userInfo")
@SaCheckPermission(value = {"user:manage-read"}, orRole = "SUPER_ADMIN", type = "admin")
public class UserInfoController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private UserInfoService userInfoService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(UserInfoQuery query){
		return getSuccessResponseVO(userInfoService.findListByPage(query));
	}

	@PostMapping("/getUserInfoByUserId")
	public ResponseVO getUserInfoByUserId(String userId) {
		return getSuccessResponseVO(userInfoService.getUserInfoByUserId(userId));
	}

	@PostMapping("/getUserInfoByEmail")
	public ResponseVO getUserInfoByEmail(String email) {
		return getSuccessResponseVO(userInfoService.getUserInfoByEmail(email));
	}

	@PostMapping("/getUserInfoByNickName")
	public ResponseVO getUserInfoByNickName(String nickName) {
		return getSuccessResponseVO(userInfoService.getUserInfoByNickName(nickName));
	}

}
