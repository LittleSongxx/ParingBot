package com.smartlect.controller.admin;

import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.entity.po.SysProductProperty;
import com.smartlect.entity.query.SysCategoryQuery;
import com.smartlect.entity.po.SysCategory;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.SysCategoryService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("sysCategoryController")
@RequestMapping("/admin/sysCategory")
public class SysCategoryController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private SysCategoryService sysCategoryService;

	@PostMapping("/loadCategory")
	public ResponseVO loadCategory(Boolean queryProperty){
		SysCategoryQuery query = new SysCategoryQuery();
		if (queryProperty!=null && queryProperty){
			query.setOrderBy(com.smartlect.entity.query.SafeSort.of("s.sort asc"));
		}
		query.setPropertyQuery(queryProperty);
		query.setParent(true);
		return getSuccessResponseVO(sysCategoryService.findListByParam(query));
	}

	@PostMapping("/saveCategory")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	public ResponseVO saveCategory(SysCategory bean) {
		sysCategoryService.saveCategory(bean);
		return getSuccessResponseVO(null);
	}

	@PostMapping("/getSysCategoryByCategoryId")
	public ResponseVO getSysCategoryByCategoryId(String categoryId) {
		return getSuccessResponseVO(sysCategoryService.getSysCategoryByCategoryId(categoryId));
	}

	@PostMapping("/delCategory")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	public ResponseVO delCategory(SysCategory bean) {
		sysCategoryService.deleteSysCategory(bean);
		return getSuccessResponseVO(null);
	}

	@PostMapping("/changeCategorySort")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	public ResponseVO changeCategorySort(String categoryIds) {
		sysCategoryService.changeCategorySort(categoryIds);
		return getSuccessResponseVO(null);
	}

	@PostMapping("/saveProductProperty")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	public ResponseVO saveProductProperty(SysProductProperty bean) {
		sysCategoryService.saveProductProperty(bean);
		return getSuccessResponseVO(null);
	}

	@PostMapping("/delProductProperty")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	public ResponseVO delProductProperty(SysProductProperty bean) {
		sysCategoryService.delProductProperty(bean);
		return getSuccessResponseVO(null);
	}
}
