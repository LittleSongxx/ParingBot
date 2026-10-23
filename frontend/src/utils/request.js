import axios from "axios";
import {ElMessage} from "element-plus";
import router from "@/router/index.js";

// 全项目只有这一个 axios 实例，页面一律 import 它。
// 请求头怎么带、响应怎么判、出错怎么提示，都收在这一处，
// 页面里不用再各写一遍 token 和错误处理
const request = axios.create({
    baseURL: import.meta.env.VITE_BASE_URL,
    // 后台接口超时时间：超过 30 秒没返回就按超时失败处理
    timeout: 30000
})

// 登录态存在浏览器缓存的这个键里：登录接口写入，退出登录和登录失效时清掉
const USER_CACHE_KEY = 'xm-user'

// request 拦截器
// 可以自请求发送前对请求做一些处理
request.interceptors.request.use(config => {
    // 上传文件时 config.data 是 FormData，Content-Type 必须留给浏览器自动生成（要带 boundary）。
    // 这里若统一改成 application/json，axios 会把表单转成 JSON 字符串，文件字段会丢掉，后端拿到的是空文件
    if (!(config.data instanceof FormData)) {
        config.headers['Content-Type'] = 'application/json;charset=utf-8';
    }
    let user = JSON.parse(localStorage.getItem(USER_CACHE_KEY) || '{}')
    // 后端从请求头的 token 里解析当前是谁，没登录时传空串，由后端回 401
    config.headers['token'] = user.token || ''
    return config
}, error => {
    return Promise.reject(error)
});

// 登录失效的统一处理：清掉缓存的账号信息，再送回登录页。
// 缓存不清的话路由守卫看着还以为登录着，会在登录页和业务页之间来回跳
const backToLogin = () => {
    localStorage.removeItem(USER_CACHE_KEY)
    if (router.currentRoute.value.path !== '/login') {
        router.push('/login')
    }
}

// response 拦截器
// 可以在接口响应后统一处理结果
request.interceptors.response.use(
    response => {
        let res = response.data;
        // 如果是返回的文件
        if (response.config.responseType === 'blob') {
            return res
        }
        // 兼容服务端返回的字符串数据
        if (typeof res === 'string') {
            res = res ? JSON.parse(res) : res
        }
        // 401：没登录，或者 token 过期了、账号被停用了。后端把这些情况统一返回 401，
        // 前端对应的动作就一个：清登录态回登录页
        if (res.code === '401') {
            ElMessage.error(res.msg || '登录状态已失效，请重新登录')
            backToLogin()
        }
        // 403：登录着但权限不够，比如租客点进了管理员才能做的操作。
        // 提示要说清换成哪个账号，不能只说一句没权限
        if (res.code === '403') {
            ElMessage.error(res.msg || '当前账号没有这个操作的权限，请换成管理员账号后再操作')
        }
        return res;
    },
    error => {
        // 后端没启动、网络断开、请求超时这几种情况下压根没有响应，
        // error.response 是 undefined，不先判空就取 status，拦截器自己会报错，页面上一点提示都看不到
        if (!error.response) {
            if (error.code === 'ECONNABORTED') {
                ElMessage.error('请求超时，请稍后重试；如果一直超时，请确认后端服务已启动')
            } else {
                ElMessage.error('连不上后端服务，请确认后端已启动，再重试刚才的操作')
            }
            return Promise.reject(error)
        }
        const status = error.response.status
        if (status === 404) {
            ElMessage.error('请求的接口不存在，请确认后端服务已启动、接口地址没有写错')
        } else if (status === 500) {
            ElMessage.error('服务器处理出错，请稍后重试；如果一直失败，请把刚才的操作告诉管理员')
        } else {
            ElMessage.error('请求失败（HTTP ' + status + '），请稍后重试；如果一直失败，请把刚才的操作告诉管理员')
        }
        return Promise.reject(error)
    }
)

export default request