# 前端 / 小程序设计指南

Step 4 加载。按 `LC-FE-001` 选框架。标准框架设计模式 AI 已知。

## Web 前端

### 框架与状态管理

- LC-FE-001 = Vue3 → Composition API + Pinia
- LC-FE-001 = React → Hooks + Zustand
- 状态管理：全局（store）+ 本地（ref/useState）
- API 层：统一 intercept 处理 token/错误
- 路由：懒加载，路由守卫鉴权

### CSS 方案

- **Vue3**：Scoped CSS（`<style scoped>`），全局主题变量用 CSS 自定义属性
- **React**：CSS Modules（`*.module.css`），全局主题变量用 CSS 自定义属性
- **禁止使用内联样式**（`style={{}}` / `style="..."`），极少数动态值场景（运行时计算的位置/尺寸）必须有注释说明原因
- 全局样式集中管理：`src/frontend/src/styles/variables.css`（色板/间距/字号/阴影/圆角）

### 组件分层结构

```
src/frontend/src/
├── components/shared/   # 跨模块共享组件（通用性高，可被 2+ 模块复用）
├── components/{模块}/   # 模块内共享组件
├── views/{模块}/        # 页面级组件
├── styles/
│   ├── variables.css    # CSS 变量（颜色/间距/字号/阴影/圆角）
│   └── global.css       # 全局重置 / 排版基础
└── api/                 # API 调用层
```

### 组件复用规则

- **相同 UI 模式出现 2 次以上，必须抽取为共享组件**，放入 `components/shared/`
- 共享组件的样式**只能使用 CSS 变量**，不硬编码颜色/间距值
- 新增组件前先检查 `components/shared/` 是否有可复用组件

### CSS 变量命名体系

```
--color-primary       # 品牌主色
--color-danger        # 危险/错误
--color-warning       # 警告
--color-success       # 成功
--color-bg            # 背景色
--color-text          # 正文色
--color-text-secondary # 次要文字
--color-border        # 边框色
--spacing-xs          # 4px
--spacing-sm          # 8px
--spacing-md          # 16px
--spacing-lg          # 24px
--spacing-xl          # 32px
--font-size-sm        # 12px
--font-size-md        # 14px
--font-size-lg        # 16px
--font-size-xl        # 20px
--radius-sm           # 4px
--radius-md           # 8px
--radius-lg           # 12px
--shadow-sm           # 小阴影
--shadow-md           # 中阴影
--shadow-lg           # 大阴影
```

框架无关，Vue3 和 React 通用。

## 微信小程序

- 页面栈：Tab 页平铺，非 Tab 页层级控制 ≤ 5
- 登录流程：wx.login → code → 后端换取 token
- 分包策略：主包 ≤ 2MB，按模块分包
- 支付：wx.requestPayment
- 样式：使用 wxss + CSS 变量（通过 `page` 或 `app.wxss` 定义主题变量）
