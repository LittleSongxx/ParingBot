package com.smartlect.biz.impl;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import com.smartlect.component.RedisComponent;
import com.smartlect.constants.Constants;
import com.smartlect.entity.po.SysProductProperty;
import com.smartlect.entity.query.SysProductPropertyQuery;
import com.smartlect.mappers.SysProductPropertyMapper;
import jakarta.annotation.Resource;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.query.SysCategoryQuery;
import com.smartlect.entity.po.SysCategory;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.mappers.SysCategoryMapper;
import com.smartlect.biz.SysCategoryService;
import com.smartlect.utils.StringTools;
import com.smartlect.utils.PageUtils;
import org.springframework.transaction.annotation.Transactional;

@Service("sysCategoryService")
@Slf4j
public class SysCategoryServiceImpl implements SysCategoryService {

	@Resource
	private SysCategoryMapper<SysCategory, SysCategoryQuery> sysCategoryMapper;

	@Resource
	private SysProductPropertyMapper<SysProductProperty, SysProductProperty> sysProductPropertyMapper;
    @Autowired
    private SysProductPropertyServiceImpl sysProductPropertyService;

	@Resource
	private RedisComponent redisComponent;

	@Override
	public List<SysCategory> findListByParam(SysCategoryQuery param) {
		List<SysCategory> list = this.sysCategoryMapper.selectList(param);
		if (Boolean.TRUE.equals(param.getParent())) {
			// 公开读路径只查 MySQL；分类快照的 Redis 写入放到管理端写操作/显式刷新，
			// 避免每个首页请求多做一次全表查询和一次 Redis 写（2026-10-18 ECS 压测热点）。
			list = findChildren(list, Constants.ZERO_STR);
		}
		if (Boolean.TRUE.equals(param.getPropertyQuery())) {
			list = find4Property(list);
		}
		return list;
	}

	public List<SysCategory> findChildren(List<SysCategory> dataList,String pCategoryId){
		List<SysCategory> childrenList = new ArrayList<>();
		for (SysCategory data : dataList) {
			if (data.getCategoryId()!=null && data.getpCategoryId()!=null && pCategoryId.equals(data.getpCategoryId())) {
				data.setChildren(findChildren(dataList, data.getCategoryId()));
				childrenList.add(data);
			}
		}
		return childrenList;
	}

	public List<SysCategory> find4Property(List<SysCategory> dataList){
		if (dataList == null || dataList.isEmpty()) {
			return new ArrayList<>();
		}
		SysProductPropertyQuery query = new SysProductPropertyQuery();
		List<SysProductProperty> productPropertyList = sysProductPropertyService.findListByParam(query);
		// 将属性按 categoryId 分组 (Map<categoryId, List<property>>)
		// 并在分组时按 propertySort 升序排序
		Map<String, List<SysProductProperty>> propertyMap = productPropertyList.stream()
				.filter(p -> p.getCategoryId() != null)
				.collect(Collectors.groupingBy(
						SysProductProperty::getCategoryId,
						Collectors.collectingAndThen(
								Collectors.toList(),
								list -> list.stream()
										.sorted(Comparator.comparing(SysProductProperty::getPropertySort, Comparator.nullsLast(Integer::compareTo)))
										.collect(Collectors.toList())
						)
				));

		// 遍历分类列表，将属性挂载到对应的分类节点上
		for (SysCategory category : dataList) {
			if (category.getCategoryId() != null) {
				// 从 Map 中取出当前分类对应的属性列表
				List<SysProductProperty> props = propertyMap.get(category.getCategoryId());
				category.setproductPropertyList(props != null ? props : new ArrayList<>());

				// 如果分类还有子节点，递归处理子节点
				if (category.getChildren() != null && !category.getChildren().isEmpty()) {
					find4Property(category.getChildren());
				}
			}
		}
		return dataList;
	}

	@Override
	public Integer findCountByParam(SysCategoryQuery param) {

		return this.sysCategoryMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<SysCategory> findListByPage(SysCategoryQuery param) {
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> this.findListByParam(param));
	}

	@Override
	public Integer add(SysCategory bean) {
		return this.sysCategoryMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<SysCategory> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.sysCategoryMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<SysCategory> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.sysCategoryMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(SysCategory bean, SysCategoryQuery param) {
		StringTools.checkParam(param);
		return this.sysCategoryMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(SysCategoryQuery param) {
		StringTools.checkParam(param);
		return this.sysCategoryMapper.deleteByParam(param);
	}

	@Override
	public SysCategory getSysCategoryByCategoryId(String categoryId) {
		return this.sysCategoryMapper.selectByCategoryId(categoryId);
	}

	@Override
	public Integer updateSysCategoryByCategoryId(SysCategory bean, String categoryId) {
		return this.sysCategoryMapper.updateByCategoryId(bean, categoryId);
	}

	@Override
	public Integer deleteSysCategoryByCategoryId(String categoryId) {
		return this.sysCategoryMapper.deleteByCategoryId(categoryId);
	}

	@Override
	// 新增路径要"取同层最大 sort → 插入 → 改名"多步写，且末尾还要刷新 Redis 快照；
	// 不加事务时中途失败会留下半棵树并与缓存不一致。单条 SQL 的失败率虽低，
	// 但这段代码本来就是"写多张/多步"的语义，事务边界应该显式。
	@Transactional(rollbackFor = Exception.class)
	public void saveCategory(SysCategory bean) {
		// 如果是修改，直接修改分类名
		// 如果是添加， 则pCategoryId为父类id， categoryId为随机生成的五位纯数字，并且sort的值为当前同层级下的最大值+1
		if (bean.getCategoryId() == null) {
			// 新增
			String newId = StringTools.getRandomNumber(Constants.LENGTH_5);
			String pId = bean.getpCategoryId();
			// 获取当前分类下最大的sort的值
			// slect max(sort) from sys_category where pCategoryId = #{bean.CategoryId}
			Integer maxSort = this.sysCategoryMapper.selectMaxSort(pId);
			if (maxSort == null) {
				maxSort = 1; // 如果该层级没有其他分类，默认从1开始
			} else {
				maxSort = maxSort + 1;
			}
			bean.setCategoryId(newId);
			bean.setSort(maxSort);
			bean.setpCategoryId(pId);
			this.sysCategoryMapper.insert(bean);
		}
		this.sysCategoryMapper.updateByCategoryId(bean, bean.getCategoryId());
		// 存入redis
		saveCategoryToRedis();
	}

	@Override
	public void deleteSysCategory(SysCategory bean) {
		// 先查询当前节点的所有直接子节点
		List<SysCategory> children = this.sysCategoryMapper.selectByPCategoryId(bean.getCategoryId());
		// 如果当前节点下还有子节点，则连同子节点一起删除
		if (children != null && !children.isEmpty()){
			for (SysCategory child : children) {
				this.deleteSysCategory(child);
			}
		}
		// 如果当前节点下没有子节点，则直接删除
		this.sysCategoryMapper.deleteByCategoryId(bean.getCategoryId());
		// 存入redis
		saveCategoryToRedis();
	}

	@Override
	public void changeCategorySort(String categoryIds) {
		// categoryIds是以逗号分割的id顺序的新序列
		// 获取新序列
		String[] ids = categoryIds.split(",");
		// 按照id顺序改变旧序列的排序
		// sort从1开始累加
		int sort = 1;
		List<SysCategory> list = new ArrayList<>();
		for (String id : ids){
			SysCategory bean = new SysCategory();
			bean = this.sysCategoryMapper.selectByCategoryId(id);
			bean.setSort(sort++);
			list.add(bean);
		}
		this.sysCategoryMapper.updateBatch(list);
		// 存入redis
		saveCategoryToRedis();
	}

	@Override
	public Integer saveProductProperty(SysProductProperty bean) {
		// 如果属性id为空，则生成长度为10的随机id，并获取当前层级下最大的property_sort值
		if (bean.getPropertyId() == null || bean.getPropertyId().isEmpty()) {
			bean.setPropertyId(StringTools.getRandomNumber(Constants.LENGTH_10));
			Integer maxSort = sysProductPropertyMapper.selectMaxPropertySort(bean.getCategoryId());
			if (maxSort == null) {
				maxSort = 1;
			} else {
				maxSort = maxSort + 1;
			}
			bean.setPropertySort(maxSort);
		}
		return sysProductPropertyMapper.insertOrUpdate(bean);
	}

	@Override
	public Integer delProductProperty(SysProductProperty bean) {
		return sysProductPropertyMapper.deleteByPropertyId(bean.getPropertyId());
	}

	// 将信息存入redis
	private void saveCategoryToRedis(){
		// 创建查询query，按sort升序排列
		SysCategoryQuery query = new SysCategoryQuery();
		query.setOrderBy(com.smartlect.entity.query.SafeSort.of("sort asc"));
		// 查询列表
		List<SysCategory> list = this.sysCategoryMapper.selectList(query);
		redisComponent.saveCategory2Redis(list);
	}

	// 返回数据库中的实时目录，并同步刷新 Redis 快照。
	@Override
	public List<SysCategory> getAllCategoryList() {
		SysCategoryQuery query = new SysCategoryQuery();
		query.setOrderBy(com.smartlect.entity.query.SafeSort.of("sort asc"));
		List<SysCategory> list = this.sysCategoryMapper.selectList(query);
		redisComponent.saveCategory2Redis(list);
		return list;
	}
}
