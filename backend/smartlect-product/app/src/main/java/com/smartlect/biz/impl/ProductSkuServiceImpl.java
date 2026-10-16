package com.smartlect.biz.impl;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import com.smartlect.catalog.IsolatedCatalog;
import com.smartlect.api.dto.SkuStockDTO;
import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.api.enums.ProductStatusEnum;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.po.ProductPropertyValue;
import com.smartlect.api.vo.ProductSkuListVO;
import com.smartlect.api.vo.ProductSkuProperDataVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.mappers.ProductPropertyValueMapper;
import com.smartlect.biz.ProductInfoService;
import jakarta.annotation.Resource;

import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.query.ProductSkuQuery;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.query.SimplePage;
import com.smartlect.mappers.ProductSkuMapper;
import com.smartlect.biz.ProductSkuService;
import com.smartlect.utils.StringTools;
import org.springframework.transaction.annotation.Transactional;
import com.github.pagehelper.PageInfo;
import com.smartlect.utils.PageUtils;

@Service("productSkuService")
public class ProductSkuServiceImpl implements ProductSkuService {

	@Resource
	private ProductSkuMapper<ProductSku, ProductSkuQuery> productSkuMapper;
	@Resource
	private StockRpcSupport stockRpcSupport;
	@Resource
	private ProductInfoService productInfoService;
    @Autowired
    private ProductInfoMapper productInfoMapper;
    @Autowired
    private ProductPropertyValueMapper productPropertyValueMapper;

	@Override
	public List<ProductSku> findListByParam(ProductSkuQuery param) {
		return this.productSkuMapper.selectList(param);
	}

	@Override
	public Integer findCountByParam(ProductSkuQuery param) {
		return this.productSkuMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<ProductSku> findListByPage(ProductSkuQuery param) {
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> this.findListByParam(param));
	}

	@Override
	public Integer add(ProductSku bean) {
		return this.productSkuMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<ProductSku> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.productSkuMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<ProductSku> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.productSkuMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(ProductSku bean, ProductSkuQuery param) {
		StringTools.checkParam(param);
		return this.productSkuMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(ProductSkuQuery param) {
		StringTools.checkParam(param);
		return this.productSkuMapper.deleteByParam(param);
	}

	@Override
	public ProductSku getProductSkuByProductIdAndPropertyValueIdHash(String productId, String propertyValueIdHash) {
		return this.productSkuMapper.selectByProductIdAndPropertyValueIdHash(productId, propertyValueIdHash);
	}

	@Override
	public Integer updateProductSkuByProductIdAndPropertyValueIdHash(ProductSku bean, String productId, String propertyValueIdHash) {
		return this.productSkuMapper.updateByProductIdAndPropertyValueIdHash(bean, productId, propertyValueIdHash);
	}

	@Override
	public Integer deleteProductSkuByProductIdAndPropertyValueIdHash(String productId, String propertyValueIdHash) {
		return this.productSkuMapper.deleteByProductIdAndPropertyValueIdHash(productId, propertyValueIdHash);
	}

	@Override
	// 不标 @Transactional：方法内只有一次本地读 + 一次远程调用（stockRpcSupport.changeStock），
	// 没有任何本地写需要原子保护。保留事务只会让数据库连接在整个远程调用期间被占住。
	public void updateStock(String productId, String propertyValueIdHash, Integer changeStock) {
		ProductSku productSku = this.getProductSkuByProductIdAndPropertyValueIdHash(productId, propertyValueIdHash);
		if (productSku == null) {
			throw new BusinessException("商品sku不存在");
		}
		stockRpcSupport.changeStock(productId, propertyValueIdHash, changeStock);
	}

	@Override
	public PaginationResultVO<ProductSkuListVO> findListByPage4ListVO(ProductSkuQuery query) {
		PageInfo<ProductSku> pageInfo = PageUtils.pageInfo(query.getPageNo(), query.getPageSize(), () -> findListByParam(query));
		int count = (int) pageInfo.getTotal();
		List<ProductSku> productSkuList = pageInfo.getList();
		List<ProductSkuListVO> productSkuListVOList = new ArrayList<>();
		for (ProductSku productSku : productSkuList){
			ProductInfo productInfo = productInfoService.getProductInfoByProductId(productSku.getProductId());
			if (productInfo == null) {
				continue;
			}
			ProductSkuListVO productSkuListVO = new ProductSkuListVO();
			BeanUtils.copyProperties(productSku, productSkuListVO);
			productSkuListVO.setStock(stockRpcSupport.getAvailable(
					productSku.getProductId(), productSku.getPropertyValueIdHash()));
			productSkuListVO.setProductName(productInfo.getProductName());
			productSkuListVO.setProductOnsale(ProductStatusEnum.ON_SALE.getStatus().equals(productInfo.getStatus()));
			List<ProductSkuProperDataVO> productSkuProperDataVOList = new ArrayList<>();
			if (!StringTools.isEmpty(productSku.getPropertyValueIds())) {
				String[] propertyValueIds = productSku.getPropertyValueIds().split("-");
				for (String propertyValueId : propertyValueIds) {
					ProductPropertyValue productPropertyValue = (ProductPropertyValue) productPropertyValueMapper.selectByProductIdAndPropertyValueId(productSku.getProductId(), propertyValueId);
					if (productPropertyValue == null) {
						continue;
					}
					ProductSkuProperDataVO productSkuProperDataVO = new ProductSkuProperDataVO();
					productSkuProperDataVO.setPropertyName(productPropertyValue.getPropertyName());
					productSkuProperDataVO.setPropertyValue(productPropertyValue.getPropertyValue());
					productSkuProperDataVOList.add(productSkuProperDataVO);
				}
			}
			if (productSkuListVO.getProductCover() == null && !StringTools.isEmpty(productInfo.getCover())){
				productSkuListVO.setProductCover(productInfo.getCover().split(",")[0]);
			}
			productSkuListVO.setPropertyData(productSkuProperDataVOList);
			productSkuListVOList.add(productSkuListVO);
		}
		int pageTotal = (int) Math.ceil((double) count / pageInfo.getPageSize());
		return new PaginationResultVO<>(count, pageInfo.getPageSize(), pageInfo.getPageNum(), pageTotal, productSkuListVOList);
	}

	@Override
	public PaginationResultVO<ProductSkuListVO> lessStockSkuPage(Integer pageNo, Integer pageSize, Integer threshold) {
		int size = pageSize == null ? PageSize.SIZE15.getSize() : pageSize;
		int no = pageNo == null || pageNo < 1 ? 1 : pageNo;
		// 先拉全量低库存再富化过滤，最后内存分页。
		// 若按 stock 页直接切页，无 product_info 的孤儿 SKU 会占满首页（如 pageSize=4），
		// 导致真实库存=5 的预警被挤掉、列表为空或只剩残缺数据。
		List<ProductSkuListVO> all = new ArrayList<>();
		int stockPageNo = 1;
		final int batch = 100;
		final int maxStockPages = 20;
		while (true) {
			PaginationResultVO<SkuStockDTO> stockPage = stockRpcSupport.listLessThan(stockPageNo, batch, threshold);
			if (stockPage == null || stockPage.getList() == null || stockPage.getList().isEmpty()) {
				break;
			}
			for (SkuStockDTO skuStock : stockPage.getList()) {
				ProductSkuListVO vo = buildLessStockSkuVo(skuStock);
				if (vo != null) {
					all.add(vo);
				}
			}
			int stockPageTotal = stockPage.getPageTotal() == null ? 1 : stockPage.getPageTotal();
			if (stockPageNo >= stockPageTotal) {
				break;
			}
			stockPageNo++;
			if (stockPageNo > maxStockPages) {
				break;
			}
		}
		int count = all.size();
		SimplePage page = new SimplePage(no, count, size);
		int from = page.getStart();
		List<ProductSkuListVO> slice = from >= count
				? Collections.emptyList()
				: all.subList(from, Math.min(from + size, count));
		return new PaginationResultVO<>(count, page.getPageSize(), page.getPageNo(), page.getPageTotal(), slice);
	}

	private ProductSkuListVO buildLessStockSkuVo(SkuStockDTO skuStock) {
		if (skuStock == null || StringTools.isEmpty(skuStock.getProductId())
				|| StringTools.isEmpty(skuStock.getPropertyValueIdHash())) {
			return null;
		}
		ProductSku productSku = getProductSkuByProductIdAndPropertyValueIdHash(
				skuStock.getProductId(), skuStock.getPropertyValueIdHash());
		if (productSku == null) {
			return null;
		}
		ProductInfo productInfo = productInfoService.getProductInfoByProductId(productSku.getProductId());
		if (productInfo == null || IsolatedCatalog.isEvalScope(productInfo.getCatalogScope())) {
			return null;
		}
		ProductSkuListVO productSkuListVO = new ProductSkuListVO();
		BeanUtils.copyProperties(productSku, productSkuListVO);
		productSkuListVO.setStock(skuStock.getStock() == null ? 0 : skuStock.getStock());
		productSkuListVO.setProductName(productInfo.getProductName());
		productSkuListVO.setProductOnsale(ProductStatusEnum.ON_SALE.getStatus().equals(productInfo.getStatus()));
		List<ProductSkuProperDataVO> productSkuProperDataVOList = new ArrayList<>();
		if (!StringTools.isEmpty(productSku.getPropertyValueIds())) {
			String[] propertyValueIds = productSku.getPropertyValueIds().split("-");
			for (String propertyValueId : propertyValueIds) {
				ProductPropertyValue productPropertyValue = (ProductPropertyValue) productPropertyValueMapper
						.selectByProductIdAndPropertyValueId(productSku.getProductId(), propertyValueId);
				if (productPropertyValue == null) {
					continue;
				}
				ProductSkuProperDataVO productSkuProperDataVO = new ProductSkuProperDataVO();
				productSkuProperDataVO.setPropertyName(productPropertyValue.getPropertyName());
				productSkuProperDataVO.setPropertyValue(productPropertyValue.getPropertyValue());
				productSkuProperDataVOList.add(productSkuProperDataVO);
			}
		}
		if (productSkuListVO.getProductCover() == null && !StringTools.isEmpty(productInfo.getCover())) {
			productSkuListVO.setProductCover(productInfo.getCover().split(",")[0]);
		}
		productSkuListVO.setPropertyData(productSkuProperDataVOList);
		return productSkuListVO;
	}
}
