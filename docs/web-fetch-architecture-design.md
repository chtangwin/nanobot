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

- **Phase 1**（抽离 core） ✅ 已完成
- **Phase 2**（接入 Tool） ✅ 已完成
- **Phase 3**（Adapter）：实现 `adapters/base.py` 接口 + `generic.py` + `x_com.py` + `registry.py`。
- **Phase 4**（Benchmark）：固定三组基准 URL，自动化对比。

---

## 16. 测试套件（Test Suite）

> 完成日期：2026-03-02 · 分支：`feature/webfetch`

### 16.1 目录结构

```text
tests/webfetch/
├── __init__.py
├── conftest.py              # 基准目标定义 + HTML fixtures + shared fixtures
├── test_models.py           # 7 tests  — FetchConfig / FetchResult / DEFAULT_HEADERS
├── test_extractors.py       # 10 tests — clean_text / extract_main_text / merge
├── test_quality.py          # 20 tests — SPA 检测 / 低质量判定 / 升级逻辑
├── test_browser.py          # 7 tests  — discovery 循环 (stall/click/scroll/max/dedup)
├── test_pipeline.py         # 19 tests — URL 规范化 / HTTP / 升级 / force / discovery / 字段
├── test_tool.py             # 19 tests — WebFetchTool schema / 兼容性 / 新参数 / 错误处理
└── test_integration.py      # 9 tests  — 4 个基准 URL 的真实网络测试 (@integration)
```

### 16.2 运行方式

```bash
# 单元测试 (92 tests, ~2s, 无需网络)
uv run pytest tests/webfetch/ -m "not integration" -v

# 集成测试 (需网络 + chromium)
uv run pytest tests/webfetch/test_integration.py -v

# 全部
uv run pytest tests/webfetch/ -v
```

### 16.3 基准目标（Benchmark Targets）

定义在 `conftest.py` 的 `BENCHMARKS` 字典中，供集成测试和后续 Phase 4 自动化 benchmark 引用：

| Key | URL | 测试场景 | 期望 source_tier |
|-----|-----|---------|-----------------|
| `plain_html` | `https://httpbin.org/html` | 纯静态 HTML（Melville 选段） | `http` |
| `javascript_spa` | `https://ip.sb/` | JS 动态页面，HTTP 只拿到 nav | `browser`（自动升级） |
| `discovery_pagination` | `https://airank.dev` | SPA + See More + 分页 Next | `browser`（discovery） |
| `adapter_x` | `https://x.com/elonmusk` | 强反爬，需专用适配器 | `adapter:x_com`（Phase 3） |

### 16.4 单元测试覆盖点

#### `test_models.py` — 数据模型
- FetchConfig 13 个字段默认值验证
- FetchConfig 自定义覆盖（部分字段改，其余保持默认）
- FetchResult 最小构造、`to_dict()` 往返、字段完整性

#### `test_extractors.py` — 内容提取
- `clean_text`: 空格剥离、CRLF 规范化、空行折叠、空字符串
- `extract_main_text`: 正常 HTML、微型 HTML、空 HTML、script/style 剥离、返回元组结构
- `merge_discovered_content`: 空列表不追加、追加格式正确、输出已清理

#### `test_quality.py` — 质量评估
- `contains_spa_signals`: 7 种 SPA 信号逐一检测 + 普通 HTML 无误报 + 组合 SPA HTML
- `is_low_quality_text`: 空文本 / 纯空格 / 好文章 / nav 关键词密集 / 无标点长文 / 短行过多 / 少量短行不误判 / 混合内容
- `should_escalate_to_browser`: 6 种 HTTP 状态码 / 正常 200 不升级 / HTML 过小 / SPA 信号 / 文本过短 / 低质量 / 优先级顺序 / None 状态码

#### `test_browser.py` — 浏览器 Discovery
- 无进展自动停止（stall_rounds）
- 点击收集 items
- 无点击目标时回退滚动
- 点击数上限（max_clicks）
- 滚动数上限（max_scrolls）
- item 去重
- Playwright 缺失时抛 RuntimeError

#### `test_pipeline.py` — 主流程
- URL 规范化：自动加 `https://`、去空格、保留 `http://`
- HTTP 快路径：好 HTML 留在 http 层、HTTP 错误返回 error result、cfg=None 用默认配置
- 浏览器升级：SPA 触发 fallback、fallback 失败回退 HTTP 结果、PDF 跳过浏览器
- 强制浏览器：跳过 HTTP、失败处理
- Discovery 模式：跳过 HTTP、content 含 `[Discovery Items]`、无 items 时不追加
- 字段一致性：成功和错误结果都包含全部 12 个字段

### 16.5 集成测试覆盖点

#### `TestPlainHtml` — httpbin.org/html
- snapshot 成功、内容含 Melville 文本、force_browser 也能工作

#### `TestJavascriptSpa` — ip.sb
- snapshot 自动升级到 browser（`needs_browser_reason` 非空）
- browser 拿到 IP 相关信息（IPv4/ISP/country 等关键词）

#### `TestDiscoveryPagination` — airank.dev
- snapshot 获取首屏内容
- 完整 discovery 工作流验证（单次 fetch，多维度断言）：
  - "See More" 作为首个 click action
  - "Next" 点击 ≥8 次（全部 10 页翻完）
  - 全部 97 个模型（#1 ~ #97）出现在 content 中
  - 末尾标志 "Showing 91 to 97 of 97" 存在
  - discovered_items ≥ 50

#### `TestXComAdapter` — x.com/elonmusk（Phase 3 基线）
- snapshot 基线记录（不 assert ok，仅验证结构有效）
- force_browser 基线记录

### 16.6 修复记录

| 发现的问题 | 修复 | 文件 |
|-----------|------|------|
| `extract_main_text("")` 抛 `lxml.ParserError: Document is empty` | `_extract_with_readability` 增加 `try/except`，空 HTML 返回 `("", None, "readability")` | `extractors.py` |
| 测试 fixture `GOOD_HTML` 不足 8KB，触发 `html_too_small` 升级 | 重复段落使 HTML 体积 > 8KB，并加 `assert` 防回归 | `conftest.py` |
| mock page 的 `page.locator()` 返回 coroutine 导致 `.inner_text()` 失败 | `page.locator` 用 `MagicMock`（sync），`.inner_text` 用 `AsyncMock`（async） | `test_browser.py` |

---

## 17. Phase 2 实施记录

> 完成日期：2026-03-02 · 分支：`feature/webfetch`

### 17.1 新 WebFetchTool（`nanobot/webfetch/tool.py`）

替换 `agent/tools/web.py` 中的旧 `WebFetchTool`，调用 core pipeline。

**接口变化：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `url` | string | *必填* | 目标 URL |
| `mode` | `"snapshot"` \| `"discovery"` | `"snapshot"` | snapshot: 单页；discovery: 自动翻页 |
| `forceBrowser` | boolean | `false` | 跳过 HTTP，直接用浏览器 |
| `maxChars` | integer (≥100) | 50000 | 最大返回字符数 |

- 旧参数 `extractMode` 仍可传入（被忽略），不会报错。
- 响应 JSON 是旧字段的超集：保留 `url`, `text`, `extractor`, `truncated`, `length`，新增 `ok`, `source_tier`, `final_url`, `needs_browser_reason`, `discovery_actions`, `discovered_items`, `error`。

### 17.2 注册方式（最小改动）

仅修改 2 个文件，各 1 行改动：

```python
# nanobot/agent/loop.py (line ~150)
from nanobot.webfetch.tool import WebFetchTool  # lazy import inside method

# nanobot/agent/subagent.py (line ~119)
from nanobot.webfetch.tool import WebFetchTool  # lazy import inside method
```

使用 lazy import 避免循环依赖（`webfetch.tool` → `agent.tools.base` → `agent.__init__` → `loop` → `webfetch.tool`）。

### 17.3 LLM 可发现性

Tool description 和参数描述已增强，LLM 能看到：
- 三种使用模式的说明（snapshot / discovery / forceBrowser）
- 何时使用 discovery（分页列表、Load More、Next 按钮）
- 何时使用 forceBrowser（已知 JS 站点、SPA、仪表盘）
- maxChars 默认值

### 17.4 依赖变更

`playwright` 和 `trafilatura` 从核心依赖移至可选 `[web]` extra：

```toml
[project.optional-dependencies]
web = ["playwright>=1.58.0", "trafilatura>=2.0.0"]
```

安装方式：`pip install nanobot-ai[web]` 或 `uv sync --extra web`。

### 17.5 测试覆盖

新增 `test_tool.py`（19 tests）：
- Schema 验证：name、required、enum、to_schema 格式
- 向后兼容：url-only 调用、legacy extractMode、旧+新响应字段
- 新参数：mode=discovery、forceBrowser、maxChars 截断
- URL 验证：无效 scheme、裸域名
- 错误处理：pipeline 错误透传、unexpected exception 兜底

**当前测试总计：92 passed（单元，~2s） + 9 集成（需网络）**

### 17.6 回退方案

旧 `WebFetchTool` 保留在 `agent/tools/web.py` 未删除。回退只需改回 import：

```python
# 回退: 改回旧 import
from nanobot.agent.tools.web import WebFetchTool
```

---

## 18. Phase 3 任务清单（Adapter 层）

### 18.1 目标

在 pipeline 中引入站点适配器机制，使难站点（如 x.com）走专用逻辑，通用站点继续走现有 generic 路径。

### 18.2 待实现文件

```text
nanobot/webfetch/adapters/
├── __init__.py          # ✅ 已创建（空骨架）
├── base.py              # Adapter 抽象接口
├── generic.py           # 通用适配器（包装现有 pipeline 逻辑）
├── x_com.py             # X/Twitter 专用适配器
└── registry.py          # URL → adapter 路由（域名匹配）
```

### 18.3 具体任务

| # | 任务 | 说明 |
|---|------|------|
| 1 | **定义 `Adapter` 抽象基类** (`base.py`) | 接口：`async def fetch(url, cfg) -> FetchResult`；属性：`domains: list[str]`（匹配的域名） |
| 2 | **实现 `GenericAdapter`** (`generic.py`) | 包装 `core/pipeline.py` 的 `robust_fetch`，作为默认 fallback |
| 3 | **实现 `XComAdapter`** (`x_com.py`) | 桥接现有 `x-scraper` skill 逻辑；持久登录态（`x_auth.json`）；按推文 URL 去重；输出结构化字段 |
| 4 | **实现 `AdapterRegistry`** (`registry.py`) | URL → adapter 选择；域名前缀匹配；未匹配时回退 generic；`register()` / `resolve(url)` API |
| 5 | **pipeline 集成** | `robust_fetch()` 开头调用 `registry.resolve(url)`；如果返回非 generic adapter → 走 adapter 路径 |
| 6 | **FetchResult.source_tier** | adapter 路径返回 `"adapter:x_com"` 等值 |
| 7 | **测试** | `test_adapters.py`：base 接口、registry 路由、generic 透传、x_com mock/集成 |
| 8 | **集成测试更新** | `test_integration.py` 的 `TestXComAdapter` 从 baseline 升级为真实验证 |

### 18.4 设计要点

- **Adapter 接口最小化**：只需 `fetch()` + `domains`，不过度抽象
- **Registry 简单路由**：域名匹配即可（`x.com` / `twitter.com` → `XComAdapter`）
- **x_com adapter 可分阶段**：先桥接现有 x-scraper，后续再内化
- **不改 tool 层**：adapter 对 `WebFetchTool` 透明，只在 pipeline 内部路由
