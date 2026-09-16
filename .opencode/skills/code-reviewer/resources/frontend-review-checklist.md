# 前端代码评审检查清单

全栈模式加载。以下每项给"怎么查"，不依赖"AI 按标准最佳实践执行"。

## Dim 6.1：编码规范

- 命名 / TypeScript / 代码风格 / 分层规范
- **怎么查**：`any` 滥用（禁）；`// TODO` 遗留；组件文件超 300 行=拆；目录是否按 `components/views/api/styles` 分层

## Dim 6.2：业务逻辑

- 页面展示 / 表单提交 / 状态映射 / 异常处理
- **怎么查**：表单提交**前**校验（不靠后端兜底）；loading/空态/错误态三态齐不齐；状态映射集中（常量/枚举），禁散落魔法值；错误提示有用户可读文案

## Dim 6.3：安全

- Token 存储（httpOnly Cookie / 内存，P0）
- XSS / CSRF / 路由守卫 / API 鉴权 / 敏感信息
- **怎么查**：Token 禁 localStorage（P0）；`v-html`/`dangerouslySetInnerHTML` 渲染不可信内容（P0）；敏感字段禁进日志/URL；无守卫路由（P0）

## Dim 6.4：性能

- 路由懒加载 / 渲染优化 / 响应式性能 / 网络请求
- **怎么查**：路由全部懒加载（P0 若整包加载）；列表渲染无 key / 大列表无虚拟滚动（P1）；重复请求无去抖/缓存；图片无懒加载（P1）

## Dim 6.5：可维护性

- 组件复杂度 / 重复代码 / 硬编码 / 路由规范 / 注释
- **怎么查**：同 UI 模式重复 2+ 次未抽组件（P1）；色值/文案/常量硬编码（P1）；路由命名不统一；`console.log` 残留

## Dim 6.6：框架特化

- Vue3：Composition API 规范、Pinia 正确使用、模板语法
- React：Hooks 规则、渲染优化（memo/useMemo）、Zustand 实践
- **怎么查**：Vue3 混用 Options/Composition（P1）；Pinia 直接改 store 而非 action（P1）；React Hooks 在条件/循环中调用（P0 规则违反）；`useEffect` 缺依赖项（P1）

## Dim 6.7：样式规范（新增）

- **P0：禁止内联样式** — React 的 `style={{}}`、Vue3 的 `:style="..."`（仅动态位置/尺寸场景可例外且须注释说明）
- **P0：CSS 变量引用** — 颜色/间距/字号等属性必须引用 `variables.css` 中的 CSS 变量，禁止硬编码
- **P1：组件复用** — 相同 UI 模式出现 2 次以上未抽取为共享组件（`components/shared/`）→告警
- **P1：组件分层违规** — `views/` 组件引用另一个 `views/` 组件、`shared/` 组件引用 `feature/` 组件等跨层引用

## Dim 6.8：前后端 API 契约验证（全栈模式，新增）

- **P0：URL 路径不匹配** — 前端 API 调用路径与后端 controller/route 定义不一致
- **P0：HTTP 方法不匹配** — 前端用 GET 但后端定义为 POST 等
- **P0：请求参数字段不匹配** — 前端传入字段名/类型与后端 controller 参数不一致
- **P0：响应字段不匹配** — 前端代码使用的响应字段名与后端实际返回字段名不一致
- **P1：枚举/常量不对齐** — 前端硬编码的值与后端枚举定义不一致
