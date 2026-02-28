# 远程主机开发工作流

> 双分支开发策略说明

## 概述

使用双分支策略将代码开发与文档分离：

- **feature/remote-node-local**: 开发分支，包含所有提交（代码 + 文档）
- **feature/remote-node**: PR 分支，仅包含代码提交，文档为本地未跟踪文件

## 分支职责

### feature/remote-node-local（开发分支）

```
用途：日常开发
提交：代码 + 文档
历史：完整记录
```

**在此分支进行：**
- ✅ 代码开发
- ✅ 文档编写
- ✅ 测试和调试
- ✅ 所有类型的 commit

**示例提交：**
```
feat: 添加主机健康检查
fix: 修复 SSH 隧道超时问题
docs: 更新使用指南
refactor: 重构连接管理器
```

### feature/remote-node（PR 分支）

```
用途：Pull Request
提交：仅代码
文档：本地未跟踪文件
```

**特点：**
- ✅ 干净的提交历史
- ✅ 仅包含代码变更
- ✅ 本地保留文档供参考
- ✅ 适合提交 PR/MR

## 工作流程

### 1. 日常开发（在 local 分支）

```bash
# 确保在开发分支
git checkout feature/remote-node-local

# 进行开发（代码或文档）
vim nanobot/remote/manager.py
vim docs/node-remote/USAGE.md

# 提交变更
git add .
git commit -m "feat: 添加主机健康检查功能"
```

### 2. 同步到 PR 分支

**方法 A：使用同步脚本（推荐）**

```bash
# 运行同步脚本
./scripts/sync-to-pr-branch.sh

# 脚本会自动：
# 1. 查找代码提交
# 2. Cherry-pick 到 PR 分支
# 3. 复制最新文档（未跟踪）
# 4. 显示同步结果
```

**方法 B：手动同步**

```bash
# 切换到 PR 分支
git checkout feature/remote-node

# Cherry-pick 特定提交
git cherry-pick <commit-hash>

# 或批量同步（仅代码提交）
git log feature/remote-node-local ^feature/remote-node --oneline
# 记下代码提交的 hash，然后逐个 cherry-pick

# 复制最新文档（未跟踪）
git checkout feature/remote-node-local -- docs/node-remote/*.md

# 推送到远程
git push origin feature/remote-node
```

### 3. 创建 Pull Request

```bash
# 确保在 PR 分支
git checkout feature/remote-node

# 推送到远程
git push origin feature/remote-node

# 在 GitHub/GitLab 创建 PR
# 从: feature/remote-node
# 到: main
```

## 提交规范

### 代码提交（会同步到 PR 分支）

```
feat: 新功能
fix: 修复 bug
refactor: 重构
test: 测试
perf: 性能优化
chore: 构建/工具变更
```

### 文档提交（不同步到 PR 分支）

```
docs: 文档更新
docs: 翻译文档
```

## 示例场景

### 场景 1：添加新功能

```bash
# 1. 在 local 分支开发
git checkout feature/remote-node-local

# 2. 编写代码
vim nanobot/remote/health.py
git add nanobot/remote/health.py
git commit -m "feat: 添加主机健康检查"

# 3. 更新文档
vim docs/node-remote/USAGE.md
git add docs/node-remote/USAGE.md
git commit -m "docs: 添加健康检查使用说明"

# 4. 同步到 PR 分支
./scripts/sync-to-pr-branch.sh
# 只会 cherry-pick "feat: 添加主机健康检查"

# 5. 推送并创建 PR
git push origin feature/remote-node
```

### 场景 2：修复 Bug

```bash
# 在 local 分支修复
git checkout feature/remote-node-local

# 修复代码
vim nanobot/remote/connection.py
git commit -am "fix: 修复连接超时处理"

# 同步到 PR 分支
./scripts/sync-to-pr-branch.sh

# 推送
git push origin feature/remote-node
```

### 场景 3：仅更新文档

```bash
# 在 local 分支更新文档
git checkout feature/remote-node-local

vim docs/node-remote/QUICKSTART.md
git commit -am "docs: 完善 SSH 配置说明"

# 此时不需同步到 PR 分支
# 因为 PR 分支的本地文档（未跟踪）会在下次同步时自动更新
```

## 分支状态查看

```bash
# 查看两个分支的差异
git log feature/remote-node..feature/remote-node-local --oneline

# 查看需要同步的提交
git log feature/remote-node..feature/remote-node-local --oneline --grep="^feat\|^fix"

# 查看当前分支
git branch --show-current

# 查看所有分支
git branch -v
```

## 常见问题

### Q: 为什么要用两个分支？

A:
- **local 分支**: 保留完整开发历史，包括文档迭代
- **PR 分支**: 提交历史干净，仅包含代码，便于审查

### Q: 文档不会丢失吗？

A: 不会。文档在两个地方：
1. **local 分支**: Git 跟踪，完整历史
2. **PR 分支**: 本地文件，未跟踪，但内容与 local 同步

### Q: 如何确保 PR 分支的文档是最新的？

A: 每次运行 `./scripts/sync-to-pr-branch.sh` 时，脚本会自动从 local 分支复制最新文档。

### Q: Cherry-pick 冲突怎么办？

A:
```bash
# 手动解决冲突
vim <冲突文件>
git add .
git cherry-pick --continue
```

### Q: 可以直接在 PR 分支开发吗？

A: 不推荐。应在 local 分支开发，然后同步到 PR 分支。

## 快速参考

```bash
# 开发
git checkout feature/remote-node-local
# ... 编码和提交 ...

# 同步
./scripts/sync-to-pr-branch.sh

# PR
git checkout feature/remote-node
git push origin feature/remote-node

# 查看状态
git log feature/remote-node..feature/remote-node-local --oneline
```

## 相关文档

- [快速入门](./QUICKSTART.md)
- [使用指南](./USAGE.md)
- [实现说明](./IMPLEMENTATION.md)
- [设计文档](./NANOBOT_NODE_ENHANCEMENT.md)
