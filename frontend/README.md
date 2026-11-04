# Article Autopilot · Frontend

Article Autopilot 的本地运营控制台。使用 Vite、React 18、TypeScript、Tailwind CSS v4、React Router、TanStack Query 与 Recharts 构建，覆盖从选题、资料、写作、审核、排版到发布的完整流程。

## 运行

要求 Node.js 20+（当前验证使用 Node 24 / npm 11）。

```bash
npm install
npm run dev
```

开发服务器默认运行在 `http://localhost:5173`，并把以下请求代理到后端：

- `/api/*` → `http://127.0.0.1:8000`
- `/openapi.json` → `http://127.0.0.1:8000`

如后端不在默认地址，可设置 `VITE_BACKEND_URL`：

```bash
VITE_BACKEND_URL=http://127.0.0.1:9000 npm run dev
```

生产 API 前缀也可通过 `VITE_API_BASE_URL` 覆盖，默认是 `/api`。

## 脚本

| 命令 | 作用 |
| --- | --- |
| `npm run dev` | 启动 Vite 开发服务器 |
| `npm run lint` | ESLint 9 flat config + typescript-eslint |
| `npm run test` | Vitest（jsdom + Testing Library）单次运行 |
| `npm run test:watch` | Vitest 监听模式 |
| `npm run build` | `tsc -b` 类型检查后构建生产包 |

## 页面

- `/`：文章工作台。创建文章、搜索/筛选、删除文章，查看状态与累计成本。
- `/articles/:id`：文章详情。桌面端粘性七节点阶段栏，移动端横向步骤条与抽屉；阶段面板支持选题推荐、资料、可编辑大纲与正文、审核报告、平台排版预览及发布确认。
- `/analytics`：按日期范围查看文章、发布、阅读、收益、成本与 ROI，含 Recharts 图表和表现表。
- `/skills`：技能列表、启用开关、内容编辑、版本记录与阶段绑定。
- `/settings`：模型档案、阶段模型绑定、平台凭据（只显示掩码）与通用配置。
- `/evolution`：自进化建议、证据/补丁、审批、应用、回滚与生成。

## 安全与实时更新

- 生成的公众号 HTML 只通过 `<iframe sandbox="" srcDoc={...}>` 渲染，不会注入父页面 DOM。
- Markdown 预览使用 `react-markdown` + `remark-gfm` 并开启 `skipHtml`。
- 平台凭据读取接口只展示后端掩码；保存后清空输入并重新读取掩码。
- 工作流通过 SSE 更新；连接异常时按指数退避重连，重连成功后全量刷新查询，文章处于活动状态时每 5 秒轮询兜底。

## 测试

测试通过 `vi.stubGlobal("fetch", ...)` 模拟网络，不依赖真实后端。当前覆盖：

- API 请求封装（JSON 头、错误体、204）
- SSE 指数退避重连、事件解析与重连后刷新
- 文章列表渲染
- 文章详情粘性阶段栏、横向步骤条与移动端抽屉
- 选题候选选择、写作面板保存后版本刷新
- 七阶段阶段栏与 paused / needs-human 警告映射
- 发布确认流程与失败平台重试
- 运维分析时间筛选与空数据
- 技能绑定保存、启停状态刷新
- 模型价格与凭据掩码
- 自进化状态徽章、筛选与操作确认
- GFM Markdown 与公众号 sandbox iframe

```bash
npm run test
```

## 已知限制

- 资料面板支持手动新增与删除来源，接口为 `GET/POST /api/articles/{id}/sources` 与 `DELETE /api/articles/{id}/sources/{source_id}`；自动检索来源仍由资料搜索阶段生成。
- 自进化建议的“生成”依赖已配置的模型与近期文章信号；样本不足时可能返回空列表。
- 当前没有前端鉴权模块，项目按本地单机控制台设计。
