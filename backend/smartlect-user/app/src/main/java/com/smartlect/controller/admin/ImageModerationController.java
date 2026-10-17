package com.smartlect.controller.admin;

import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.component.UserTempBanService;
import com.smartlect.entity.dto.BaiduImageCensorResultDTO;
import com.smartlect.entity.query.ImageModerationRecordQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.ImageModerationService;
import com.smartlect.exception.BusinessException;
import com.smartlect.utils.FileUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotNull;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;

@RestController("imageModerationController")
@RequestMapping("/admin/imageModeration")
public class ImageModerationController extends com.smartlect.controller.admin.ABaseController {

    @Resource
    private ImageModerationService imageModerationService;
    @Resource
    private FileUtils fileUtils;
    @Resource
    private UserTempBanService userTempBanService;

    @PostMapping("/loadDataList")
    public ResponseVO loadDataList(ImageModerationRecordQuery query) {
        if (query.getOrderBy() == null) {
            query.setOrderBy(com.smartlect.entity.query.SafeSort.of("create_time desc"));
        }
        return getSuccessResponseVO(imageModerationService.findListByPage(query));
    }

    @PostMapping("/getByRecordId")
    public ResponseVO getByRecordId(Integer recordId) {
        return getSuccessResponseVO(imageModerationService.getByRecordId(recordId));
    }

    @PostMapping("/handleReview")
    @SaCheckPermission(value = AdminPermissions.MODERATION_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO handleReview(Integer recordId, String action, String handleRemark) {
        imageModerationService.handleReview(recordId, action, handleRemark);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/getTempBanInfo")
    public ResponseVO getTempBanInfo(String userId) {
        Long unbanAt = userTempBanService.getUnbanAtMs(userId);
        Map<String, Object> data = new HashMap<>();
        data.put("tempBanned", unbanAt != null);
        data.put("unbanAt", unbanAt);
        return getSuccessResponseVO(data);
    }

    @PostMapping("/unbanUser")
    @SaCheckPermission(value = AdminPermissions.MODERATION_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO unbanUser(String userId) {
        if (!userTempBanService.manualUnban(userId)) {
            throw new BusinessException("该用户当前非临时封禁状态，无法解封");
        }
        return getSuccessResponseVO(null);
    }

    @PostMapping("/censorImage")
    @SaCheckPermission(value = AdminPermissions.MODERATION_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO censorImage(@NotNull MultipartFile file) {
        try {
            BaiduImageCensorResultDTO result = imageModerationService.censorImageBytes(
                    file.getBytes(), "admin-test", "127.0.0.1");
            return getSuccessResponseVO(result);
        } catch (Exception e) {
            throw new BusinessException(StringTools.isEmpty(e.getMessage()) ? "审核失败" : e.getMessage());
        }
    }
}
