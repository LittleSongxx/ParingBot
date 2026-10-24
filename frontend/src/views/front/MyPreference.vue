<template>
  <div class="main-content">
    <!-- 页头：说清「必须」和「加分」的区别；右侧实时显示「必须」项数量，多了少了当场说，不用等保存才报错 -->
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>合住偏好</h2>
        <p class="page-tip">
          「必须」是这个条件不能松口，筛选时一个都不能少；「加分」表示优先满足，候选不够时可以适当放宽。
        </p>
      </div>
      <div class="page-head-action" v-if="data.hasProfile">
        <span class="must-count" :class="countError ? 'is-bad' : 'is-ok'">
          已标「必须」<b>{{ mustCount }}</b> / {{ data.options.dimension_count }} 项，
          {{ countError || '数量正好，保存后这些「必须」项不会被放宽' }}
          （要控制在 {{ data.options.must_count_range.min }} 到 {{ data.options.must_count_range.max }} 个之间）
        </span>
      </div>
    </div>

    <div class="card empty-card" v-if="!data.hasProfile">
      <el-alert
          type="warning"
          :closable="false"
          title="还没有填写租客档案"
          description="合住偏好挂在租客档案上，请先把档案填好保存，再回来设置偏好。">
      </el-alert>
      <div class="go-profile">
        <el-button type="primary" @click="router.push('/front/memberProfile')">去填写租客档案</el-button>
      </div>
    </div>

    <!-- 标了必须但取值对谁都成立的情况要指出来，否则白白占掉一个必须项名额 -->
    <div class="warn-strip" v-if="data.hasProfile && meaningless.length">
      <el-icon class="warn-icon"><WarningFilled /></el-icon>
      <div class="warn-text">
        「{{ meaningless.join('、') }}」标了「必须」，但取值是「不限」「无所谓」或把作息全选上了，
        对谁都成立，不会筛掉任何人，建议改成「加分」。
      </div>
    </div>

    <div class="card form-card" v-if="data.hasProfile">
      <div class="block-title">七个维度</div>
      <el-form ref="formRef" :model="data.form" :rules="data.rules">
        <div class="dim-grid">
          <el-form-item prop="age_min" class="dim-card" :class="dimClass('age')">
            <div class="dim-head">
              <span class="dim-icon"><el-icon><Calendar /></el-icon></span>
              <span class="dim-name">年龄</span>
              <el-radio-group v-model="data.form.age_required" class="dim-required" size="small">
                <el-radio-button value="必须">必须</el-radio-button>
                <el-radio-button value="加分">加分</el-radio-button>
              </el-radio-group>
            </div>
            <div class="dim-body">
              <el-input-number v-model="data.form.age_min" :min="data.options.age_range.min"
                               :max="data.options.age_range.max" controls-position="right" class="num"></el-input-number>
              <span class="dim-sep">到</span>
              <el-input-number v-model="data.form.age_max" :min="data.options.age_range.min"
                               :max="data.options.age_range.max" controls-position="right" class="num"></el-input-number>
              <span class="dim-unit">岁</span>
            </div>
            <div class="dim-tip">对方年龄落在这个区间里才算满足</div>
          </el-form-item>

          <el-form-item prop="budget_min" class="dim-card" :class="dimClass('budget')">
            <div class="dim-head">
              <span class="dim-icon"><el-icon><Wallet /></el-icon></span>
              <span class="dim-name">室友预算</span>
              <el-radio-group v-model="data.form.budget_required" class="dim-required" size="small">
                <el-radio-button value="必须">必须</el-radio-button>
                <el-radio-button value="加分">加分</el-radio-button>
              </el-radio-group>
            </div>
            <div class="dim-body">
              <el-input-number v-model="data.form.budget_min" :min="data.options.budget_range.min" :step="100"
                               :max="data.options.budget_range.max" controls-position="right" class="num"></el-input-number>
              <span class="dim-sep">到</span>
              <el-input-number v-model="data.form.budget_max" :min="data.options.budget_range.min" :step="100"
                               :max="data.options.budget_range.max" controls-position="right" class="num"></el-input-number>
              <span class="dim-unit">元 / 月</span>
            </div>
            <div class="dim-tip">对方的月租预算落在这个区间里才算满足，预算接近才租得起同一档房型</div>
          </el-form-item>

          <el-form-item prop="tidiness_min" class="dim-card" :class="dimClass('tidiness')">
            <div class="dim-head">
              <span class="dim-icon"><el-icon><Brush /></el-icon></span>
              <span class="dim-name">最低整洁度</span>
              <el-radio-group v-model="data.form.tidiness_required" class="dim-required" size="small">
                <el-radio-button value="必须">必须</el-radio-button>
                <el-radio-button value="加分">加分</el-radio-button>
              </el-radio-group>
            </div>
            <div class="dim-body">
              <el-select v-model="data.form.tidiness_min" placeholder="请选择最低整洁度" class="fill">
                <el-option v-for="item in data.options.tidiness_levels" :key="item" :label="item" :value="item"></el-option>
                <el-option label="不限" value="不限"></el-option>
              </el-select>
            </div>
            <div class="dim-tip">对方整洁度不低于这一档才算满足，选「不限」表示不设门槛</div>
          </el-form-item>

          <el-form-item prop="store_scope" class="dim-card" :class="dimClass('store')">
            <div class="dim-head">
              <span class="dim-icon"><el-icon><Location /></el-icon></span>
              <span class="dim-name">门店范围</span>
              <el-radio-group v-model="data.form.store_required" class="dim-required" size="small">
                <el-radio-button value="必须">必须</el-radio-button>
                <el-radio-button value="加分">加分</el-radio-button>
              </el-radio-group>
            </div>
            <div class="dim-body">
              <el-radio-group v-model="data.form.store_scope">
                <el-radio v-for="item in data.options.store_scopes" :key="item" :value="item">{{ item }}</el-radio>
              </el-radio-group>
            </div>
            <div class="dim-tip">同门店 / 同片区按你档案里填的意向门店判断，选「不限」表示全城门店都可以</div>
          </el-form-item>

          <el-form-item prop="schedule_accept" class="dim-card" :class="dimClass('schedule')">
            <div class="dim-head">
              <span class="dim-icon"><el-icon><Moon /></el-icon></span>
              <span class="dim-name">可接受作息</span>
              <el-radio-group v-model="data.form.schedule_required" class="dim-required" size="small">
                <el-radio-button value="必须">必须</el-radio-button>
                <el-radio-button value="加分">加分</el-radio-button>
              </el-radio-group>
            </div>
            <div class="dim-body">
              <el-select v-model="data.form.schedule_accept" multiple placeholder="至少选一个" class="fill">
                <el-option v-for="item in data.options.schedule_types" :key="item" :label="item" :value="item"></el-option>
              </el-select>
            </div>
            <div class="dim-tip">对方作息在选中的这几种里才算满足，三种全选等于不限制</div>
          </el-form-item>

          <el-form-item prop="lease_min" class="dim-card" :class="dimClass('lease')">
            <div class="dim-head">
              <span class="dim-icon"><el-icon><Calendar /></el-icon></span>
              <span class="dim-name">最短租期</span>
              <el-radio-group v-model="data.form.lease_required" class="dim-required" size="small">
                <el-radio-button value="必须">必须</el-radio-button>
                <el-radio-button value="加分">加分</el-radio-button>
              </el-radio-group>
            </div>
            <div class="dim-body">
              <el-select v-model="data.form.lease_min" placeholder="请选择最短租期" class="fill">
                <el-option v-for="item in data.options.lease_terms" :key="item" :label="item" :value="item"></el-option>
                <el-option label="不限" value="不限"></el-option>
              </el-select>
            </div>
            <div class="dim-tip">对方计划租期不短于这一档才算满足，选「不限」表示不设门槛</div>
          </el-form-item>

          <el-form-item prop="pet_accept" class="dim-card" :class="dimClass('pet')">
            <div class="dim-head">
              <span class="dim-icon"><el-icon><Sunny /></el-icon></span>
              <span class="dim-name">宠物态度</span>
              <el-radio-group v-model="data.form.pet_required" class="dim-required" size="small">
                <el-radio-button value="必须">必须</el-radio-button>
                <el-radio-button value="加分">加分</el-radio-button>
              </el-radio-group>
            </div>
            <div class="dim-body">
              <el-radio-group v-model="data.form.pet_accept">
                <el-radio v-for="item in data.options.pet_accepts" :key="item" :value="item">{{ item }}</el-radio>
              </el-radio-group>
            </div>
            <div class="dim-tip">指对室友养宠的接受度：选「不接受」会把养宠的租客排除在外，选「接受」或「无所谓」都不设门槛</div>
          </el-form-item>
        </div>
      </el-form>
      <div class="form-actions">
        <el-button type="primary" @click="save">保存偏好</el-button>
        <el-button @click="loadPreference">重新加载</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import router from "@/router/index.js";
import request from "@/utils/request.js";

const formRef = ref()
// 七个维度按这个顺序展示，标注列名是「编码 + _required」
const DIMENSION_CODES = ['age', 'budget', 'tidiness', 'store', 'schedule', 'lease', 'pet']
const DIMENSION_NAMES = {
  age: '年龄',
  budget: '预算',
  tidiness: '整洁度',
  store: '门店',
  schedule: '作息',
  lease: '租期',
  pet: '宠物态度'
}

const data = reactive({
  hasProfile: false,
  preference: null,
  // 取值清单从后端取，页面不自己维护一份；下面这份默认值只用于首次渲染
  options: {
    tidiness_levels: [],
    lease_terms: [],
    schedule_types: [],
    store_scopes: [],
    pet_accepts: [],
    age_range: { min: 18, max: 80 },
    budget_range: { min: 800, max: 20000 },
    must_count_range: { min: 2, max: 4 },
    dimension_count: 7
  },
  form: {
    age_min: null,
    age_max: null,
    age_required: '加分',
    budget_min: null,
    budget_max: null,
    budget_required: '加分',
    tidiness_min: '',
    tidiness_required: '加分',
    store_scope: '',
    store_required: '加分',
    schedule_accept: [],
    schedule_required: '加分',
    lease_min: '',
    lease_required: '加分',
    pet_accept: '',
    pet_required: '加分'
  },
  rules: {
    age_min: [{ required: true, message: '请填写年龄范围', trigger: 'change' }],
    age_max: [{ required: true, message: '请填写年龄范围', trigger: 'change' }],
    budget_min: [{ required: true, message: '请填写预算范围', trigger: 'change' }],
    budget_max: [{ required: true, message: '请填写预算范围', trigger: 'change' }],
    tidiness_min: [{ required: true, message: '请选择最低整洁度', trigger: 'change' }],
    store_scope: [{ required: true, message: '请选择门店范围', trigger: 'change' }],
    schedule_accept: [{ required: true, type: 'array', message: '请至少选一个可以接受的作息', trigger: 'change' }],
    lease_min: [{ required: true, message: '请选择最短租期', trigger: 'change' }],
    pet_accept: [{ required: true, message: '请选择对室友养宠的态度', trigger: 'change' }]
  }
})

// 卡片边框和底色跟着「必须 / 加分」变化，扫一眼就知道哪几项是硬条件
const dimClass = (code) => (data.form[code + '_required'] === '必须' ? 'is-must' : 'is-bonus')

// 当前标了「必须」的维度数量，页面上实时显示，和保存时后端卡的是同一件事
const mustCount = computed(() =>
    DIMENSION_CODES.filter(code => data.form[code + '_required'] === '必须').length)

const countError = computed(() => {
  const range = data.options.must_count_range
  if (mustCount.value < range.min) {
    return '还差 ' + (range.min - mustCount.value) + ' 项要标成「必须」'
  }
  if (mustCount.value > range.max) {
    return '超出 ' + (mustCount.value - range.max) + ' 项，请把多余的改成「加分」'
  }
  return ''
})

// 取值本身对谁都成立时，「必须」这个标注起不到筛选作用，页面要提醒一句
const noConstraint = (code) => {
  if (code === 'tidiness') {
    return !data.form.tidiness_min || data.form.tidiness_min === '不限'
  }
  if (code === 'lease') {
    return !data.form.lease_min || data.form.lease_min === '不限'
  }
  if (code === 'store') {
    return data.form.store_scope === '不限'
  }
  if (code === 'pet') {
    return data.form.pet_accept !== '不接受'
  }
  if (code === 'schedule') {
    const all = data.options.schedule_types.length
    return all > 0 && data.form.schedule_accept.length === all
  }
  return false
}

const meaningless = computed(() =>
    DIMENSION_CODES
        .filter(code => data.form[code + '_required'] === '必须' && noConstraint(code))
        .map(code => DIMENSION_NAMES[code]))

const fillForm = (preference) => {
  data.form = {
    age_min: preference.age_min,
    age_max: preference.age_max,
    age_required: preference.age_required,
    budget_min: preference.budget_min,
    budget_max: preference.budget_max,
    budget_required: preference.budget_required,
    // 后端把「不设门槛」存成空值，回填时换回下拉框里的「不限」
    tidiness_min: preference.tidiness_min || '不限',
    tidiness_required: preference.tidiness_required,
    store_scope: preference.store_scope,
    store_required: preference.store_required,
    schedule_accept: preference.schedule_accept || [],
    schedule_required: preference.schedule_required,
    lease_min: preference.lease_min || '不限',
    lease_required: preference.lease_required,
    pet_accept: preference.pet_accept,
    pet_required: preference.pet_required
  }
}

const loadPreference = () => {
  request.get('/preference/my').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    data.preference = res.data
    if (res.data) {
      fillForm(res.data)
    }
  })
}

const load = () => {
  request.get('/preference/options').then(res => {
    if (res.code === '200') {
      data.options = res.data
    } else {
      ElMessage.error(res.msg)
    }
  })
  // 先看有没有租客档案：没有的话偏好接口会直接报错，页面提前给出该走的那一步
  request.get('/member/my').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    data.hasProfile = !!res.data
    if (data.hasProfile) {
      loadPreference()
    }
  })
}

const save = () => {
  if (countError.value) {
    ElMessage.warning('标为「必须」的维度要在 ' + data.options.must_count_range.min + ' 到 '
        + data.options.must_count_range.max + ' 个之间，现在有 ' + mustCount.value + ' 个')
    return
  }
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    request.post('/preference/saveMy', data.form).then(res => {
      if (res.code === '200') {
        ElMessage.success('偏好已保存')
        data.preference = res.data
        fillForm(res.data)
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

load()
</script>

<style scoped>
/* .main-content 的宽度和留白在 front.css 里，这里只补底部留白 */
/* Element Plus 自带一套蓝色主色，按钮、输入框聚焦、下拉高亮都会露出蓝色，
   这里把主色和它的深浅梯度一起换成主题色，页面里才不会掺进第二种颜色 */
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

/* 页头右侧的「必须」项计数：数量对了显示绿色，多了少了显示红色，保存前就能看到 */
.must-count {
  font-size: 13px;
  line-height: 20px;
}
.must-count b {
  font-size: 16px;
}
.must-count.is-ok {
  color: #67c23a;
}
.must-count.is-bad {
  color: #d94a5f;
}

.empty-card {
  margin-top: 12px;
  padding: 20px 24px 24px;
}
.go-profile {
  padding-top: 16px;
}

/* 标了「必须」却没起到筛人作用时单独铺一条提醒，颜色比正文重一点 */
.warn-strip {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  padding: 12px 16px;
  border: 1px solid #DDF0EF;
  border-radius: 10px;
  background-color: #F7FDFD;
  font-size: 13px;
  color: #2A7F7A;
}
.warn-icon {
  flex: none;
  margin-top: 4px;
  color: #7FC4BF;
}
.warn-text {
  line-height: 22px;
}

.form-card {
  margin-top: 12px;
  padding: 20px 24px 24px;
}

/* 卡片标题统一加粗，不加任何装饰线条 */
.block-title {
  margin-bottom: 14px;
  font-size: 16px;
  font-weight: bold;
  line-height: 20px;
  color: #333;
}

/* 七个维度两列铺开，窄屏下退回一列 */
.dim-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

/* 每个维度一张卡片，边框和底色跟着「必须 / 加分」变化，宽度和其它卡片一致 */
.el-form-item.dim-card {
  position: relative;
  overflow: hidden;
  margin-bottom: 0;
  padding: 14px 16px 18px;
  border: 1px solid #DFECEB;
  border-radius: 10px;
  background-color: #fff;
  transition: border-color .2s, box-shadow .2s;
}
.el-form-item.dim-card:hover {
  border-color: #CDE3E1;
  box-shadow: 0 6px 16px rgba(31, 111, 107, .1);
}

.el-form-item.dim-card.is-must {
  border-color: #CDE3E1;
  background-color: #FAFDFD;
}

.dim-head {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  line-height: 20px;
}
.dim-icon {
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
.dim-name {
  flex: 1;
  min-width: 0;
  font-size: 15px;
  font-weight: bold;
  color: #333;
}
/* 选中「必须」铺主题色、选中「加分」铺浅一档的底色配深色字，和卡片边框是同一个含义。
   这几个变量 Element Plus 定义在按钮自己身上，覆盖要落在 .el-radio-button 上才生效 */
.dim-card.is-must .el-radio-button {
  --el-radio-button-checked-bg-color: #1F6F6B;
  --el-radio-button-checked-border-color: #1F6F6B;
}
.dim-card.is-bonus .el-radio-button {
  --el-radio-button-checked-bg-color: #DFECEB;
  --el-radio-button-checked-border-color: #C9DDDC;
  --el-radio-button-checked-text-color: #2A7F7A;
}

.dim-body {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
  margin-top: 12px;
  line-height: 20px;
}
.num {
  width: 108px;
}
.fill {
  width: 100%;
}
.dim-sep,
.dim-unit {
  color: #999;
}
.dim-tip {
  width: 100%;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #E4F0EF;
  color: #999;
  font-size: 12px;
  line-height: 20px;
}

.form-actions {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid #DFECEB;
  text-align: center;
}

/* 窄屏下卡片退回一列，两个输入框并排会把区间挤得看不出来 */
@media (max-width: 1100px) {
  .dim-grid {
    grid-template-columns: 1fr;
  }
}
</style>