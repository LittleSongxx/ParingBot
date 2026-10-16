package com.smartlect.api.dubbo;

import com.smartlect.api.dto.UserAddressQueryDTO;
import com.smartlect.api.dto.UserIdsDTO;
import com.smartlect.api.dto.UserJoinCountDTO;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.api.vo.UserBriefVO;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;

import java.util.List;

/**
 * 用户域内部 Dubbo 契约（取代 UserDubboService，方法签名一致；HTTP /internal/user
 * 端点保留给 assistant 与运维工具，双通道共用同一 Service 层）。
 *
 * <p>getAddress 的 userId 显式参数延续 HTTP 通道「委托用户头」的信任边界语义：
 * provider 校验其与 DTO 内 userId 一致，防止跨用户查询。</p>
 */
public interface UserDubboService {

    ResponseVO<UserAddressVO> getAddress(UserAddressQueryDTO dto, String userId);

    ResponseVO<List<String>> listAllUserIds();

    ResponseVO<List<UserBriefVO>> listBriefByUserIds(UserIdsDTO dto);

    ResponseVO<Integer> countByJoinDate(UserJoinCountDTO dto);
}
