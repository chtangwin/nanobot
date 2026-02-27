#!/bin/bash
# 同步代码提交到 feature/remote-node PR 分支
# 用法：./scripts/sync-to-pr-branch.sh

set -e

# 颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

DEV_BRANCH="feature/remote-node-local"
PR_BRANCH="feature/remote-node"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  同步到 PR 分支${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 确保在开发分支
if [ "$(git branch --show-current)" != "$DEV_BRANCH" ]; then
    echo -e "${YELLOW}切换到开发分支: $DEV_BRANCH${NC}"
    git checkout "$DEV_BRANCH"
fi

# 获取需要同步的提交（仅代码提交，排除 docs:）
echo -e "${BLUE}查找代码提交...${NC}"
CODE_COMMITS=$(git log "$PR_BRANCH..$DEV_BRANCH" --oneline --grep="^feat\|^fix\|^refactor\|^chore\|^test\|^perf" | grep -v "^docs:" | awk '{print $1}' | tac)

if [ -z "$CODE_COMMITS" ]; then
    echo -e "${YELLOW}没有需要同步的代码提交${NC}"
    exit 0
fi

echo -e "${GREEN}将同步以下提交:${NC}"
git log "$PR_BRANCH..$DEV_BRANCH" --oneline --grep="^feat\|^fix\|^refactor\|^chore\|^test\|^perf" | grep -v "^docs:" | nl

echo ""
read -p "确认同步这些提交到 $PR_BRANCH? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}已取消${NC}"
    exit 0
fi

# 切换到 PR 分支
echo -e "${BLUE}切换到 PR 分支: $PR_BRANCH${NC}"
git checkout "$PR_BRANCH"

# Cherry-pick 代码提交
echo -e "${BLUE}同步代码提交...${NC}"
for commit in $CODE_COMMITS; do
    echo -e "${GREEN}  → $commit${NC}"
    git cherry-pick "$commit" || {
        echo -e "${YELLOW}冲突发生，请手动解决${NC}"
        echo "解决后运行: git add . && git cherry-pick --continue"
        exit 1
    }
done

# 复制最新文档（未跟踪）
echo -e "${BLUE}复制最新文档...${NC}"
git checkout "$DEV_BRANCH" -- docs/node-remote/*.md 2>/dev/null || true

# 确保文档未被跟踪
if git ls-files --error-unmatch docs/node-remote/*.md >/dev/null 2>&1; then
    git rm --cached docs/node-remote/*.md 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  同步完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "PR 分支状态:"
echo -e "  - 代码提交: $(git log "$PR_BRANCH" ^1f837d9 --oneline | wc -l) 个"
echo -e "  - 本地文档: $(ls docs/node-remote/*.md 2>/dev/null | wc -l) 个文件（未跟踪）"
echo ""
echo -e "下一步:"
echo -e "  1. 查看状态: git status"
echo -e "  2. 推送到远程: git push origin $PR_BRANCH"
echo ""
