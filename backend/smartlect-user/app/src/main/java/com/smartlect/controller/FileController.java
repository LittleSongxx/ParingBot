package com.smartlect.controller;

import com.smartlect.api.dto.ImageUploadResultDTO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.ImageModerationService;
import com.smartlect.utils.FileUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.constraints.NotNull;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import cn.dev33.satoken.annotation.SaCheckLogin;

@RestController("fileController")
@RequestMapping("/file")
@Validated
@Slf4j
public class FileController extends ABaseController{

    @Resource
    private ImageModerationService imageModerationService;

    @Resource
    private FileUtils fileUtils;

    @SaCheckLogin
    @PostMapping("/uploadImage")
    public ResponseVO uploadImage(@NotNull MultipartFile file, Boolean createThumbnail, String scene,
                                  String orderId, HttpServletRequest request) {
        String userId = getTokenUserInfo().getUserId();
        String ip = getClientIp(request);
        ImageUploadResultDTO result = imageModerationService.uploadAndModerate(
                userId, ip, file, createThumbnail, scene, orderId);
        // 合规直传：data 直接返回路径字符串，避免前端解析对象出错
        if (!Boolean.TRUE.equals(result.getPendingReview())) {
            return getSuccessResponseVO(result.getPath());
        }
        return getSuccessResponseVO(result);
    }

    @GetMapping("/getResource")
    public void getResource(HttpServletResponse response, @NotNull String sourceName) throws IOException {
        if(!StringTools.pathIsOK(sourceName)){
            response.sendError(HttpServletResponse.SC_NOT_FOUND);
            return;
        }
        // 只存了另一个变体时（例如商品图只有缩略图）回退到实际存在的那个；长缓存只在真的
        // 找到文件时下发——以前对缺失文件回 200 空体并带 max-age，浏览器会把这个空响应缓存
        // 近一天，表现就是“大图一直加载不出来”。
        File file = fileUtils.resolveReadableStoredFile(sourceName);
        if (file == null) {
            response.sendError(HttpServletResponse.SC_NOT_FOUND);
            return;
        }
        String suffix = StringTools.getFileSuffix(sourceName);
        response.setContentType(resolveImageContentType(suffix));
        response.setHeader("Cache-Control", "max-age=100000");
        writeFile(response, file);
    }

    protected void writeFile(HttpServletResponse response, File file){
        try (OutputStream out = response.getOutputStream();
            FileInputStream in = new FileInputStream(file)) {
                byte[] byteData =  new byte[8192];
                int len = 0;
                while((len = in.read(byteData)) != -1){
                    out.write(byteData,0,len);
                }
                out.flush();
        } catch (Exception e) {
            log.error("读取文件异常", e);
        }
    }

    private String getClientIp(HttpServletRequest request) {
        // 与登录锁定/限流共用同一套信任模型：XFF 第一段可伪造，取最后一跳（IpUtils）
        return com.smartlect.utils.IpUtils.resolveClientIp(request);
    }

    private static String resolveImageContentType(String suffix) {
        if (StringTools.isEmpty(suffix)) {
            return "image/jpeg";
        }
        return switch (suffix.toLowerCase()) {
            case ".jpg", ".jpeg" -> "image/jpeg";
            case ".png" -> "image/png";
            case ".gif" -> "image/gif";
            case ".webp" -> "image/webp";
            case ".bmp" -> "image/bmp";
            default -> "image/jpeg";
        };
    }
}
