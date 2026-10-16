package com.smartlect.biz.impl;

import com.smartlect.api.enums.CommendTypeEnum;
import com.smartlect.api.enums.ProductStatusEnum;
import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.api.dto.SkuStockQueryDTO;
import com.smartlect.api.vo.ProductPropertyVO;
import com.smartlect.api.vo.ProductPropertyValueVO;
import com.smartlect.biz.ProductInfoService;
import com.smartlect.component.ProductBloomFilterComponent;
import com.smartlect.constants.Constants;
import com.smartlect.entity.dto.ProductSaveDTO;
import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.enums.ResponseCodeEnum;
import com.smartlect.metrics.SmartlectMetrics;
import com.smartlect.entity.po.Product4Load;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.po.ProductPropertyValue;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.query.ProductPropertyValueQuery;
import com.smartlect.entity.query.ProductSkuQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.Product4VO;
import com.smartlect.entity.vo.ProductSkuCountVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.mappers.ProductPropertyValueMapper;
import com.smartlect.mappers.ProductSkuMapper;
import com.smartlect.mappers.SysCategoryMapper;
import com.smartlect.utils.CollectionCompare;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import com.smartlect.utils.PageUtils;

@Service("productInfoService")
@Slf4j
public class ProductInfoServiceImpl implements ProductInfoService {

	@Resource
	private ProductInfoMapper<ProductInfo, ProductInfoQuery> productInfoMapper;
    @Autowired
    private ProductPropertyValueMapper productPropertyValueMapper;
    @Autowired
    private ProductSkuMapper productSkuMapper;
    @Autowired
    private SysCategoryMapper sysCategoryMapper;
	@Resource
	private ProductBloomFilterComponent productBloomFilterComponent;
	@Resource
	private com.smartlect.component.ProductCacheService productCacheService;
	@Resource
	private SmartlectMetrics metrics;
	@Resource
	private StockRpcSupport stockRpcSupport;

	@Override
	public List<ProductInfo> findListByParam(ProductInfoQuery param) {
		return this.productInfoMapper.selectList(param);
	}

	@Override
	public Integer findCountByParam(ProductInfoQuery param) {
		return this.productInfoMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<ProductInfo> findListByPage(ProductInfoQuery param) {
		boolean categoryUnion = useCategoryUnionQuery(param);
		if (categoryUnion) {
			prepareCategoryUnionQuery(param);
		}
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> categoryUnion
				? productInfoMapper.selectListByCategoryUnion(param)
				: this.findListByParam(param));
	}

	private boolean useCategoryUnionQuery(ProductInfoQuery param) {
		return !StringTools.isEmpty(param.getCategoryIdOrPCategoryId());
	}

	private void prepareCategoryUnionQuery(ProductInfoQuery param) {
		param.setCategoryUnionQuery(true);
		if (param.getOrderBy() != null) {
			param.setOrderBy(param.getOrderBy().withoutQualifier("p"));
		}
	}

	@Override
	public Integer add(ProductInfo bean) {
		return this.productInfoMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<ProductInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.productInfoMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<ProductInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.productInfoMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(ProductInfo bean, ProductInfoQuery param) {
		StringTools.checkParam(param);
		return this.productInfoMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(ProductInfoQuery param) {
		StringTools.checkParam(param);
		return this.productInfoMapper.deleteByParam(param);
	}

	@Override
	public ProductInfo getProductInfoByProductId(String productId) {
		if (!productBloomFilterComponent.mightExist(productId)) {
			return null;
		}
		ProductInfo productInfo = this.productInfoMapper.selectByProductId(productId);
		if (productInfo != null) {
			productBloomFilterComponent.add(productId);
		}
		return productInfo;
	}

	@Override
	public Integer updateProductInfoByProductId(ProductInfo bean, String productId) {
		return this.productInfoMapper.updateByProductId(bean, productId);
	}

	@Override
	public Integer deleteProductInfoByProductId(String productId) {
		return this.productInfoMapper.deleteByProductId(productId);
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public void saveProduct(ProductSaveDTO productSaveDTO) {
		normalizeSkuHashes(productSaveDTO);
		ProductInfo productInfo = productSaveDTO.getProductInfo();
		List<ProductPropertyValue> productPropertyList = productSaveDTO.getProductPropertyList();
		List<ProductSku> productSkuList = productSaveDTO.getSkuList();
		//判断是否是新增
		Boolean isAdd = productInfo.getProductId() == null;
		// 如果是新增，生成15位随机数id,设置创建时间精确到秒
		if (isAdd) {
			productInfo.setProductId(StringTools.getRandomNumber(Constants.LENGTH_15));
		}
		// 分别为productProperty和productSku设置productId
		for (ProductPropertyValue productPropertyValue : productPropertyList) {
			productPropertyValue.setProductId(productInfo.getProductId());
		}
		for (ProductSku productSku : productSkuList) {
			productSku.setProductId(productInfo.getProductId());
		}
		productInfo.setStatus(null);
		productInfo.setCommendType(null);
		// 获取商品的最低价格
		productInfo.setMinPrice(productSkuList.stream().map(ProductSku::getPrice).min(BigDecimal::compareTo).orElse(BigDecimal.ZERO));
		// 获取商品的最高价格
		productInfo.setMaxPrice(productSkuList.stream().map(ProductSku::getPrice).max(BigDecimal::compareTo).orElse(BigDecimal.ZERO));
		if (isAdd){
			productInfo.setCreateTime(StringTools.getCurrentDate());
			// 设置状态为未上架
			productInfo.setStatus(Constants.NOT_ON_SALE);
			// 同时将商品信息、商品属性、商品SKU插入数据库
			productInfoMapper.insert(productInfo);
			productPropertyValueMapper.insertBatch(productPropertyList);
			productSkuMapper.insertBatch(productSkuList);
		}// 否则为修改
		 else{
			 // 修改商品信息、商品属性、商品SKU
			 // 为商品信息设置不能修改的属性
			 productInfo.setStatus(null);
			 productInfo.setProductId(productInfo.getProductId());
			 productInfo.setCreateTime(null);
			 productInfo.setCategoryId(null);
			 productInfo.setpCategoryId(null);
			 productInfo.setCommendType(null);
			 productInfoMapper.updateByProductId(productInfo, productInfo.getProductId());
			 // 关于新增、修改、删除的比较可以使用Utils类中的CollectionCompare().compare()方法
			 // 对于商品属性，需要比较是新增，修改，还是删除
			// 创建查询query获取所有商品属性
			 ProductPropertyValueQuery productPropertyValueQuery = new ProductPropertyValueQuery();
			 productPropertyValueQuery.setProductId(productInfo.getProductId());
			 List<ProductPropertyValue> dbPropertyList = productPropertyValueMapper.selectList(productPropertyValueQuery);
			CollectionCompare.CompareResult<ProductPropertyValue> compareResult = new CollectionCompare<ProductPropertyValue>().compare(dbPropertyList, productPropertyList, ProductPropertyValue::getPropertyValueId);
			if (compareResult.addList != null && !compareResult.addList.isEmpty()){
				productPropertyValueMapper.insertBatch(compareResult.addList);
			}
			if (compareResult.updateList != null && !compareResult.updateList.isEmpty()){
				productPropertyValueMapper.updateBatch(productInfo.getProductId(),compareResult.updateList);
			}
			if (compareResult.deleteList != null && !compareResult.deleteList.isEmpty()){
				productPropertyValueMapper.deleteBatch(productInfo.getProductId(),compareResult.deleteList);
			}
			// 对于商品SKU，需要比较是新增，修改，还是删除
			// 创建查询query获取所有商品SKU
			ProductSkuQuery productSkuQuery = new ProductSkuQuery();
			productSkuQuery.setProductId(productInfo.getProductId());
			List<ProductSku> dbSkuList = productSkuMapper.selectList(productSkuQuery);
			CollectionCompare.CompareResult<ProductSku> compareResult4Sku = new CollectionCompare<ProductSku>().compare(dbSkuList, productSkuList, ProductSku::getPropertyValueIdHash);
			if (compareResult4Sku.addList != null && !compareResult4Sku.addList.isEmpty()){
				productSkuMapper.insertBatch(compareResult4Sku.addList);
			}
			if (compareResult4Sku.updateList != null && !compareResult4Sku.updateList.isEmpty()){
				productSkuMapper.updateBatch(productInfo.getProductId(),compareResult4Sku.updateList);
			}
			if (compareResult4Sku.deleteList != null && !compareResult4Sku.deleteList.isEmpty()){
				productSkuMapper.deleteBatch(productInfo.getProductId(),compareResult4Sku.deleteList);
			}
		}
		final boolean added = isAdd;
		// 待数据库操作完成后
		TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
			@Override
			public void afterCommit() {
				if (added) {
					productCacheService.invalidate(productInfo.getProductId());
					productBloomFilterComponent.add(productInfo.getProductId());
				}
			}
		});
	}

	@Override
	public PaginationResultVO findListByPage4ListVO(ProductInfoQuery query) {
		// 在findListByPage的基础上在list中多查询totalStock（product_sku表）；skuCount（product_sku表）；categoryName（sys_category表）；
		PaginationResultVO<ProductInfo> resultVO = this.findListByPage(query);
		List<ProductInfo> list = resultVO.getList();
		List<Product4Load> product4LoadList = new ArrayList<>();
		if (list == null || list.isEmpty()) {
			return new PaginationResultVO<>(resultVO.getTotalCount(), resultVO.getPageSize(),
					resultVO.getPageNo(), resultVO.getPageTotal(), product4LoadList);
		}
		List<String> productIds = list.stream().map(ProductInfo::getProductId).toList();
		Map<String, Integer> stockByProduct = stockRpcSupport.totalByProducts(productIds);
		Map<String, Integer> skuCountByProduct = new HashMap<>();
		List<ProductSkuCountVO> skuCounts = productSkuMapper.selectCountByProductIds(productIds);
		if (skuCounts != null) {
			for (ProductSkuCountVO row : skuCounts) {
				if (row != null && row.getProductId() != null) {
					skuCountByProduct.put(row.getProductId(), row.getSkuCount());
				}
			}
		}
		Set<String> categoryIds = new HashSet<>();
		for (ProductInfo productInfo : list) {
			if (productInfo.getCategoryId() != null) {
				categoryIds.add(productInfo.getCategoryId());
			}
		}
		Map<String, String> categoryNameById = new HashMap<>();
		if (!categoryIds.isEmpty()) {
			List<com.smartlect.entity.po.SysCategory> categories =
					sysCategoryMapper.selectByCategoryIds(new ArrayList<>(categoryIds));
			if (categories != null) {
				for (com.smartlect.entity.po.SysCategory category : categories) {
					if (category != null && category.getCategoryId() != null) {
						categoryNameById.put(category.getCategoryId(), category.getCategoryName());
					}
				}
			}
		}
		for (ProductInfo productInfo : list) {
			// 创建一个Product4Load对象，将productInfo中的数据复制到Product4Load对象中
			Product4Load product4Load = new Product4Load();
			BeanUtils.copyProperties(productInfo, product4Load);
			// 加入新属性
			product4Load.setTotalStock(stockByProduct.getOrDefault(productInfo.getProductId(), 0));
			product4Load.setSkuCount(skuCountByProduct.getOrDefault(productInfo.getProductId(), 0));
			product4Load.setCategoryName(categoryNameById.get(productInfo.getCategoryId()));
			// 加入product4LoadList
			product4LoadList.add(product4Load);
		}
		return new PaginationResultVO<>(resultVO.getTotalCount(), resultVO.getPageSize(), resultVO.getPageNo(), resultVO.getPageTotal(), product4LoadList);
	}

	@Override
	public Product4VO getProduct4VOByProductId(String productId) {
		if (!productBloomFilterComponent.mightExist(productId)) {
			throw new BusinessException(ResponseCodeEnum.CODE_600);
		}
		// Cache-Aside 读：L1（进程内）→ L2（Redis）→ DB，命中后实时补库存（库存不进缓存）
		Product4VO cached = productCacheService.get(productId);
		if (cached != null) {
			return replenishRealtimeStock(cached);
		}
		// 根据productId查询productInfo,productPropertyList,skuList
		ProductInfo productInfo = productInfoMapper.selectByProductId(productId);
		if (productInfo == null) {
			throw new BusinessException(ResponseCodeEnum.CODE_600);
		}
		productBloomFilterComponent.add(productId);
		// 获取productPropertyList
		// 创建Map<String,ProductPropertyValue>其中的String为productPropertyId
		// 同一个属性可以对应多个属性值，其中属性只需存储一次
		Map<String, ProductPropertyVO> productPropertyMap = new HashMap<>();
		// 查询所有属性值，创建查询query
		ProductPropertyValueQuery productPropertyValueQuery = new ProductPropertyValueQuery();
		productPropertyValueQuery.setProductId(productId);
		productPropertyValueQuery.setOrderBy(com.smartlect.entity.query.SafeSort.of("property_sort asc"));
		List<ProductPropertyVO> ProductPropertyVOS = new ArrayList<>();
		List<ProductPropertyValue> productPropertyValueList = productPropertyValueMapper.selectList(productPropertyValueQuery);
		for (ProductPropertyValue productPropertyValue : productPropertyValueList) {
			// 创建ProductPropertyVO从Map中获取
			ProductPropertyVO productPropertyVO = productPropertyMap.get(productPropertyValue.getPropertyId());
			// 创建productPropertyValueVO
			ProductPropertyValueVO productPropertyValueVO = new ProductPropertyValueVO();
			productPropertyValueVO.setPropertyValueId(productPropertyValue.getPropertyValueId());
			productPropertyValueVO.setPropertyValue(productPropertyValue.getPropertyValue());
			productPropertyValueVO.setPropertyCover(productPropertyValue.getPropertyCover());
			productPropertyValueVO.setPropertyGallery(productPropertyValue.getPropertyGallery());
			productPropertyValueVO.setPropertyRemark(productPropertyValue.getPropertyRemark());
			// 如果Map中没有，则创建,并添加属性，添加到Map中
			if (productPropertyVO == null){
				productPropertyVO = new ProductPropertyVO();
				productPropertyVO.setPropertyId(productPropertyValue.getPropertyId());
				productPropertyVO.setPropertyName(productPropertyValue.getPropertyName());
				productPropertyVO.setPropertySort(productPropertyValue.getPropertySort());
				productPropertyVO.setCoverType(productPropertyValue.getCoverType());
				// 添加到Map中
				productPropertyMap.put(productPropertyValue.getPropertyId(), productPropertyVO);
				// 创建List<ProductPropertyValueVO>
				 List<ProductPropertyValueVO> propertyValueVOS = new ArrayList<>();
				 // 将productPropertyValueVO加到propertyValueVOS中
				 propertyValueVOS.add(productPropertyValueVO);
				 // 将propertyValueVOS加到productPropertyVO中
				 productPropertyVO.setPropertyValues(propertyValueVOS);
				 // 将productPropertyVO加到productPropertyVOS中
				 ProductPropertyVOS.add(productPropertyVO);
			}// 如果Map中有，则添加属性值
			else{
				productPropertyVO.getPropertyValues().add(productPropertyValueVO);
			}
		}
		// 获取skuList
		// 创建查询query
		ProductSkuQuery productSkuQuery = new ProductSkuQuery();
		productSkuQuery.setProductId(productId);
		productSkuQuery.setOrderBy(com.smartlect.entity.query.SafeSort.of("sort asc"));
		List<ProductSku> productSkuList = productSkuMapper.selectList(productSkuQuery);
		List<SkuStockQueryDTO> stockQueries = productSkuList.stream()
				.map(sku -> new SkuStockQueryDTO(sku.getProductId(), sku.getPropertyValueIdHash()))
				.toList();
		Map<String, Integer> stockBySku = stockRpcSupport.getAvailableBatch(stockQueries);
		for (ProductSku sku : productSkuList) {
			sku.setStock(stockBySku.getOrDefault(sku.getPropertyValueIdHash(), 0));
		}
		// 封装到Product4VO
		Product4VO product4VO = new Product4VO();
		product4VO.setProductInfo(productInfo);
		product4VO.setProductPropertyList(ProductPropertyVOS);
		product4VO.setSkuList(productSkuList);
		// 回填多级缓存（库存清零后存静态快照，下次命中再实时补）
		productCacheService.put(productId, product4VO);
		metrics.productCache("db", "load");
		return product4VO;
	}

	/** 缓存里的快照库存已清零，这里实时补库存（RPC 查 stock，与 miss 路径同源）。 */
	private Product4VO replenishRealtimeStock(Product4VO cached) {
		if (cached.getSkuList() == null || cached.getSkuList().isEmpty()) {
			return cached;
		}
		java.util.List<com.smartlect.api.dto.SkuStockQueryDTO> queries = cached.getSkuList().stream()
				.map(sku -> new com.smartlect.api.dto.SkuStockQueryDTO(
						sku.getProductId(), sku.getPropertyValueIdHash()))
				.toList();
		java.util.Map<String, Integer> stockBySku = stockRpcSupport.getAvailableBatch(queries);
		for (var sku : cached.getSkuList()) {
			sku.setStock(stockBySku.getOrDefault(sku.getPropertyValueIdHash(), 0));
		}
		return cached;
	}

	@Override
	public void updateSkuStock(String skuId, Integer stock) {
		throw new BusinessException("请使用 productId + propertyValueIdHash 调整库存");
	}

	/**
	 * 服务端权威重算 SKU 指纹（ADR-0022）：此前 hash 由管理端前端计算后直接提交，
	 * 后端从不校验——异常客户端可用同一组属性值配不同 hash 制造重复 SKU。
	 * 现以 md5(propertyValueIds) 重算覆写，并拒绝同商品内重复指纹。
	 */
	private void normalizeSkuHashes(ProductSaveDTO productSaveDTO) {
		java.util.List<ProductSku> skuList = productSaveDTO.getSkuList();
		if (skuList == null || skuList.isEmpty()) {
			return;
		}
		java.util.Set<String> seen = new java.util.HashSet<>();
		for (ProductSku sku : skuList) {
			if (StringTools.isEmpty(sku.getPropertyValueIds())) {
				throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "SKU 规格属性不能为空");
			}
			String authoritative = StringTools.encodeByMD5(sku.getPropertyValueIds());
			if (authoritative == null) {
				throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "SKU 规格指纹计算失败");
			}
			if (!authoritative.equals(sku.getPropertyValueIdHash())) {
				log.warn("SKU 指纹与属性不一致，已按服务端重算覆写 productId={}, submitted={}, expected={}",
						productSaveDTO.getProductInfo() == null ? null : productSaveDTO.getProductInfo().getProductId(), sku.getPropertyValueIdHash(), authoritative);
				sku.setPropertyValueIdHash(authoritative);
			}
			if (!seen.add(authoritative)) {
				throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "存在重复的 SKU 规格组合");
			}
		}
	}

	@Override
	public void updateProductStatus(String productId, Integer status) {
		ProductStatusEnum statusEnum = ProductStatusEnum.getByStatus(status);
		if (statusEnum == null || statusEnum == ProductStatusEnum.DELETE ) {
			throw new BusinessException(ResponseCodeEnum.CODE_600);
		}
		if (statusEnum == ProductStatusEnum.OFF_SALE) {
			ProductInfo existing = productInfoMapper.selectByProductId(productId);
			if (existing == null) {
				throw new BusinessException(ResponseCodeEnum.CODE_600);
			}
			if (CommendTypeEnum.COMMEND.getType().equals(existing.getCommendType())) {
				throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "请先取消推荐后再下架");
			}
		}
		// ADR-0022：check-then-update 改条件更新（CAS），两个管理员并发操作不再越权覆盖
		ProductInfo existing = productInfoMapper.selectByProductId(productId);
		if (existing == null) {
			throw new BusinessException(ResponseCodeEnum.CODE_600);
		}
		ProductInfo productInfo = new ProductInfo();
		productInfo.setStatus(status);
		ProductInfoQuery casQuery = new ProductInfoQuery();
		casQuery.setProductId(productId);
		casQuery.setStatus(existing.getStatus());
		if (productInfoMapper.updateByParam(productInfo, casQuery) != 1) {
			throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "商品状态已变化，请刷新后重试");
		}
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public void deleteProduct(String productId) {
		ProductInfo existing = productInfoMapper.selectByProductId(productId);
		if (existing == null) {
			throw new BusinessException(ResponseCodeEnum.CODE_600);
		}
		if (ProductStatusEnum.ON_SALE.getStatus().equals(existing.getStatus())) {
			throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "请先下架商品后再删除");
		}
		if (CommendTypeEnum.COMMEND.getType().equals(existing.getCommendType())) {
			throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "请先取消推荐后再删除");
		}
		ProductInfo productInfo = new ProductInfo();
		productInfo.setStatus(ProductStatusEnum.DELETE.getStatus());
		// ADR-0022：删除也走条件更新——仅下架态可删，并发窗口内被重新上架则失败重试
		ProductInfoQuery casQuery = new ProductInfoQuery();
		casQuery.setProductId(productId);
		casQuery.setStatus(ProductStatusEnum.OFF_SALE.getStatus());
		if (productInfoMapper.updateByParam(productInfo, casQuery) != 1) {
			throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "商品状态已变化，请刷新后重试");
		}
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public void commendProduct(String productId, Integer commendType) {
		CommendTypeEnum commendTypeEnum = CommendTypeEnum.getByType(commendType);
		if (commendTypeEnum == null) {
			throw new BusinessException(ResponseCodeEnum.CODE_600);
		}
		if (commendTypeEnum == CommendTypeEnum.COMMEND) {
			ProductInfo existing = productInfoMapper.selectByProductId(productId);
			if (existing == null || !ProductStatusEnum.ON_SALE.getStatus().equals(existing.getStatus())) {
				throw new BusinessException(ResponseCodeEnum.CODE_600.getCode(), "仅已上架商品可设为推荐");
			}
		}
		ProductInfo productInfo = new ProductInfo();
		productInfo.setCommendType(commendType);
		productInfoMapper.updateByProductId(productInfo, productId);
		if (commendTypeEnum == CommendTypeEnum.COMMEND) {
			TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
				@Override
				public void afterCommit() {
					productCacheService.invalidate(productId);
        productBloomFilterComponent.add(productId);
				}
			});
		}
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public void updateTotalSale(List<String> productIdList) {
		if (productIdList == null || productIdList.isEmpty()) {
			return;
		}
		productInfoMapper.updateTotalSale(productIdList);
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public void updateTotalSaleByCount(java.util.Map<String, Integer> productSaleMap) {
		if (productSaleMap == null || productSaleMap.isEmpty()) {
			return;
		}
		productInfoMapper.updateTotalSaleByCount(productSaleMap);
	}
}
