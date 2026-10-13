package com.smartlect.biz.impl;

import com.smartlect.component.BaiduImageCensorComponent;
import com.smartlect.component.ImageCensorRateLimitService;
import com.smartlect.component.UserTempBanService;
import com.smartlect.entity.dto.BaiduImageCensorResultDTO;
import com.smartlect.api.dto.ImageUploadResultDTO;
import com.smartlect.api.dubbo.OrderDubboService;
import org.apache.dubbo.config.annotation.DubboReference;
import com.smartlect.api.dto.OrderIdDTO;
import com.smartlect.api.support.FeignResponseSupport;
import com.smartlect.api.vo.OrderBriefVO;
import com.smartlect.api.enums.ImageModerationSceneEnum;
import com.smartlect.api.enums.ImageModerationStatusEnum;
import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.po.ImageModerationRecord;
import com.smartlect.entity.query.ImageModerationRecordQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.ImageModerationRecordMapper;
import com.smartlect.biz.ImageModerationService;
import com.smartlect.utils.FileUtils;
import com.smartlect.utils.ImageCompressUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.util.Arrays;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import com.smartlect.utils.PageUtils;

@Service("imageModerationService")
@Slf4j
public class ImageModerationServiceImpl implements ImageModerationService {

    private static final int TEMP_BAN_HOURS = 2;
    @Resource
    private FileUtils fileUtils;
    @Resource
    private BaiduImageCensorComponent baiduImageCensorComponent;
    @Resource
    private ImageCensorRateLimitService imageCensorRateLimitService;
    @Resource
    private UserTempBanService userTempBanService;
    @Resource
    private ImageModerationRecordMapper<ImageModerationRecord, ImageModerationRecordQuery> imageModerationRecordMapper;
    @DubboReference
    private OrderDubboService orderFeignClient;
    @Resource
    private FeignResponseSupport feignResponseSupport;
    @Value("${image-moderation.orphan-upload-hours:24}")
    private int orphanUploadHours;

    @Override
    public ImageUploadResultDTO uploadAndModerate(String userId, String userIp, MultipartFile file,
                                                  Boolean createThumbnail, String scene, String orderId) {
        ImageModerationSceneEnum sceneEnum = ImageModerationSceneEnum.getByCode(scene);
        if (sceneEnum == null) {
            throw new BusinessException(600, "不支持的图片使用场景");
        }
        ImageCompressUtils.PreparedImage prepared = fileUtils.prepareUploadImage(file);
        byte[] censorBytes = ImageCompressUtils.prepareForBaiduCensor(prepared.getData());
        BaiduImageCensorResultDTO result = censorImageBytes(censorBytes, userId, userIp);
        if (result.isPass()) {
            String path = fileUtils.savePreparedImage(prepared, createThumbnail);
            return new ImageUploadResultDTO(path, false);
        }
        return handleCensorResult(userId, userIp, prepared, sceneEnum, orderId, result);
    }

    @Override
    public BaiduImageCensorResultDTO censorImageBytes(byte[] imageBytes, String userId, String userIp) {
        if (baiduImageCensorComponent.isEnabled()) {
            imageCensorRateLimitService.checkUserAndIp(userId, userIp);
        }
        return baiduImageCensorComponent.censorImage(imageBytes);
    }

    private ImageUploadResultDTO handleCensorResult(
            String userId, String userIp, ImageCompressUtils.PreparedImage prepared,
            ImageModerationSceneEnum scene, String orderId, BaiduImageCensorResultDTO result) {
        if (result.isSuspect()) {
            String quarantinePath = fileUtils.saveModerationQuarantineImage(prepared);
            try {
                saveRecord(userId, userIp, quarantinePath, scene.getCode(), orderId, result,
                        ImageModerationStatusEnum.PENDING.getStatus());
            } catch (RuntimeException exception) {
                fileUtils.deleteUserImageWithThumbnailQuietly(quarantinePath);
                throw exception;
            }
            if (ImageModerationSceneEnum.COMMENT.equals(scene)
                    && !StringTools.isEmpty(orderId)) {
                return new ImageUploadResultDTO(quarantinePath, true);
            }
            Map<String, Object> data = new HashMap<>();
            data.put("errorType", "IMAGE_SUSPECT");
            throw new BusinessException(600, "图片存在违规风险，已提交人工审核，请更换图片后再试", data);
        }
        if (result.isReject()) {
            saveRecord(userId, userIp, null, scene.getCode(), orderId, result,
                    ImageModerationStatusEnum.VIOLATION.getStatus());
            long unbanAt = userTempBanService.banUserHours(userId, TEMP_BAN_HOURS);
            Map<String, Object> data = new HashMap<>();
            data.put("errorType", "IMAGE_REJECT_BANNED");
            data.put("unbanAt", unbanAt);
            String msg = "图片涉嫌违规，上传已拒绝，" + userTempBanService.buildTempBanMessage(unbanAt);
            throw new BusinessException(600, msg, data);
        }
        throw new BusinessException("图片审核未通过，请更换图片后重试");
    }

    private ImageModerationRecord saveRecord(
            String userId, String userIp, String imagePath, String scene, String orderId,
            BaiduImageCensorResultDTO result, Integer status) {
        ImageModerationRecord record = new ImageModerationRecord();
        record.setUserId(userId);
        record.setUserIp(userIp);
        record.setImagePath(imagePath);
        record.setScene(scene);
        record.setOrderId(orderId);
        record.setConclusionType(result.getConclusionType());
        record.setConclusion(result.getConclusion());
        record.setBaiduResponse(result.getRawResponse());
        record.setStatus(status);
        record.setCreateTime(new Date());
        imageModerationRecordMapper.insert(record);
        return record;
    }

    @Override
    public List<ImageModerationRecord> findListByParam(ImageModerationRecordQuery param) {
        return imageModerationRecordMapper.selectList(param);
    }

    @Override
    public PaginationResultVO<ImageModerationRecord> findListByPage(ImageModerationRecordQuery param) {
        return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> findListByParam(param));
    }

    @Override
    public ImageModerationRecord getByRecordId(Integer recordId) {
        return imageModerationRecordMapper.selectByRecordId(recordId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void handleReview(Integer recordId, String action, String handleRemark) {
        ImageModerationRecord record = getByRecordId(recordId);
        if (record == null) {
            throw new BusinessException("审核记录不存在");
        }
        if (!ImageModerationStatusEnum.PENDING.getStatus().equals(record.getStatus())) {
            throw new BusinessException("该记录已处理");
        }
        ImageModerationRecord patch = new ImageModerationRecord();
        patch.setHandleTime(new Date());
        patch.setHandleRemark(handleRemark);
        switch (action == null ? "" : action) {
            case "approve" -> {
                patch.setStatus(ImageModerationStatusEnum.APPROVED.getStatus());
            }
            case "dismiss" -> patch.setStatus(ImageModerationStatusEnum.DISMISSED.getStatus());
            case "ban_temp" -> patch.setStatus(ImageModerationStatusEnum.VIOLATION.getStatus());
            case "ban_perm" -> patch.setStatus(ImageModerationStatusEnum.VIOLATION.getStatus());
            default -> throw new BusinessException("无效的处理动作");
        }
        int updated = imageModerationRecordMapper.updateByRecordIdIfPending(patch, recordId);
        if (updated != 1) {
            throw new BusinessException("该记录已处理");
        }
        switch (action == null ? "" : action) {
            case "approve" -> onCommentRecordApproved(record);
            case "dismiss" -> onCommentRecordRejected(record, action);
            case "ban_temp" -> {
                userTempBanService.banUserHours(record.getUserId(), TEMP_BAN_HOURS);
                onCommentRecordRejected(record, action);
            }
            case "ban_perm" -> {
                userTempBanService.banUserPermanent(record.getUserId());
                onCommentRecordRejected(record, action);
            }
            default -> { }
        }
    }

    private void onCommentRecordApproved(ImageModerationRecord record) {
        if (!isCommentPendingReview(record)) {
            return;
        }
        String orderId = record.getOrderId();
        if (countPendingCommentModerationRecords(orderId) > 0) {
            return;
        }
        publishPendingOrderComment(orderId);
    }

    private void onCommentRecordRejected(ImageModerationRecord record, String action) {
        if (!isCommentPendingReview(record)) {
            return;
        }
        rejectPendingOrderComment(record.getOrderId(), action);
    }

    private boolean isCommentPendingReview(ImageModerationRecord record) {
        return ImageModerationSceneEnum.COMMENT.getCode().equals(record.getScene())
                && !StringTools.isEmpty(record.getOrderId());
    }

    private int countPendingCommentModerationRecords(String orderId) {
        ImageModerationRecordQuery query = new ImageModerationRecordQuery();
        query.setOrderId(orderId);
        query.setScene(ImageModerationSceneEnum.COMMENT.getCode());
        query.setStatus(ImageModerationStatusEnum.PENDING.getStatus());
        return imageModerationRecordMapper.selectCount(query);
    }

    private void publishPendingOrderComment(String orderId) {
        // 评论发布属 order 域；审核通过后由运营在订单侧处理或后续 Feign 补齐
        log.warn("审核通过后发布待审评论需订单服务配合，已跳过自动发布 orderId={}", orderId);
    }

    private void rejectPendingOrderComment(String orderId, String action) {
        log.warn("驳回待审评论需订单服务配合，仅清理本域审核记录 orderId={} action={}", orderId, action);
        dismissSiblingPendingRecords(orderId, action);
    }

    private void dismissSiblingPendingRecords(String orderId, String action) {
        ImageModerationRecordQuery query = new ImageModerationRecordQuery();
        query.setOrderId(orderId);
        query.setScene(ImageModerationSceneEnum.COMMENT.getCode());
        query.setStatus(ImageModerationStatusEnum.PENDING.getStatus());
        List<ImageModerationRecord> pendingList = imageModerationRecordMapper.selectList(query);
        Integer targetStatus = "dismiss".equals(action)
                ? ImageModerationStatusEnum.DISMISSED.getStatus()
                : ImageModerationStatusEnum.VIOLATION.getStatus();
        for (ImageModerationRecord item : pendingList) {
            ImageModerationRecord patch = new ImageModerationRecord();
            patch.setStatus(targetStatus);
            patch.setHandleTime(new Date());
            patch.setHandleRemark("关联订单评论复核一并处理");
            imageModerationRecordMapper.updateByRecordId(patch, item.getRecordId());
            if (FileUtils.isModerationQuarantinePath(item.getImagePath())) {
                fileUtils.deleteStoredFileQuietly(item.getImagePath());
            }
        }
    }

    private void deleteAllCommentImagesQuietly(String commentImages) {
        for (String path : splitImagePaths(commentImages)) {
            fileUtils.deleteUserImageWithThumbnailQuietly(path);
        }
    }

    @Override
    public int cleanupOrphanedCommentUploads() {
        ImageModerationRecordQuery query = new ImageModerationRecordQuery();
        query.setScene(ImageModerationSceneEnum.COMMENT.getCode());
        query.setStatus(ImageModerationStatusEnum.PENDING.getStatus());
        List<ImageModerationRecord> pendingList = imageModerationRecordMapper.selectList(query);
        long cutoffMs = System.currentTimeMillis() - (long) orphanUploadHours * 3600_000L;
        int cleaned = 0;
        for (ImageModerationRecord record : pendingList) {
            if (record.getCreateTime() != null && record.getCreateTime().getTime() > cutoffMs) {
                continue;
            }
            if (!isOrphanCommentUpload(record)) {
                continue;
            }
            ImageModerationRecord patch = new ImageModerationRecord();
            patch.setStatus(ImageModerationStatusEnum.DISMISSED.getStatus());
            patch.setHandleTime(new Date());
            patch.setHandleRemark("超时未提交评价，自动清理");
            int updated = imageModerationRecordMapper.updateByRecordIdIfPending(patch, record.getRecordId());
            if (updated != 1) {
                continue;
            }
            if (FileUtils.isModerationQuarantinePath(record.getImagePath())) {
                fileUtils.deleteStoredFileQuietly(record.getImagePath());
            }
            cleaned++;
        }
        if (cleaned > 0) {
            log.info("清理孤立评论疑似图片 {} 条", cleaned);
        }
        return cleaned;
    }

    private boolean isOrphanCommentUpload(ImageModerationRecord record) {
        String orderId = record.getOrderId();
        if (StringTools.isEmpty(orderId)) {
            return true;
        }
        try {
            OrderBriefVO order = feignResponseSupport.call(
                    () -> orderFeignClient.getOrder(new OrderIdDTO(orderId)),
                    "查询订单失败");
            // 订单不存在视为孤立；存在则保守不删（评论状态跨服务暂不可见）
            return order == null;
        } catch (Exception e) {
            log.warn("判断孤立评论上传失败 orderId={}", orderId, e);
            return false;
        }
    }


    public static List<String> splitImagePaths(String commentImages) {
        if (StringTools.isEmpty(commentImages)) {
            return List.of();
        }
        return Arrays.stream(commentImages.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .collect(Collectors.toList());
    }

    @Override
    public boolean containsQuarantinePath(String commentImages) {
        return splitImagePaths(commentImages).stream().anyMatch(FileUtils::isModerationQuarantinePath);
    }


}
