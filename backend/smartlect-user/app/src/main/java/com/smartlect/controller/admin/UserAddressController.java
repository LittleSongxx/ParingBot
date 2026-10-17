package com.smartlect.controller.admin;

import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.entity.query.UserAddressQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.UserAddressService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("adminUserAddressController")
@RequestMapping("/admin/userAddress")
public class UserAddressController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private UserAddressService userAddressService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(UserAddressQuery query){
		query.setOrderBy(com.smartlect.entity.query.SafeSort.of("address_id desc"));
		return getSuccessResponseVO(userAddressService.findListByPage(query));
	}

	@PostMapping("/getUserAddressByAddressId")
	public ResponseVO getUserAddressByAddressId(String addressId) {
		return getSuccessResponseVO(userAddressService.getUserAddressByAddressId(addressId));
	}

	@PostMapping("/deleteUserAddressByAddressId")
	@SaCheckPermission(value = AdminPermissions.USER_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	public ResponseVO deleteUserAddressByAddressId(String addressId) {
		userAddressService.deleteUserAddressByAddressId(addressId);
		return getSuccessResponseVO(null);
	}
}
