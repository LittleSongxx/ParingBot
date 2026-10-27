import { createRouter, createWebHistory } from 'vue-router'

import Login from '@/views/Login.vue'
import Register from '@/views/Register.vue'
import FourOFour from '@/views/404.vue'

import ModelConfig from '@/views/manager/ModelConfig.vue'
import Prompt from '@/views/manager/Prompt.vue'
import AgentDefinition from '@/views/manager/AgentDefinition.vue'
import FunctionTool from '@/views/manager/FunctionTool.vue'
import ToolCallLog from '@/views/manager/ToolCallLog.vue'
import MatchTrace from '@/views/manager/MatchTrace.vue'
import Home from '@/views/manager/Home.vue'
import User from '@/views/manager/User.vue'
import SysConfig from '@/views/manager/SysConfig.vue'
import Member from '@/views/manager/Member.vue'
import InterestTag from '@/views/manager/InterestTag.vue'
import Person from '@/views/manager/Person.vue'
import Password from '@/views/manager/Password.vue'

import FrontHome from '@/views/front/Home.vue'
import FrontMemberProfile from '@/views/front/MemberProfile.vue'
import FrontMyPreference from '@/views/front/MyPreference.vue'
import FrontMyMoment from '@/views/front/MyMoment.vue'
import FrontMyPortrait from '@/views/front/MyPortrait.vue'
import FrontMyCandidate from '@/views/front/MyCandidate.vue'
import FrontMyAudit from '@/views/front/MyAudit.vue'
import FrontMyMatch from '@/views/front/MyMatch.vue'
import FrontPerson from '@/views/front/Person.vue'
import FrontPassword from '@/views/front/Password.vue'


const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    // 打开站点先到登录页，登录成功后按账号角色分流到对应的那一端
    { path: '/', redirect: '/login' },
    {
      // 管理端布局：ADMIN 账号登录后进入，左侧菜单在 Manager.vue 里按角色渲染
      path: '/manager',
      component: () => import('@/views/Manager.vue'),
      children: [
        { path: 'home', meta: { name: '系统首页' }, component: () => Home,  },
        { path: 'user', meta: { name: '用户管理', requiresAdmin: true }, component: () => User, },
        { path: 'sysConfig', meta: { name: '系统参数', requiresAdmin: true }, component: () => SysConfig, },
        { path: 'modelConfig', meta: { name: 'AI模型配置', requiresAdmin: true }, component: () => ModelConfig, },
        { path: 'prompt', meta: { name: 'Prompt模板', requiresAdmin: true }, component: () => Prompt, },
        { path: 'agentDefinition', meta: { name: '子 Agent 定义', requiresAdmin: true }, component: () => AgentDefinition, },
        { path: 'functionTool', meta: { name: '工具中心', requiresAdmin: true }, component: () => FunctionTool, },
        { path: 'toolCallLog', meta: { name: '工具调用日志', requiresAdmin: true }, component: () => ToolCallLog, },
        { path: 'matchTrace', meta: { name: '调度时间线', requiresAdmin: true }, component: () => MatchTrace, },
        { path: 'member', meta: { name: '租客管理', requiresAdmin: true }, component: () => Member, },
        { path: 'interestTag', meta: { name: '兴趣标签', requiresAdmin: true }, component: () => InterestTag, },
        { path: 'person', meta: { name: '个人资料' }, component: () => Person, },
        { path: 'password', meta: { name: '修改密码' }, component: () => Password, },
      ]
    },
    {
      // 用户端布局：USER 账号登录后进入，顶部菜单在 Front.vue 里按登录状态渲染
      path: '/front',
      component: () => import('@/views/Front.vue'),
      children: [
        // 用户端是租客区域，进这些页面都要先登录
        { path: 'home', meta: { name: '首页', requiresUser: true }, component: () => FrontHome,  },
        { path: 'memberProfile', meta: { name: '租客档案', requiresUser: true }, component: () => FrontMemberProfile,  },
        { path: 'myPreference', meta: { name: '合住偏好', requiresUser: true }, component: () => FrontMyPreference,  },
        { path: 'myMoment', meta: { name: '我的动态', requiresUser: true }, component: () => FrontMyMoment,  },
        { path: 'myMatch', meta: { name: '智能匹配', requiresUser: true }, component: () => FrontMyMatch,  },
        { path: 'myPortrait', meta: { name: '画像结果', requiresUser: true }, component: () => FrontMyPortrait,  },
        { path: 'myCandidate', meta: { name: '候选结果', requiresUser: true }, component: () => FrontMyCandidate,  },
        { path: 'myAudit', meta: { name: '审核结果', requiresUser: true }, component: () => FrontMyAudit,  },
        { path: 'person', meta: { name: '个人中心', requiresUser: true }, component: () => FrontPerson,  },
        { path: 'password', meta: { name: '修改密码', requiresUser: true }, component: () => FrontPassword,  },
      ]
    },
    { path: '/login', component: () => Login },
    { path: '/register', component: () => Register },
    { path: '/404', component: () => FourOFour },
    { path: '/:pathMatch(.*)', redirect: '/404' }
  ],
  // 换页时把视口带回页面顶部；返回上一页时还原原来的位置
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      // 页面组件按需加载，等挂载完成后再滚动，位置才不会被当前页面高度截断
      return new Promise((resolve) => {
        setTimeout(() => resolve(savedPosition), 300)
      })
    }
    return { top: 0 }
  }
})

// 登录态存在浏览器缓存里，由登录接口写入，退出登录时清掉
router.beforeEach((to) => {
  const user = JSON.parse(localStorage.getItem('xm-user') || '{}')
  // 管理端只对管理员开放：没登录的去登录页，登录了但不是管理员的回自己的用户端。
  // 直接甩一句没权限提示会让人不知道该去哪，所以这里给的是具体去处
  if (to.path.startsWith('/manager')) {
    if (!user.id) {
      return '/login'
    }
    if (user.role !== 'ADMIN') {
      return '/front/home'
    }
  }
  // 路由上声明了 requiresAdmin 的页面只对管理员开放：上面按 /manager 前缀先拦了一道，
  // 这里再按 meta 声明兜一层，以后管理页面换个前缀挂载也不会漏掉角色校验
  if (to.meta.requiresAdmin && user.role !== 'ADMIN') {
    return '/front/home'
  }
  // 用户端里标了 requiresUser 的页面同样要求先登录
  if (to.meta.requiresUser && !user.id) {
    return '/login'
  }
})

export default router
