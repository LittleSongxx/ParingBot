<template>
  <div class="main-content">
    <!-- 页头：说清动态是干什么用的 -->
    <div class="page-head">
      <h2>我的动态</h2>
      <p class="page-tip">
        动态挂在租客档案上，是平台了解你的主要来源：平台会从动态正文里整理你的生活方式，
        匹配时也会参考。挑几条能看出平时怎么过日子的写，比只写「今天天气不错」有用得多。
      </p>
    </div>

    <!-- 动态挂在租客档案上，还没填档案时先把去处指清楚 -->
    <div v-if="!data.hasProfile" class="card block-card">
      <div class="block-title">先补租客档案</div>
      <el-alert
          type="warning"
          :closable="false"
          title="还没有填写租客档案"
          description="动态挂在租客档案上，请先把档案填好保存，再回来发布动态。">
      </el-alert>
      <div class="go-profile">
        <el-button type="primary" @click="router.push('/front/memberProfile')">去填写租客档案</el-button>
      </div>
    </div>

    <template v-else>
      <div class="card block-card">
        <div class="block-head">
          <div class="block-title">写点什么好</div>
          <el-button type="primary" @click="handlePublish">发布动态</el-button>
        </div>
        <div class="tip-item" v-for="item in tipList" :key="item">
          <span class="tip-dot"></span>
          <span>{{ item }}</span>
        </div>
      </div>

      <div v-if="!data.tableData.length" class="card empty-card">
        <div class="empty-icon"><el-icon><ChatLineSquare /></el-icon></div>
        <div class="empty-title">还没有发布过动态</div>
        <div class="empty-desc">点上面的「发布动态」写第一条，把当天真的做了什么写清楚就够了。</div>
      </div>

      <div v-for="item in data.tableData" :key="item.id" class="card moment-card">
        <div class="moment-head">
          <div class="moment-icon"><el-icon><ChatDotRound /></el-icon></div>
          <div class="moment-time">发布于 {{ item.publish_time }}</div>
          <span class="visible-chip" :class="item.visible === '公开' ? 'is-open' : 'is-limited'">
            <el-icon><component :is="item.visible === '公开' ? View : Lock" /></el-icon>
            {{ item.visible }}
          </span>
          <div class="moment-actions">
            <el-button type="primary" link @click="handleEdit(item)">编辑</el-button>
            <el-button type="danger" link @click="del(item)">删除</el-button>
          </div>
        </div>
        <div class="moment-content">{{ item.content }}</div>
        <div v-if="item.image_paths.length" class="moment-images">
          <el-image
              v-for="(image, index) in item.image_paths"
              :key="image"
              :src="image"
              :preview-src-list="item.image_paths"
              :initial-index="index"
              preview-teleported
              fit="cover"
              class="moment-image">
          </el-image>
        </div>
      </div>

      <div class="card pager-card" v-if="data.total > data.pageSize">
        <el-pagination
            v-model:current-page="data.pageNum"
            background
            layout="prev, pager, next"
            :page-size="data.pageSize"
            :total="data.total"
            @current-change="load"
        />
      </div>
    </template>

    <el-dialog class="moment-dialog" :title="data.form.id ? '编辑动态' : '发布动态'" v-model="data.formVisible" width="560px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="80px">
        <el-form-item prop="content" label="动态内容">
          <el-input
              type="textarea"
              :rows="5"
              maxlength="500"
              show-word-limit
              v-model="data.form.content"
              placeholder="例如：周末在家烤了一个芝士蛋糕，第一次做成型，配方贴在下面了"></el-input>
        </el-form-item>
        <el-form-item label="配图">
          <el-upload
              :action="baseUrl + '/files/upload'"
              :headers="uploadHeaders"
              list-type="picture-card"
              :limit="9"
              v-model:file-list="data.fileList"
              :before-upload="beforeUpload"
              :on-success="handleUploadSuccess"
              :on-error="handleUploadError"
              :on-exceed="handleExceed">
            <el-icon><Plus /></el-icon>
          </el-upload>
          <div class="upload-tip">最多 9 张，单张不超过 5MB。删掉的图在保存之后才会从服务器一并清掉。</div>
        </el-form-item>
        <el-form-item label="可见范围">
          <el-radio-group v-model="data.form.visible">
            <el-radio v-for="item in data.visibleOptions" :key="item" :value="item">{{ item }}</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Plus, ChatLineSquare, ChatDotRound, View, Lock } from "@element-plus/icons-vue";
import router from "@/router/index.js";
import request from "@/utils/request.js";

// 上传组件自己发请求，不走 request.js，action 要写完整地址，token 也要在这里手动带上
const baseUrl = import.meta.env.VITE_BASE_URL
const uploadHeaders = { token: JSON.parse(localStorage.getItem('xm-user') || '{}').token || '' }
const formRef = ref()

// 写动态的几条建议，说的都是这一页自己的事
const tipList = [
  "写今天真的做了什么，比写一句心情更容易整理出生活方式。",
  "配图挑能看出场景的，不用摆拍，日常的样子就够用。",
  "发布之后正文和配图都还能改，发布时间不会跟着改。",
  "删掉一条动态，平台不会再从它里面整理生活方式，配图也会一并清掉。"
];

const data = reactive({
  hasProfile: false,
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  visibleOptions: ['公开', '仅匹配室友可见'],
  fileList: [],
  formVisible: false,
  form: {
    id: null,
    content: '',
    visible: '公开'
  },
  rules: {
    content: [{ required: true, message: '请填写动态内容', trigger: 'blur' }]
  }
})

const load = () => {
  request.get('/moment/selectMyPage', {
    params: { page_num: data.pageNum, page_size: data.pageSize }
  }).then(res => {
    if (res.code === '200') {
      data.tableData = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const loadOptions = () => {
  request.get('/moment/visibleOptions').then(res => {
    if (res.code === '200') {
      data.visibleOptions = res.data || []
    }
  })
}

const loadProfile = () => {
  // 先看有没有租客档案：没有的话动态接口会直接报错，页面提前给出该走的那一步
  request.get('/member/my').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    data.hasProfile = !!res.data
    if (data.hasProfile) {
      load()
    }
  })
}

const handlePublish = () => {
  data.form = { id: null, content: '', visible: '公开' }
  data.fileList = []
  data.formVisible = true
}

const handleEdit = (row) => {
  data.form = { id: row.id, content: row.content, visible: row.visible }
  data.fileList = row.image_paths.map(url => ({
    // 文件名取地址最后一段，回显时列表里能看出是哪个文件
    name: url.substring(url.lastIndexOf('/') + 1),
    url
  }))
  data.formVisible = true
}

// 只收图片且不超过 5MB。上传组件自己发请求，校验放在上传之前拦
const beforeUpload = (file) => {
  if (!file.type.startsWith('image/')) {
    ElMessage.error('配图只能上传图片文件')
    return false
  }
  if (file.size / 1024 / 1024 > 5) {
    ElMessage.error('单张图片不能超过 5MB')
    return false
  }
  return true
}

const handleUploadSuccess = (res, file) => {
  if (res.code !== '200') {
    ElMessage.error(res.msg)
    return
  }
  // 上传接口返回的是文件下载地址，点保存时才会把地址写进数据库
  file.url = res.data
}

const handleUploadError = (error, file) => {
  // 上传失败的那张从列表里摘掉，否则保存时会把一个本地预览地址写进数据库
  data.fileList = data.fileList.filter(item => item.uid !== file.uid)
  ElMessage.error('图片上传失败，请检查网络后重试')
}

const handleExceed = () => {
  ElMessage.warning('一条动态最多配 9 张图，想换图请先删掉一张')
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    // 还有图在传的时候先拦住，等地址回来再保存，数据里不会混进本地预览地址
    if (data.fileList.some(file => !file.url || !file.url.startsWith('http'))) {
      ElMessage.warning('还有图片没上传完，等图片都显示出来之后再点保存')
      return
    }
    const payload = {
      content: data.form.content,
      visible: data.form.visible,
      image_paths: data.fileList.map(file => file.url).filter(url => !!url)
    }
    if (data.form.id) {
      request.put('/moment/update', payload, { params: { moment_id: data.form.id } }).then(res => {
        if (res.code === '200') {
          ElMessage.success('动态已更新')
          data.formVisible = false
          load()
        } else {
          ElMessage.error(res.msg)
        }
      })
      return
    }
    request.post('/moment/publish', payload).then(res => {
      if (res.code === '200') {
        ElMessage.success('动态已发布')
        data.formVisible = false
        data.pageNum = 1
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

// 动态删掉之后平台就不会再从它里面提取生活方式标签了，确认框里把这条说清楚
const del = (row) => {
  ElMessageBox.confirm(
      '删除这条动态后，平台不会再从它里面整理你的生活方式，配图也会一并从服务器删掉，您确定吗？',
      '删除确认', { type: 'warning', customClass: 'moment-confirm' }).then(() => {
    request.delete('/moment/delete/' + row.id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

loadOptions()
loadProfile()
</script>

<style scoped>
/* .main-content 的宽度和留白在 front.css 里，这里只补底部留白和页面主色 */
.main-content {
  padding-bottom: 10px;
  --el-color-primary: #1F6F6B;
  --el-color-primary-light-3: #4F8F8A;
  --el-color-primary-light-5: #84B5B2;
  --el-color-primary-light-7: #A9CFCB;
  --el-color-primary-light-8: #C4DCDA;
  --el-color-primary-light-9: #EFF6F5;
  --el-color-primary-dark-2: #24625E;
}

/* 卡片标题统一加粗，发布按钮跟着标题同一行，不加任何装饰线条 */
.block-card {
  margin-top: 12px;
  padding: 20px 24px 22px;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.block-title {
  font-size: 16px;
  font-weight: bold;
  line-height: 20px;
  color: #333;
}
.block-card .el-alert {
  margin-top: 14px;
}
.tip-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  line-height: 22px;
  color: #666;
}
.block-head + .tip-item {
  margin-top: 14px;
}
.tip-item + .tip-item {
  margin-top: 6px;
}
.tip-dot {
  flex: none;
  width: 6px;
  height: 6px;
  margin-top: 8px;
  border-radius: 50%;
  background-color: #B8D9D7;
}
.go-profile {
  padding-top: 16px;
}

/* 一条动态都没有时给一块带图标的空状态，比一行灰字更像一个能动手的地方 */
.empty-card {
  margin-top: 12px;
  padding: 28px 24px 32px;
  text-align: center;
}
.empty-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 12px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #1F6F6B;
  background-color: rgba(31, 111, 107, .1);
}
.empty-title {
  font-size: 15px;
  font-weight: bold;
  color: #333;
}
.empty-desc {
  margin-top: 6px;
  font-size: 13px;
  line-height: 22px;
  color: #999;
}

/* 每条动态一张卡片：头部是发布信息和操作，正文按原样保留换行 */
.moment-card {
  margin-top: 12px;
  padding: 16px 22px 18px;
  border: 1px solid #DFECEB;
  border-radius: 10px;
  box-shadow: 0 1px 2px rgba(31, 111, 107, .05);
  transition: border-color .2s, box-shadow .2s, transform .2s;
}
.moment-card:hover {
  border-color: #CDE3E1;
  box-shadow: 0 8px 20px rgba(31, 111, 107, .1);
  transform: translateY(-2px);
}
.moment-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 12px;
  border-bottom: 1px solid #E4F0EF;
}
.moment-icon {
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  color: #1F6F6B;
  background-color: rgba(31, 111, 107, .1);
}
.moment-time {
  font-size: 13px;
  color: #666;
}
/* 可见范围用自带的配色块，公开用主题色、仅匹配室友可见用灰，扫一眼能分清 */
.visible-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
}
.visible-chip.is-open {
  color: #1F6F6B;
  border: 1px solid #D5E8E6;
  background-color: rgba(31, 111, 107, .08);
}
.visible-chip.is-limited {
  color: #8a8a8a;
  border: 1px solid #eaeaea;
  background-color: #f7f7f7;
}
.moment-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}
.moment-content {
  margin-top: 12px;
  color: #333;
  font-size: 14px;
  line-height: 24px;
  white-space: pre-wrap;
  word-break: break-all;
}
.moment-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 12px;
}
.moment-image {
  width: 104px;
  height: 104px;
  border-radius: 8px;
  border: 1px solid #E6F0EF;
}

.pager-card {
  margin-top: 12px;
  padding: 12px;
  text-align: center;
}
.pager-card .el-pagination {
  justify-content: center;
}

.upload-tip {
  width: 100%;
  color: #999;
  font-size: 12px;
  line-height: 20px;
}

/* 弹窗和确认框都挂在 body 上渲染，主题色变量要按它们自己的类名给，
   写在 .main-content 上的页面作用域盖不到 */
:global(.moment-dialog),
:global(.moment-confirm) {
  --el-color-primary: #1F6F6B;
  --el-color-primary-light-3: #4F8F8A;
  --el-color-primary-light-5: #84B5B2;
  --el-color-primary-light-7: #A9CFCB;
  --el-color-primary-light-8: #C4DCDA;
  --el-color-primary-light-9: #EFF6F5;
  --el-color-primary-dark-2: #24625E;
}

</style>
