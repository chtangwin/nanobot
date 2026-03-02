# Web Fetch 架构设计（通用框架 + 站点适配器）

> 目标：把当前 `scripts/web_fetch_robust.py` 的能力产品化到 nanobot，形成可扩展、可维护、可基准测试（benchmark）的网页抓取体系。  
> 关键约束：不同网站交互差异大，不能依赖“写死按钮”；同时要保留对难站点（如 x.com）的稳定抓取能力。

---

## 1. 背景与问题

我们已经验证：

- 纯 HTTP 抓取很快，但对 JS/SPA 页面经常拿不到有效内容。
- 通用 Playwright + discovery（点击/滚动/翻页）可以覆盖大量站点，但无法 100% 通吃所有网站。
- 对 x.com 这类强登录、虚拟列表、反爬强的站点，**站点专用逻辑**明显更稳（现有 `x-scraper` skill 已证明）。

因此需要一种组合方案：

1. 默认走通用抓取路径（快、泛化）
2. 对难站点自动切换专用适配器（稳、准确）
3. 统一输入输出，便于 tool 调用和后续 benchmark

---

## 2. 结论（架构方向）

**采用「Tool 为主，Skill 为辅」的分层设计。**

- **Tool**：承载稳定抓取能力、统一 API、统一结果结构。
- **Skill**：承载操作策略/引导（何时 discovery、何时登录、如何排障），不承载核心抓取引擎。

这能避免代码分散和逻辑重复，也能让后续扩展新站点更可控。

---

## 3. 设计原则

1. **Fast-first**：优先 HTTP 快路径，失败再升级浏览器。
2. **Progressive escalation**：按质量门槛升级，而非一上来全量浏览器。
3. **Adapter-first for hard sites**：难站点走专用适配器。
4. **统一输出协议**：无论通用/专用路径，都返回同一 schema。
5. **可扩展**：新增网站能力应尽量“加文件，不改主流程”。
6. **可 benchmark**：每次抓取都可追踪来源层级和动作序列。

---

## 4. 推荐目录结构

```text
nanobot/
  webfetch/
    core/
      models.py          # FetchRequest / FetchResult 等
      pipeline.py        # HTTP -> Browser -> Discovery 主流程
      extractors.py      # trafilatura/readability/raw 抽取
      quality.py         # 质量评估、升级判定
      browser.py         # Playwright 通用能力
    adapters/
      base.py            # Adapter 抽象接口
      generic.py         # 通用适配器（默认）
      x_com.py           # X 站点适配器（后续优先）
      registry.py        # URL -> adapter 选择
    infra/
      cache.py           # 可选：缓存/去重
      rate_limit.py      # 可选：域名限速
      logging.py         # 结构化日志
```

Tool 层保留：

- `nanobot/agent/tools/web.py`（`web_fetch` 名称不变）

---

## 5. Tool vs Skill 职责边界

### Tool（主能力）

- 对外稳定接口（`web_fetch`）
- 统一参数：`mode`, `forceBrowser`, `maxChars` 等
- 内部自动路由：generic 或 site adapter
- 统一返回字段：`source_tier`, `discovery_actions`, `discovered_items` 等

### Skill（编排与操作）

- 何时使用 `mode=discovery`
- 特殊站点的使用建议（例如 x.com 登录态失效时如何处理）
- 非核心能力说明（首次登录、人工校验）

> 简单说：Tool 是引擎，Skill 是驾驶手册。

---

## 6. 统一接口建议

### 入参（建议）

- `url: str`
- `mode: "snapshot" | "discovery"`（默认 `snapshot`）
- `forceBrowser: bool`（可选）
- `maxChars: int`
- `goal: str | None`（可选，未来用于策略提示）
- `hints: object | None`（可选，未来扩展）

### 出参（建议）

- `ok: bool`
- `url`, `final_url`, `status_code`
- `title`, `content`
- `source_tier: "http" | "browser" | "adapter:<name>"`
- `extractor`
- `needs_browser_reason`
- `discovery_actions: string[]`
- `discovered_items: int`
- `error: str | null`

---

## 7. Discovery 的“通用但有限”原则

我们已经确认一个现实：

- Discovery 可以做成通用策略（click/next/scroll/stall-stop）
- 但无法保证任意网站 100% 全量抓取

因此设计上要接受“概率型 + 护栏型”策略：

- 最大点击数、最大滚动数、最大等待
- 连续无增量则停止
- 始终输出动作轨迹，便于复盘

### 已遇到的真实坑

- 初版把按钮打 `clicked` 标记后，分页 `Next` 被误伤，只点一次就停。
- 修复后：允许 `Next/下一页` 重复点击，直到无增量或不可用。

这类经验应该固化在 `core/quality.py` 与 `core/pipeline.py` 里。

---

## 8. 三个基准案例（后续 benchmark 用）

## 8.1 `https://ip.sb/`（动态信息区块）

现象：HTTP 文本常被导航噪声主导，正文质量低。  
策略：

- `snapshot` 先跑 HTTP
- 命中低质量后升级 browser
- 优先提取正文，必要时回退 `body.inner_text`

预期指标：

- `source_tier=browser`
- `needs_browser_reason=low_content_quality`（或类似）
- 能拿到 IPv4/IPv6 连接信息而非只有菜单。

## 8.2 `https://airank.dev`（SPA + 分页榜单）

现象：

- 首屏有 `See More (93 more models)`
- 展开后分页 `Next`，每页约 10 条，总 97 条

策略：

- `mode=discovery`
- 先点 `See More`，后续连续 `Next`
- 收集表格/列表条目并去重

预期指标：

- `source_tier=browser`
- `needs_browser_reason=discovery_mode`
- `discovery_actions` 含多次 `click:Next`
- 内容中出现 `Showing 91 to 97 of 97 models`

## 8.3 `https://x.com/...`（强站点特化）

现象：

- 登录态、虚拟列表、反爬限制强
- 通用 discovery 覆盖有限，不稳定

策略：

- 使用 x 专用适配器（或现有 `x-scraper`）
- 持久登录态（如 `x_auth.json`）
- 按推文 URL 去重，滚动增量抓取

预期指标：

- 能稳定获取“最近 N 条帖子”
- 输出结构化字段：`text/date/url/likes/retweets/replies/media`

---

## 9. 关于“是否替换 WebFetchTool”

建议：**兼容式替换内核，不换工具名。**

- `web_fetch` 名称保留
- `WebSearchTool` 不动
- `WebFetchTool` 内部改为调用新架构
- 默认行为继续可用（snapshot）
- 新增可选高级参数（discovery / forceBrowser）

这样可以保证现有调用不被破坏，并逐步升级能力。

---

## 10. 迭代落地计划

### Phase 1：抽离核心

- 把 `scripts/web_fetch_robust.py` 拆到 `nanobot/webfetch/core/*`
- 保留脚本作为调试入口（thin wrapper）

### Phase 2：接入 Tool

- `nanobot/agent/tools/web.py` 的 `WebFetchTool.execute()` 改为调用 core pipeline
- 返回结构保持兼容并扩展字段

### Phase 3：接入 Adapter

- `generic` + `x_com` 两个 adapter
- `x_com` 初期可桥接现有 x-scraper 逻辑（快速稳定）

### Phase 4：benchmark 与稳定性

- 固定三组基准：`ip.sb`、`airank.dev`、`x.com`
- 记录成功率、抓取时延、字段完整度、动作轨迹

---

## 11. 风险与应对

1. **网站变化快**：选择器失效
   - 应对：adapter 独立文件 + 快速修复
2. **通用 discovery 误点**：跳转到详情页
   - 应对：更严格按钮筛选 + URL 变化监控 + 回退策略
3. **抓取成本高**：浏览器耗资源
   - 应对：HTTP 优先、并发控制、域名限速
4. **编码问题（Windows 控制台）**
   - 应对：统一 UTF-8 输出配置

---

## 12. 最终决策摘要

- 架构采用：**Tool 主体 + Adapter 扩展 + Skill 辅助**
- `web_fetch` 保持工具名，内部升级
- 通用 discovery 保留，但承认其边界
- 难站点（x.com）走专用适配器
- 用 `ip.sb` / `airank.dev` / `x.com` 作为长期 benchmark 样本

---

## 13. 附：当前脚本能力状态（作为迁移基线）

当前 `scripts/web_fetch_robust.py` 已具备：

- HTTP 快路径 + 浏览器 fallback
- 低质量内容检测与升级
- `snapshot | discovery` 模式
- 通用 click/scroll discovery
- `source_tier` / `needs_browser_reason` / `discovery_actions` / `discovered_items`
- UTF-8 输出修正

迁移时应确保这些能力在 core/tool 层完整保留。

---

## 14. 代码库现状审查（Code Review）

> 审查日期：2026-03-02

### 14.1 当前 `WebFetchTool`（`nanobot/agent/tools/web.py`）

- **纯 HTTP 抓取**，使用 `httpx` + `readability-lxml`。
- 支持 `markdown` / `text` 两种提取模式，HTML→Markdown 转换基于正则替换。
- 返回 JSON 字段：`url`, `finalUrl`, `status`, `extractor`, `truncated`, `length`, `text`。
- **无浏览器 fallback**，无 SPA 支持，无 discovery 能力。
- 与设计文档目标的差距：缺少 `source_tier`, `needs_browser_reason`, `discovery_actions`, `discovered_items` 等追踪字段。

### 14.2 当前脚本 `scripts/web_fetch_robust.py`（迁移基线）

- **完整的 HTTP → Browser → Discovery 三级流水线**，约 350 行。
- `FetchConfig` 数据类控制所有阈值参数（超时、重试、最大步数等）。
- `FetchResult` 数据类统一输出结构，已包含设计文档要求的大部分字段。
- 质量评估逻辑完备：SPA 信号检测（`_contains_spa_signals`）、低质量内容检测（`_is_low_quality_text`）、短文本检测。
- 浏览器升级判定（`should_escalate_to_browser`）：按 HTTP 状态码 / HTML 体积 / SPA 信号 / 文本质量四层递进。
- Discovery 模式：通用 click/scroll 扩展，`Next` 重复点击修复，无增量连续 N 轮停止。
- 支持 `trafilatura` + `readability` 双提取器（trafilatura 优先）。
- 已作为独立 CLI 工具可用（`uv run python scripts/web_fetch_robust.py`）。

### 14.3 基础设施就绪度

| 项 | 状态 |
|----|------|
| `Tool` 抽象基类（`base.py`） | ✅ 提供 `name`, `description`, `parameters`, `execute()`, `validate_params()` |
| `ToolRegistry`（`registry.py`） | ✅ 动态注册/执行/schema 导出 |
| `playwright` 依赖 | ✅ `pyproject.toml` 已声明 `>=1.58.0` |
| `trafilatura` 依赖 | ✅ `pyproject.toml` 已声明 `>=2.0.0` |
| `readability-lxml` 依赖 | ✅ `pyproject.toml` 已声明 `>=0.8.4` |
| `nanobot/webfetch/` 包 | ❌ 尚未创建，需 Phase 1 新建 |

---

## 15. 设计文档评审意见

### 15.1 设计亮点（✅ 认可）

1. **Fast-first + Progressive escalation** — 分层策略合理，避免不必要的浏览器开销。
2. **Adapter 模式** — 难站点走专用适配器、通用站点走 generic，扩展点清晰。
3. **统一输出协议** — `source_tier` / `discovery_actions` / `discovered_items` 可追踪、可 benchmark。
4. **兼容式替换** — 工具名不变，默认行为向后兼容，现有调用不会中断。
5. **Benchmark 三案例** — `ip.sb`（动态内容）、`airank.dev`（SPA 分页）、`x.com`（强反爬）覆盖面好。

### 15.2 需关注的风险与建议（⚠️）

| # | 风险点 | 说明 | 建议 |
|---|--------|------|------|
| 1 | **脚本→模块拆分的行为一致性** | `web_fetch_robust.py` 约 350 行，拆到 5 个模块需确保逻辑不丢失、边界 case 不回归 | Phase 1 完成后用现有 CLI 做 A/B 对比测试（同 URL 同参数，对比输出） |
| 2 | **Tool 接口变更的兼容性** | 新增 `mode`, `forceBrowser`, `goal`, `hints` 参数；LLM 端 schema 需同步更新 | 新参数全部设为 optional 且有默认值；旧调用（只传 `url`）行为不变 |
| 3 | **Playwright 生命周期与性能** | 当前脚本每次调用都 launch/close browser，频繁调用时开销大 | Phase 2 可先保持现状；后续考虑 browser pool 或 context 复用（infra 层） |
| 4 | **Adapter registry 路由复杂度** | 目前只有 generic + x_com 两个适配器 | 初期用域名前缀匹配即可，避免过度设计；预留 `registry.py` 接口供后续扩展 |
| 5 | **Discovery 误点风险** | 设计文档 §7 已提及，但缺少具体护栏参数建议 | 建议在 `FetchConfig` 中增加 `discovery_url_change_abort: bool` 字段，跳转到不同域名时自动回退 |
| 6 | **出参字段与现有 Tool 返回的差异** | 现有 `WebFetchTool` 返回 `finalUrl`（camelCase），脚本用 `final_url`（snake_case） | 统一为 snake_case（Python 惯例），Tool 返回 JSON 时也用 snake_case |

### 15.3 Phase 落地顺序确认

设计文档的 4 个 Phase 划分合理，建议细化：

- **Phase 1**（抽离 core）：创建 `nanobot/webfetch/` 包，拆分 models / extractors / quality / pipeline / browser，保留 `scripts/web_fetch_robust.py` 作为 thin wrapper 调用新 core。
- **Phase 2**（接入 Tool）：修改 `WebFetchTool.execute()` 调用 `core.pipeline`，扩展入参和出参，保持默认行为兼容。
- **Phase 3**（Adapter）：实现 `adapters/base.py` 接口 + `generic.py` + `x_com.py` + `registry.py`。
- **Phase 4**（Benchmark）：固定三组基准 URL，自动化对比。
