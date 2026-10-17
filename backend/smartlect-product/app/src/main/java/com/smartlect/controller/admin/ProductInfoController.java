package com.smartlect.controller.admin;

import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.annotation.AdminSensitiveConfirm;
import com.smartlect.catalog.IsolatedCatalog;
import com.smartlect.entity.dto.ProductSaveDTO;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.ProductInfoService;
import com.smartlect.biz.ProductSkuService;
import com.smartlect.valid.Create;
import com.smartlect.valid.Update;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("productInfoController")
@RequestMapping("/admin/productInfo")
public class ProductInfoController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private ProductInfoService productInfoService;

	@Resource
	private ProductSkuService productSkuService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(ProductInfoQuery query){
		return getSuccessResponseVO(productInfoService.findListByPage(query));
	}

	@PostMapping("/addProduct")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	public ResponseVO addProduct(@RequestBody @Validated(Create.class) ProductSaveDTO productSaveDTO) {
		productInfoService.saveProduct(productSaveDTO);
		return getSuccessResponseVO(productSaveDTO.getProductInfo().getProductId());
	}

	@PostMapping("/updateProduct")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	@AdminSensitiveConfirm
	public ResponseVO updateProduct(@RequestBody @Validated(Update.class) ProductSaveDTO productSaveDTO) {
		productInfoService.saveProduct(productSaveDTO);
		return getSuccessResponseVO(productSaveDTO.getProductInfo().getProductId());
	}

	@PostMapping("/loadProduct")
	public ResponseVO loadProduct(String productNameFuzzy,
								  Integer pageNo,
								  Integer pageSize,
								  String categoryIdOrPCategoryId,
								  Integer status,
								  Integer commendType) {
		ProductInfoQuery query = new ProductInfoQuery();
		query.setProductNameFuzzy(productNameFuzzy);
		query.setPageNo(pageNo);
		query.setPageSize(pageSize);
		query.setCategoryIdOrPCategoryId(categoryIdOrPCategoryId);
		query.setStatus(status);
		query.setCommendType(commendType);
		query.setOrderBy(com.smartlect.entity.query.SafeSort.of("create_time desc"));
		query.setExcludeIsolatedCatalog(!IsolatedCatalog.looksLikeIsolatedSearch(productNameFuzzy));
		PaginationResultVO resultVO = productInfoService.findListByPage4ListVO(query);
		return getSuccessResponseVO(resultVO);
	}

	@PostMapping("/getProductInfo")
	public ResponseVO getProductInfo(@NotEmpty String productId) {
		return getSuccessResponseVO(productInfoService.getProduct4VOByProductId(productId));
	}

	@PostMapping("/updateSkuStock")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	@AdminSensitiveConfirm
	public ResponseVO updateSkuStock(@NotEmpty String productId, @NotEmpty String propertyValueIdHash, @NotNull Integer changeStock) {
		productSkuService.updateStock(productId, propertyValueIdHash, changeStock);
		return getSuccessResponseVO(null);
	}

	@PostMapping("/updateProductStatus")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	@AdminSensitiveConfirm
	public ResponseVO updateProductStatus(@NotNull String productId, @NotNull Integer status) {
		productInfoService.updateProductStatus(productId,status);
		return getSuccessResponseVO(null);
	}

	@PostMapping("/deleteProduct")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	@AdminSensitiveConfirm
	public ResponseVO deleteProduct(@NotNull String productId) {
		productInfoService.deleteProduct(productId);
		return getSuccessResponseVO(null);
	}

	@PostMapping("/commendProduct")
	@SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
	public ResponseVO commendProduct(@NotNull String productId, @NotNull Integer commendType) {
		productInfoService.commendProduct(productId,commendType);
		return getSuccessResponseVO(null);
	}
}
