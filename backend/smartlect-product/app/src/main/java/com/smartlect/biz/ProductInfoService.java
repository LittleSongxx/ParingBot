package com.smartlect.biz;

import java.util.List;

import com.smartlect.entity.dto.ProductSaveDTO;
import com.smartlect.entity.vo.Product4VO;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.vo.PaginationResultVO;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;

public interface ProductInfoService {

	List<ProductInfo> findListByParam(ProductInfoQuery param);

	Integer findCountByParam(ProductInfoQuery param);

	PaginationResultVO<ProductInfo> findListByPage(ProductInfoQuery param);

	Integer add(ProductInfo bean);

	Integer addBatch(List<ProductInfo> listBean);

	Integer addOrUpdateBatch(List<ProductInfo> listBean);

	Integer updateByParam(ProductInfo bean,ProductInfoQuery param);

	Integer deleteByParam(ProductInfoQuery param);

	ProductInfo getProductInfoByProductId(String productId);

	Integer updateProductInfoByProductId(ProductInfo bean,String productId);

	Integer deleteProductInfoByProductId(String productId);

    void saveProduct(ProductSaveDTO productSaveDTO);

	PaginationResultVO findListByPage4ListVO(ProductInfoQuery query);

	Product4VO getProduct4VOByProductId(@NotEmpty String productId);

	/**
	 * @param requireOnSale 公开详情必须为在售；管理端预览传 false，可查看下架商品。
	 */
	Product4VO getProduct4VOByProductId(@NotEmpty String productId, boolean requireOnSale);

	void updateSkuStock(@NotNull String skuId, @NotNull Integer stock);

	void updateProductStatus(@NotNull String productId, @NotNull Integer status);

	void deleteProduct(@NotNull String productId);

	void commendProduct(@NotNull String productId, @NotNull Integer commendType);

	void updateTotalSale(List<String> productIdList);

	void updateTotalSaleByCount(java.util.Map<String, Integer> productSaleMap);
}
