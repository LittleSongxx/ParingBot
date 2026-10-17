package com.smartlect.controller.admin;


import cn.dev33.satoken.annotation.SaCheckPermission;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.utils.FileUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
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

@RestController("adminFileController")
@RequestMapping("/admin/file")
@Validated
@Slf4j
public class FileController extends com.smartlect.controller.admin.ABaseController{

    @Resource
    private FileUtils fileUtils;

    @PostMapping("/uploadImage")
    @SaCheckPermission(value = AdminPermissions.PRODUCT_MANAGE, orRole = "SUPER_ADMIN", type = "admin")
    public ResponseVO uploadImage(@NotNull MultipartFile file, Boolean createThumbnail) {
        String filePath = fileUtils.uploadImage(file, createThumbnail);
        return getSuccessResponseVO(filePath);
    }

    @GetMapping("/getResource")
    public void getResource(HttpServletResponse response, @NotNull String sourceName) throws IOException {
        if(!StringTools.pathIsOK(sourceName)){
            response.sendError(HttpServletResponse.SC_NOT_FOUND);
            return;
        }
        // 与用户端 /file/getResource 同一套语义：只存了另一个变体时回退到存在的那一个，
        // 真的缺失就回 404，绝不回 200 空体（空体带长缓存会让浏览器把破图缓存近一天）。
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
