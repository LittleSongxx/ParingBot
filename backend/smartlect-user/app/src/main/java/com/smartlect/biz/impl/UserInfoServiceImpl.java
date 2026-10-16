package com.smartlect.biz.impl;

import java.util.List;

import com.smartlect.component.RedisComponent;
import com.smartlect.api.enums.UserSexEnum;
import com.smartlect.api.enums.UserStatusEnum;
import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.exception.BusinessException;
import jakarta.annotation.Resource;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.query.UserInfoQuery;
import com.smartlect.entity.po.UserInfo;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.mappers.UserInfoMapper;
import com.smartlect.service.PasswordService;
import com.smartlect.biz.UserInfoService;
import com.smartlect.utils.StringTools;
import com.smartlect.utils.PageUtils;

@Service("userInfoService")
public class UserInfoServiceImpl implements UserInfoService {

	/** 邮件验证码最大尝试次数（安全码不作无限制校验）。 */
	private static final int EMAIL_CODE_MAX_ATTEMPTS = 5;

	@Resource
	private UserInfoMapper<UserInfo, UserInfoQuery> userInfoMapper;
    @Autowired
    private RedisComponent redisComponent;

	@Resource
	private PasswordService passwordService;

	@Resource
	private AppConfig appConfig;

	@Override
	public List<UserInfo> findListByParam(UserInfoQuery param) {
		return this.userInfoMapper.selectList(param);
	}

	@Override
	public Integer findCountByParam(UserInfoQuery param) {
		return this.userInfoMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<UserInfo> findListByPage(UserInfoQuery param) {
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> this.findListByParam(param));
	}

	@Override
	public Integer add(UserInfo bean) {
		return this.userInfoMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<UserInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.userInfoMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<UserInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.userInfoMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(UserInfo bean, UserInfoQuery param) {
		StringTools.checkParam(param);
		return this.userInfoMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(UserInfoQuery param) {
		StringTools.checkParam(param);
		return this.userInfoMapper.deleteByParam(param);
	}

	@Override
	public UserInfo getUserInfoByUserId(String userId) {
		return this.userInfoMapper.selectByUserId(userId);
	}

	@Override
	public Integer updateUserInfoByUserId(UserInfo bean, String userId) {
		return this.userInfoMapper.updateByUserId(bean, userId);
	}

	@Override
	public Integer deleteUserInfoByUserId(String userId) {
		return this.userInfoMapper.deleteByUserId(userId);
	}

	@Override
	public UserInfo getUserInfoByEmail(String email) {
		return this.userInfoMapper.selectByEmail(email);
	}

	@Override
	public Integer updateUserInfoByEmail(UserInfo bean, String email) {
		return this.userInfoMapper.updateByEmail(bean, email);
	}

	@Override
	public Integer deleteUserInfoByEmail(String email) {
		return this.userInfoMapper.deleteByEmail(email);
	}

	@Override
	public UserInfo getUserInfoByNickName(String nickName) {
		return this.userInfoMapper.selectByNickName(nickName);
	}

	@Override
	public Integer updateUserInfoByNickName(UserInfo bean, String nickName) {
		return this.userInfoMapper.updateByNickName(bean, nickName);
	}

	@Override
	public Integer deleteUserInfoByNickName(String nickName) {
		return this.userInfoMapper.deleteByNickName(nickName);
	}

	@Override
	public void register(String email, String nickName, String registerPassword, String checkCode) {
		// 验证码校验（含失败次数上限：6 位数字不允许无限次尝试，超限作废并逼迫重新获取）
		redisComponent.verifyEmailCode(email, checkCode, EMAIL_CODE_MAX_ATTEMPTS);
		createEnabledUser(email, nickName, registerPassword);
		redisComponent.cleanEmailCode(email);
	}

	@Override
	public void registerVerified(String email, String nickName, String registerPassword) {
		createEnabledUser(email, nickName, registerPassword);
	}

	private void createEnabledUser(String email, String nickName, String registerPassword) {
		if (appConfig.isTrialLockPublicRegister()) {
			throw new BusinessException(TrialIdentities.REGISTER_LOCKED);
		}
		if (TrialIdentities.isPublishedDemoEmail(email)
				|| TrialIdentities.USER_NICK.equals(nickName)
				|| TrialIdentities.SHOPPER_NICK.equals(nickName)) {
			throw new BusinessException(TrialIdentities.REGISTER_LOCKED);
		}
		UserInfo userInfo = this.getUserInfoByEmail(email);
		if (userInfo != null) {
			throw new BusinessException("注册失败：请检查输入或稍后重试");  // 邮箱枚举缓解：不暴露账号存在性
		}
		userInfo = new UserInfo();
		userInfo.setEmail(email);
		userInfo.setNickName(nickName);
		userInfo.setPassword(passwordService.encode(registerPassword));
		userInfo.setUserId(StringTools.getRandomNumber(10));
		userInfo.setSex(UserSexEnum.SECRECY.getType());
		userInfo.setJoinTime(StringTools.getCurrentDate());
		userInfo.setStatus(UserStatusEnum.ENABLE.getStatus());
		this.userInfoMapper.insert(userInfo);
	}

	@Override
    public void updateUserInfo(String userId, String avatar, @NotEmpty String nickName, @NotNull Integer sex) {
		UserInfo current = this.getUserInfoByUserId(userId);
		if (current != null && TrialIdentities.isPublishedDemoUser(current.getUserId(), current.getEmail())) {
			throw new BusinessException(publishedIdentityDenied(current.getUserId(), current.getEmail()));
		}
		UserInfo userInfo = new UserInfo();
		userInfo.setAvatar(avatar);
		userInfo.setNickName(nickName);
		userInfo.setSex(sex);
		this.userInfoMapper.updateByUserId(userInfo, userId);
		// 更新token
		redisComponent.updateUser(userId);
    }

	@Override
	public void updatePassword(String userId, String oldPassword, String password) {
		UserInfo userInfo = this.getUserInfoByUserId(userId);
		if (userInfo != null && TrialIdentities.isPublishedDemoUser(userInfo.getUserId(), userInfo.getEmail())) {
			throw new BusinessException(publishedIdentityDenied(userInfo.getUserId(), userInfo.getEmail()));
		}
		if (!passwordService.matches(oldPassword, userInfo.getPassword())) {
			throw new BusinessException("旧密码输入错误");
		}
		if (passwordService.matches(password, userInfo.getPassword())){
			throw new BusinessException("新密码不能与旧密码相同");
		}
		userInfo.setPassword(passwordService.encode(password));
		this.userInfoMapper.updateByUserId(userInfo, userId);
		// 删除token
		redisComponent.cleanAllToken(userId);
	}

	// 找回密码
	@Override
	public void forgetPassword(String email, String newPassword, String checkCode) {
		if (TrialIdentities.isPublishedDemoEmail(email)) {
			throw new BusinessException(TrialIdentities.isShopperEmail(email)
					? TrialIdentities.SHOPPER_DENIED : TrialIdentities.USER_DENIED);
		}
		// 判断当前用户是否已注册
		if (this.getUserInfoByEmail(email) == null) {
			throw new BusinessException("如该邮箱已注册，重置邮件已发送");  // 邮箱枚举缓解：不暴露账号不存在
		}
		// 验证码校验（含失败次数上限：6 位数字不允许无限次尝试，超限作废并逼迫重新获取）
		redisComponent.verifyEmailCode(email, checkCode, EMAIL_CODE_MAX_ATTEMPTS);
		UserInfo userInfo = this.getUserInfoByEmail(email);
		userInfo.setPassword(passwordService.encode(newPassword));
		this.userInfoMapper.updateByEmail(userInfo, email);
		redisComponent.cleanAllToken(userInfo.getUserId());
	}

	private static String publishedIdentityDenied(String userId, String email) {
		return TrialIdentities.isShopperUserId(userId) || TrialIdentities.isShopperEmail(email)
				? TrialIdentities.SHOPPER_DENIED : TrialIdentities.USER_DENIED;
	}
}
