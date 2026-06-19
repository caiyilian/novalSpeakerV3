# novalSpeakerV3

基于 OpenCode + oh-my-openagent 的小说对话说话人自动标注工具。

---

## 简介

把小说中形如 `「对话内容」` 的对话，自动标注上对应的说话角色名。

```
输入 (novel.txt)
「这是最后一件了吧？」
「嗯，这里确实有……七十件。多谢惠顾。」

输出 (labeled.txt)
村民
罗伦斯
```

本项目不重新实现 Agent 编排，而是**直接利用 [OpenCode](https://github.com/anomalyco/opencode)（v1.17.8） + [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent)（v4.11.1）** 的多 Agent 能力和自动循环机制，配合 Ollama 本地模型完成标注。

---

## 架构

```
novalSpeakerV3/
├── opencode/                  # OpenCode 源码（v1.17.8，不随本仓库分发）
├── oh-my-openagent/           # oh-my-openagent 源码（v4.11.1，不随本仓库分发）
├── .opencode-home/            # 隔离的 OpenCode 配置目录（运行时生成）
├── .omo/                      # 角色注册表等持久化状态
├── AGENTS.md                  # 多 Agent 协作规则（注入到每个 Agent 上下文）
├── novel.txt                  # 待标注的小说文本
├── labeled.txt                # 标注结果输出
├── answers/                   # 人工标注的参考答案（用于评估）
│   └── 第1卷.txt
├── 方案_*.md                  # 详细设计方案
├── 笔记_*.md                  # 分析与总结
└── run-novel.bat              # 一键启动脚本
```

### 多 Agent 协作

| Agent | 角色 | 说明 |
|-------|------|------|
| **Sisyphus** | 主编排 | 逐批处理对话，决定是否委派子 Agent |
| **Oracle** | 分析专家 | 在独立上下文中深入分析复杂场景 |
| **Explore** | 搜索专家 | 在后文中搜索角色身份线索 |
| **Librarian** | 查证专家 | 维护和查证角色注册表 |

所有 Agent 共用同一模型（`qwen3:4b`），服务器只需加载一个模型。

---

## 前置条件

| 依赖 | 说明 |
|------|------|
| [Bun](https://bun.sh/) | 运行时（>= 1.3.14） |
| [Ollama](https://ollama.com/) | 本地模型服务 |
| qwen3:4b | 推荐模型（也可用其他模型） |

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/caiyilian/novalSpeakerV3.git
cd novalSpeakerV3
```

### 2. 准备依赖

```bash
# 克隆 OpenCode（v1.17.8）
git clone --branch v1.17.8 https://github.com/anomalyco/opencode.git

# 克隆 oh-my-openagent（v4.11.1）
git clone https://github.com/code-yeongyu/oh-my-openagent.git

# 安装 OpenCode 依赖
cd opencode
bun install
cd ..
```

### 3. 配置连接

创建 `ip_config` 文件：

```
OLLAMA_BASE_URL=http://your-ollama-server:11434
OLLAMA_MODEL=qwen3:4b
```

### 4. 放入小说

把要标注的小说放到 `novel.txt`，对话需用 `「」` 括起来。

### 5. 标注

```bash
run-novel.bat
```

或直接运行：

```bash
cd opencode
set OPENCODE_CONFIG_DIR=..\.opencode-home
bun run --cwd packages/opencode dev --dangerously-skip-permissions
```

---

## 配置文件

| 文件 | 作用 |
|------|------|
| `.opencode-home/opencode.jsonc` | OpenCode 主配置（provider、插件、权限） |
| `.opencode-home/oh-my-openagent.jsonc` | oh-my-openagent 插件配置（Agent 模型、Team Mode、ulw-loop） |
| `AGENTS.md` | 多 Agent 协作规则（自动注入到上下文） |

详见 `方案_本地opencode+oh-my-openagent小说标注.md`。

---

## 测试数据

项目包含第一卷小说的完整测试数据：

- **novel.txt** — 3065 行，1349 条 `「」` 对话
- **answers/第1卷.txt** — 手工标注的完整答案

答案格式：`【说话人】「对话内容」`，多可接受答案用 `|` 分隔。

---

## 与旧项目的对比

本项目的定位与 [opencode-novel-loop](https://github.com/caiyilian/opencode-novel-loop) 不同：

| 对比项 | opencode-novel-loop（旧） | novalSpeakerV3（当前） |
|--------|--------------------------|----------------------|
| 实现方式 | Python 独立 CLI + 自己写编排 | 直接利用 OpenCode + oh-my-openagent |
| Agent 管理 | 自己实现 Coordinator/Verifier/Arbiter | oh-my-openagent Team Mode |
| 记忆系统 | 无 | 角色注册表 |
| 自动循环 | 自己实现 | ulw-loop 内置 |
| 代码量 | ~2000 行 Python | 0 行（只有配置文件） |

旧项目的 12 个 Issue 记录和困难案例分析见 `笔记_opencode-novel-loop困难案例.md`。

---

## 许可证

本项目为公开仓库，仅供参考和学习使用。
oh-my-openagent 使用 SUL-1.0 许可证，注意其使用限制。
OpenCode 使用 MIT 许可证。
测试小说为《狼与香辛料》，版权归原作者所有。
