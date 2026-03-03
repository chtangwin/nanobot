# Skills 加载机制

## 启动链路

```
gateway() → AgentLoop → ContextBuilder(workspace)
                              ↓
                        SkillsLoader(workspace)
                              ↓
                   build_system_prompt() 每次 LLM 调用时执行
```

## 扫描目录（仅两个）

```python
# nanobot/agent/skills.py
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"
#                    → nanobot/skills/

# SkillsLoader.__init__
self.workspace_skills = workspace / "skills"     # ~/.nanobot/workspace/skills/
self.builtin_skills = BUILTIN_SKILLS_DIR         # nanobot/skills/
```

## 扫描优先级

1. **workspace skills 优先**：先扫 `~/.nanobot/workspace/skills/*/SKILL.md`
2. **builtin skills 兜底**：再扫 `nanobot/skills/*/SKILL.md`，**同名跳过**（workspace 覆盖 builtin）

```python
# 关键逻辑：workspace 同名 skill 覆盖 builtin
if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
```

## 加载方式：渐进式（三级）

1. **始终在 context 中**：`name` + `description`（frontmatter）→ 通过 `build_skills_summary()` 生成 XML 列表注入 system prompt
2. **always skills**：frontmatter 有 `always: true` 的 skill → body 全文注入 system prompt
3. **按需加载**：LLM 看到 skill 列表后，用 `read_file` 工具读取 SKILL.md 全文

## 只扫一层深度

```
nanobot/skills/
├── webfetch/SKILL.md    ✅ 会发现
├── cron/SKILL.md        ✅ 会发现
├── contrib/
│   └── foo/SKILL.md     ❌ 不会发现（contrib 本身没有 SKILL.md，foo 是二级子目录）
```

## 新增 Skill 的推荐位置

| 场景 | 放哪里 | 理由 |
|------|--------|------|
| 随代码库分发的 skill（所有用户可用） | `nanobot/skills/<name>/SKILL.md` | git 版本控制，自动分发 |
| 用户私有 skill（个人配置、公司知识） | `~/.nanobot/workspace/skills/<name>/SKILL.md` | 不污染代码库，同名可覆盖 builtin |
| 覆盖 builtin skill 的行为 | `~/.nanobot/workspace/skills/<同名>/SKILL.md` | workspace 优先，自动覆盖 |

不建议创建 `nanobot/contrib/skills/` 等子目录——当前代码不扫二级路径，且 skill 文件很小（1-5KB），即使 20-30 个也不会显著膨胀代码库。
