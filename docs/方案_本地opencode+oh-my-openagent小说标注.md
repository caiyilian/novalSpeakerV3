# 方案：本地 OpenCode + oh-my-openagent + Ollama 小说对话标注

> 编写日期：2026-06-19（v2 修订）
> 目标：不碰系统安装的 opencode，用本地源码 + 单模型 Ollama + 带记忆的多 Agent，自动标注小说对话说话人
>
> ⚠️ **本文档基于 opencode-novel-loop 项目的全部困难教训修订。**
> 详见 `笔记_opencode-novel-loop困难案例.md` 中的 8 条教训 + 12 个 Issue 记录。

---

## 目录

1. [方案总览](#1-方案总览)
2. [目录结构](#2-目录结构)
3. [隔离运行原理](#3-隔离运行原理)
4. [配置文件详解](#4-配置文件详解)
5. [记忆系统：角色注册表](#5-记忆系统角色注册表)
6. [标注流程](#6-标注流程)
7. [一键启动](#7-一键启动)
8. [与旧方案的对比](#8-与旧方案的对比)

---

## 1. 方案总览

```
┌─────────────────────────────────────────────────────────────────┐
│                    novalSpeakerV3/                               │
│                                                                  │
│  opencode/        oh-my-openagent/       .opencode-home/         │
│  (v1.17.8 源码)   (v4.11.1 源码)         (隔离配置目录)           │
│       │                  │                      │                │
│       └──────┬───────────┘                      │                │
│              │ 本地路径引用插件                   │                │
│              ▼                                   ▼                │
│      ┌──────────────┐                   ┌──────────────┐         │
│      │  opencode    │◄──────────────────│ opencode.    │         │
│      │  引擎        │   读取             │ jsonc        │         │
│      └──────┬───────┘                   └──────────────┘         │
│             │                                                    │
│     Ollama  │  http://{{OLLAMA_HOST}}:11434                        │
│     qwen3:4b│  所有 Agent 共用同一模型                             │
│             ▼                                                    │
│      ┌─────────────────────────────────────────┐                 │
│      │  oh-my-openagent 多 Agent 编排            │                 │
│      │  (Team Mode)                             │                 │
│      │                                          │                 │
│      │  Sisyphus (主编排)  ← qwen3:4b            │                 │
│      │    ├── 自己标注（简单场景）                  │                 │
│      │    ├── 委派 Oracle 分析（复杂场景）          │                 │
│      │    ├── 委派 Explore 搜索（身份后置）         │                 │
│      │    └── 查询 Librarian（角色库查证）          │                 │
│      │                                           │                 │
│      │  Oracle (分析 Agent)  ← qwen3:4b           │                 │
│      │  Explore (搜索 Agent)  ← qwen3:4b          │                 │
│      │  Librarian (查证 Agent) ← qwen3:4b         │                 │
│      │                                           │                 │
│      │  ulw-loop (自动循环)                       │                 │
│      └──────────────────┬──────────────────────┘                 │
│                         │                                         │
│              ┌──────────▼──────────┐                             │
│              │  记忆系统            │                             │
│              │  .omo/evidence/     │                             │
│              │  characters.json     │  ← 角色注册表（持久化）    │
│              │  progress.json      │  ← 标注进度                │
│              └─────────────────────┘                             │
│                                                                  │
│  novel.txt ──────────→ labeled.txt (每行一个人名)                │
│  answers/第1卷.txt ──→ 人工标注的参考答案（用于评估）            │
└─────────────────────────────────────────────────────────────────┘
```

### 核心思路

| 需求 | 方案 |
|---|---|
| **不碰系统 opencode** | `OPENCODE_CONFIG_DIR` 指向本地 `.opencode-home/`，配置/数据/缓存全隔离 |
| **单模型省显存** | 所有 Agent 模型统一设为 `ollama/qwen3:4b`，服务器只需加载一个模型 |
| **多 Agent 独立上下文** | Team Mode：Sisyphus 主编排，Oracle/Explore/Librarian 子 Agent 各有独立上下文 |
| **不依赖大上下文窗口** | 每个 Agent 只处理自己的那部分，不塞整卷小说。用子 Agent 搜索后文身份 |
| **有记忆** | `characters.json` 作为角色注册表，跨 Session 持久化 |
| **全自动** | `ulw-loop`（Ralph Loop）自动循环，"没标完就继续" |
| **规则驱动** | `AGENTS.md` 注入标注规则 + 委派策略到每个 Agent 上下文 |

### ⚠️ 关键风险提醒（来自旧项目教训）

| # | 旧项目教训 | 本方案的应对 |
|---|-----------|-------------|
| 1 | **Agent 不会自觉调用工具/维护状态** — 阶段 5-4 的 5 个工具 3 个零调用 | `AGENTS.md` 必须用强指令、每次启动强制读取角色注册表、标注指令中嵌入"先查角色库，再标"步骤 |
| 2 | **简单重试导致死循环** — fragile verifier pass 造成 `index=363` 稳定卡死 | 利用 oh-my-openagent 的 Todo Enforcer 和默认超时熔断；如果同一对话反复失败，需人工介入 |
| 3 | **模型超时无有效降级** — 固定 30s timeout 重试 4 次全白费 | opencode 自身有超时和 fallback 机制；但仍需监控长时间无响应的情况 |
| 4 | **角色名不统一** — 同一角色被标成「赫萝」「贤狼赫萝」「女孩」 | 角色注册表 + AGENTS.md 强约束："优先使用已注册的角色名，不得创建别名" |
| 5 | **指标先变差再变好** — 新功能可能暂时降低准确率 | 第一次跑完不要轻易否定方案，迭代 2-3 轮再看趋势 |
| 6 | **英文 prompt 导致英文输出** — system prompt 用英文得到 `Customer`/`Merchant` | AGENTS.md 全部用中文，指定简体中文输出 |
| 7 | **上下文长度隔离靠独立 Agent** — 不是靠工具 | oh-my-openagent 的每个 Agent 有独立上下文，这正是你想要的 |
| 8 | **非人物发声需特殊处理** — 「唰唰唰唰唰」等拟声词 | AGENTS.md 中增加"非人物发声"标签规则 |
| 9 | **缺少标注质量验证** — 旧项目有完整的 verifier/arbiter 闭环 | 本方案初期靠人工抽检；后期可考虑加 quality MCP

---

## 2. 目录结构

```
E:\projects\novalSpeakerV3/
│
├── opencode/                          # opencode 源码 (v1.17.8)
│   └── packages/opencode/
│       ├── src/index.ts               # 入口
│       └── package.json               # "dev": "bun run ./src/index.ts"
│
├── oh-my-openagent/                   # oh-my-openagent 源码 (v4.11.1)
│   ├── dist/                          # 编译产物（直接引用）
│   └── package.json
│
├── .opencode-home/                    # ← 隔离的 opencode 配置目录
│   ├── opencode.jsonc                 #   OpenCode 主配置
│   ├── oh-my-openagent.jsonc         #   插件配置（覆写所有 Agent 模型）
│   ├── tui.json                       #   TUI 配置
│   └── log/                           #   日志（隔离）
│
├── .omo/                              # ← oh-my-openagent 状态目录（持久化）
│   └── evidence/
│       ├── characters.json            #   角色注册表（记忆核心）
│       └── progress.json             #   标注进度
│
├── answers/                          # 人工标注的参考答案（来自旧项目 opencode-novel-loop）
│   └── 第1卷.txt                     #   第一卷完整答案，1349 条对话手工标注
├── AGENTS.md                          # 标注规则（自动注入到 Agent 上下文）
├── ip_config                          # Ollama 服务器地址
├── novel.txt                          # 待标注小说
├── labeled.txt                        # 标注结果输出
├── run-novel.bat                      # ← 一键启动脚本
└── 方案_本地opencode+oh-my-openagent小说标注.md   # 本文档
```

---

## 3. 隔离运行原理

### 3.1 关键环境变量

| 环境变量 | 值 | 作用 |
|---|---|---|
| `OPENCODE_CONFIG_DIR` | `E:\projects\novalSpeakerV3\.opencode-home` | 覆盖整个配置目录，不碰 `~/.config/opencode/` |
| `OPENCODE_DISABLE_AUTOUPDATE` | `1` | 禁止自动更新检查 |
| `OPENCODE_DISABLE_PRUNE` | `1` | 禁止自动清理 |

系统原本的 XDG 路径指向：
```
data:   ~/.local/share/opencode/       →  .opencode-home/data/
cache:  ~/.cache/opencode/             →  .opencode-home/cache/
config: ~/.config/opencode/            →  .opencode-home/        ← OPENCODE_CONFIG_DIR
state:  ~/.local/state/opencode/       →  .opencode-home/state/
```

设置 `OPENCODE_CONFIG_DIR` 后，所有路径都落到 `.opencode-home/` 下，**系统里那个 `opencode.exe` 和它的配置完全不受影响**。

### 3.2 本地运行 opencode

```bash
cd E:\projects\novalSpeakerV3\opencode
bun install                              # 安装依赖（首次）
bun run --cwd packages/opencode dev      # 从源码运行
```

opencode 的 `packages/opencode/package.json` 中有：
```json
"dev": "bun run --conditions=browser ./src/index.ts"
```

### 3.3 本地加载 oh-my-openagent 插件

在 `opencode.jsonc` 中直接用**本地文件路径**引用插件：

```jsonc
{
  "plugin": [
    "E:\\projects\\novalSpeakerV3\\oh-my-openagent"
  ]
}
```

opencode 的插件系统支持本地目录路径，oh-my-openagent 的 `dist/` 目录就在源码里，不需要额外编译。

---

## 4. 配置文件详解

### 4.1 `.opencode-home/opencode.jsonc`

```jsonc
{
  "$schema": "https://opencode.ai/config.json",

  // 插件：用本地路径引用 oh-my-openagent
  "plugin": [
    "E:\\projects\\novalSpeakerV3\\oh-my-openagent"
  ],

  // Provider 配置：只用 Ollama
  "provider": {
    "ollama": {
      "baseURL": "http://{{OLLAMA_HOST}}:11434",
      "stream": false   // ← 必须关闭！否则 Ollama 返回 NDJSON 导致 JSON Parse Error
    }
  },

  // 权限：放开以支持批量自动运行
  "permission": {
    "default": "allow"
  },

  // 引用（方便 Agent 理解项目）
  "references": {
    "novel": {
      "path": "E:\\projects\\novalSpeakerV3\\novel.txt",
      "description": "待标注的小说文本"
    },
    "output": {
      "path": "E:\\projects\\novalSpeakerV3\\labeled.txt",
      "description": "标注结果输出文件"
    },
    "registry": {
      "path": "E:\\projects\\novalSpeakerV3\\.omo\\evidence\\characters.json",
      "description": "角色注册表（记忆）"
    }
  }
}
```

### 4.2 `.opencode-home/oh-my-openagent.jsonc`

这个文件最关键——**把所有 Agent 的模型统一覆写为 `ollama/qwen3:4b`**。

```jsonc
{
  // ============================================================
  // 模型配置：所有 Agent 都用同一个 Ollama 模型
  // 这样服务器只需加载一个 qwen3:4b，显存只占一份
  // ============================================================
  "agents": {
    // --- 主编排 Agent ---
    "sisyphus": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },
    "sisyphus-junior": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },

    // --- 规划 Agent ---
    "prometheus": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },
    "metis": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },

    // --- 深度工作 Agent ---
    "hephaestus": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },

    // --- 分析/咨询 Agent ---
    "oracle": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },
    "atlas": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },

    // --- 工具 Agent（快速响应）---
    "explore": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },
    "librarian": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },

    // --- 多模态（用不上但配了不报错）---
    "multimodal-looker": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },

    // --- 团队模式 Agent ---
    "mom": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    },
    "momus": {
      "model": "ollama/qwen3:4b",
      "temperature": 0.1
    }
  },

  // ============================================================
  // 分类（用于任务委派）
  // ============================================================
  "categories": {
    "analyze": { "model": "ollama/qwen3:4b" },
    "deep": { "model": "ollama/qwen3:4b" },
    "quick": { "model": "ollama/qwen3:4b" },
    "ultrabrain": { "model": "ollama/qwen3:4b" }
  },

  // ============================================================
  // 核心功能开关
  // ============================================================

  // Team Mode：多 Agent 独立上下文协作
  // 每个子 Agent 都有自己的独立上下文窗口，不占 Sisyphus 的预算
  "team_mode": {
    "enabled": true,
    "max_parallel_members": 3,
    "tmux_visualization": false     // Windows 没有 tmux，关掉
  },

  // Ralph Loop / ulw-loop：自动循环标注
  "ulw_loop": {
    "enabled": true,
    "max_iterations": 5000,     // 旧项目整卷 1349 条，设大一些防止中途停止
    "check_interval_seconds": 5
  },

  // Todo Enforcer：Agent 空闲时拉回来继续干活
  "todo_enforcer": {
    "enabled": true
  },

  // 默认模式：启动即进入 ultrawork
  "default_mode": "ultrawork",

  // 关闭遥测（本地使用，不需要上报）
  "telemetry": {
    "enabled": false
  },

  // ============================================================
  // ⚠️ 防死循环安全配置（来自旧项目教训）
  // ============================================================

  // 最大连续工具调用次数，防止模型陷入无限重试
  // 旧项目曾在 index=363 遇到 fragile verifier 死循环
  "max_tool_calls_per_step": 30,

  // 如果同一对话连续失败 N 次，跳过并记录
  // 旧项目教训：重试不解决问题时应该跳过，而不是卡死整卷
  "max_retries_per_dialogue": 5,

  // 模型超时时间（秒）
  // 旧项目教训：qwen3:4b 在复杂上下文可能响应很慢
  "model_timeout": 120
}
```

### 4.3 `AGENTS.md`（标注规则 + 记忆系统）

这是整个方案的**灵魂**——它定义了标注规则和记忆系统的使用方式。

```markdown
# 小说对话说话人标注

## 你是谁
你是 **Sisyphus**，oh-my-openagent 的主编排 Agent。
你的任务是领导一个多 Agent 团队，逐段标注小说对话的说话人。

你的团队成员：
- **你自己（Sisyphus）** — 主编排，决定每批对话怎么标
- **Oracle** — 分析专家，负责深入分析复杂上下文
- **Explore** — 搜索专家，负责在后文中搜索角色身份线索
- **Librarian** — 查证专家，负责维护和查证角色注册表

## 任务描述
把 novel.txt 中的对话（「」括起来的内容）标注上对应的说话角色名，
写入 labeled.txt。**这是一部通用小说，不要依赖任何特定作品的角色知识。**

## 输出格式
labeled.txt 每行一个说话人，与 novel.txt 中的对话按出现顺序一一对应。
**不要写对话内容，只写说话人名字。**
```
张三
李四
村民
非人物发声
```

## 执行策略

### 逐批处理流程
每次处理一批对话（建议 1 条），遵循以下决策树：

```
第1步：读取 .omo/evidence/characters.json（角色注册表）
第2步：读取 novel.txt 中当前对话前后各 10-20 行上下文
第3步：判断——这个说话人确定吗？

  ├── ✅ 十分确定（比如已知角色在连续对话）
  │   → 直接写入 labeled.txt
  │   → 更新 characters.json（出场次数+1）
  │   → 输出 <promise>DONE</promise>
  │
  ├── 🤔 不太确定（新角色、代词、短句）
  │   → 使用 team_send_message 或 delegate_task
  │     委派给子 Agent：
  │
  │     ① 委派 Oracle：在独立上下文中分析
  │       Oracle 会读到更广的上下文（前后 30-50 行）
  │       从叙事角度分析谁在说话
  │
  │     ② 如果 Oracle 仍然不确定，委派 Explore：
  │       Explore 会在后文中搜索角色姓名
  │       搜索范围：当前行往后 50-200 行
  │       返回找到的所有可能角色名及行号
  │
  │     ③ 委派 Librarian：
  │       对比角色注册表，查看是否有匹配的已有角色
  │       检查口癖、语气、关系网络
  │
  │   → 综合子 Agent 的结果决定说话人
  │   → 如果是新发现角色，更新 characters.json
  │   → 写入 labeled.txt
  │   → 输出 <promise>DONE</promise>
  │
  └── ❌ 完全不确定（拟声词、环境描写、多人同时发声等）
      → 标记为「非人物发声」或「？？？」
      → 在 progress.json 中备注
      → 输出 <promise>DONE</promise>
```

### 委派原则（什么时候该委派）

| 场景 | 行为 | 原因 |
|---|---|---|
| 已知角色在连续说话 | 直接标，不委派 | 节省时间 |
| 新角色首次出现 | 🚨 **必须委派 Oracle/Explore 去查** | 旧项目教训：不查就会标成「女孩」「男人」 |
| 短句/追问/省略号 | 委派 Oracle 分析上下文 | 单靠一句话无法判断 |
| 代词「彼」「汝」「咱」 | 委派 Librarian 查角色库 | 需要匹配注册表中的口癖 |
| 拟声词「唰唰唰唰唰」 | 直接标「非人物发声」 | 不用查 |
| 角色名不一致 | 委派 Librarian 做归一 | 防止同角色不同名 |

### 委派方式
使用 `delegate_task` 工具或 `team_send_message` 工具：
```
delegate_task(agent="oracle", task="分析第 X 行对话的说话人是谁，上下文是：...")
```

子 Agent 的结果会返回给你，由你汇总决策。**最终标注决定权在你手上。**

## 角色注册表
位置：`.omo/evidence/characters.json`
⚠️ **每次标注前必须先读取！每次标注后必须更新！**

```json
{
  "张三": {
    "firstSeen": "第1章 第23行",
    "gender": "男",
    "traits": ["商人", "谨慎"],
    "speechPatterns": ["……", "嗯"],
    "relations": {"李四": "旅伴"},
    "aliases": ["三哥"],
    "description": "旅行商人"
  }
}
```

## 核心规则

### 规则 1：身份后置优先
如果角色先以「女孩」「少年」「男人」等描述出现，后文揭示姓名，
**必须使用揭示后的姓名**，不能留为「女孩」。

委派 Explore 在后文搜索身份揭示：
- 搜索范围：当前行往后 50-200 行
- 搜索关键词：自称、名字、称呼
- 如果找到 → 用找到的名字
- 如果 200 行后仍未找到 → 用当前最佳推断

### 规则 2：一致性优先
已注册的角色用原名，**不允许创建别名**。

### 规则 3：角色库优先于临时身份
有角色库 → 用角色库里的名字。
没有角色库但推断是具体人物 → 先派 Agent 去找，找到再用。

### 规则 4：不要用临时关系代替稳定身份
- ❌ 村民 →「顾客」「商人」
- ✅ 村民 →「村民」

### 规则 5：短句/追问/省略号
委派 Oracle 分析，不要凭感觉判断。

### 规则 6：非人物发声
拟声词、环境音效 →「非人物发声」

### 规则 7：输出语言
**所有标签必须是简体中文。** 禁止英文。

### 规则 8：模糊情况
完全无法确定 →「？？？」并在 progress.json 备注。
```

---

## 5. 记忆系统：角色注册表

### 5.1 为什么需要记忆

原来的 dialoop 每次标注都是"眼一闭一睁"：

```
读到对话 → LLM 分析 → 写结果 → 下一段 → LLM 从零开始...
                                          ↑
                                    不知道张三前面出现过！
```

结果是：
- **随机的角色名**：同一角色在不同段落被标成不同名字
- **代词失效**：遇到「彼」「彼女」「あの人」只能靠猜
- **越标越乱**：长篇小说的角色越来越多，准确率不升反降

### 5.2 带记忆的流程

```
第1轮：读到「你来了。」→ LLM: "这应该是张三" → 写入 labeled.txt
       同时写入 characters.json: {张三: {gender:"男", traits:["粗犷"]}}

第2轮：读到「嗯，等很久了吗？」→ LLM 查注册表 → 看到张三→
       判断语气不同 → "这是李四" → 写入 labeled.txt
       更新 characters.json: {张三: ..., 李四: {gender:"女", ...}}

第3轮：读到「彼は今日来ないよ」→ LLM 查注册表 →
       注册表有张三和李四 → "彼" 指张三 → 写入 "张三"
       （不用从零推理！）

第N轮：角色注册表越来越完善 → 准确率越来越高
```

### 5.3 记忆的持久化层级

| 位置 | 存储内容 | 更新时机 | 持久性 |
|---|---|---|---|
| `.omo/evidence/characters.json` | 所有已知角色及其特征 | 每标注完一段 | ★★★ 跨 Session |
| `.omo/evidence/progress.json` | 当前标注到第几行 | 每标注完一段 | ★★★ 跨 Session |
| `AGENTS.md` | 标注规则 + 角色注册表路径 | 项目初始化 | ★★★ 永久 |
| Session 上下文 | 当前批次的对话历史 | 每次推理 | ★★ 本次运行 |
| Agent 上下文窗口 | 正在处理的这一段 | 每次推理 | ★ 单次推理 |

### 5.4 中断恢复

```
中断前：
  characters.json 含 15 个角色
  progress.json: {lastProcessedLine: 342, totalLines: 1000}

恢复后：
  1. 读 progress.json → 知道上次标到第 342 行
  2. 读 characters.json → 知道已有的 15 个角色
  3. 从 novel.txt 第 343 行继续标注
  4. 角色注册表继续积累
```

---

## 6. 标注流程

### 6.1 完整流程图

```
启动
  │
  ▼
Sisyphus 读取角色注册表 (characters.json) 和进度 (progress.json)
  │
  ▼ 进入逐批循环
  │
  Sisyphus 读取 novel.txt 的下一段对话，判断说话人确定度
  │
  ├── ✅ 十分确定（已知角色连续说话、明显上下文）
  │   ├── 直接写入 labeled.txt
  │   ├── 更新 characters.json（出场次数+1）
  │   ├── 更新 progress.json
  │   └── 输出 <promise>DONE</promise> → ulw-loop 继续下一批
  │
  ├── 🤔 不太确定（新角色、代词、短句、追问）
  │   │
  │   ├── 委派 Oracle ──→ Oracle 在独立上下文中深入分析
  │   │   │               │ 读更广上下文（前后 30-50 行）
  │   │   │               │ 从叙事角度推断说话人
  │   │   │               │ 返回: 说话人推断 + 证据行号
  │   │   │
  │   │   └── 如果 Oracle 也不确定 ──→ 委派 Explore
  │   │                               │ 在后文搜索身份揭示
  │   │                               │ 范围: 当前行 +50~+200 行
  │   │                               │ 搜索: 自我介绍、称呼、姓名
  │   │                               │ 返回: 找到的角色名 + 行号
  │   │
  │   ├── 委派 Librarian ──→ 查证角色注册表
  │   │   │                  │ 对比口癖/语气/关系网络
  │   │   │                  │ 返回: 匹配结果 + 置信度
  │   │   │
  │   │   └── 所有子 Agent 返回结果
  │   │       Sisyphus 综合决策
  │   │       ├── 确定 → 写入 labeled.txt
  │   │       ├── 发现新角色 → 写入 labeled.txt + 更新 characters.json
  │   │       └── 仍不确定 → 用最佳推断标，在 progress 备注
  │   │
  │   ├── 更新 progress.json
  │   └── 输出 <promise>DONE</promise> → ulw-loop 继续
  │
  └── ❌ 完全不确定（拟声词、环境描写）
      ├── 标「非人物发声」或「？？？」
      ├── 更新 progress.json 备注原因
      └── 输出 <promise>DONE</promise> → ulw-loop 继续

  ↑ 循环直到所有对话标完 ↑
```

### 6.2 ulw-loop 自动循环机制

ulw-loop 是 oh-my-openagent 的核心机制之一，继承自 ralph-loop：

```
Sisyphus 完成一轮标注
       │
       ▼
ulw-loop 检查 Assistant 输出
       │
       ├── 包含 "<promise>DONE</promise>" → 本轮标注完成
       │   ├── 还有对话未标 → ulw-loop 注入 continuation prompt
       │   │   ├── Sisyphus 读取最新 progress.json
       │   │   ├── 继续下一段对话的标注
       │   │   └── 回到 ulw-loop 检查
       │   │
       │   └── 所有对话标完 → 退出
       │
       └── 不包含 → ulw-loop 注入 continuation prompt
              │
              ▼
        Sisyphus 继续当前对话的标注
        （如果 Sisyphus 还在等子 Agent 的结果，子 Agent 继续工作）
              │
              ▼
        回到 ulw-loop 检查
```

这个机制保证了：
- **无人值守**：启动后不用管，它自己会一直标
- **多 Agent 协同**：每个子 Agent 的独立上下文在 ulw-loop 中不会混淆
- **越标越准**：角色注册表不断积累，越往后知识越丰富

### 6.3 启动命令

⚠️ **注意：不要在 `opencode run` 中同时使用 `--model` 和配置文件中的 provider 设置——可能冲突。**
推荐只通过配置文件指定模型，启动命令只传任务描述：

```bash
# 全自动标注（非交互模式，推荐）
opencode run \
  --dangerously-skip-permissions \
  "开始小说对话说话人标注任务。按照 AGENTS.md 中的规则，读取 novel.txt、characters.json、progress.json，从上次进度继续标注。每次标一段对话，更新 labeled.txt、characters.json、progress.json。标完后输出 <promise>DONE</promise>。注意：只写说话人名到 labeled.txt，每行一个，不要写对话内容。"
```

如果需要在命令行覆盖模型：

```bash
opencode run \
  --model ollama/qwen3:4b \
  --dangerously-skip-permissions \
  "开始小说对话说话人标注任务..."
```

交互式启动：

```bash
opencode
> ultrawork
> 开始小说对话说话人标注任务...
```

---

## 7. 一键启动

### 7.1 `run-novel.bat`

```bat
@echo off
chcp 65001 >nul
title Novel Speaker Labeling - Local OpenCode + oh-my-openagent

echo ============================================
echo  小说对话说话人标注系统
echo  引擎: OpenCode v1.17.8 (本地)
echo  插件: oh-my-openagent v4.11.1 (本地)
echo  模型: Ollama qwen3:4b
echo  服务器: http://{{OLLAMA_HOST}}:11434
echo ============================================

:: ===== 隔离配置 =====
set OPENCODE_CONFIG_DIR=E:\projects\novalSpeakerV3\.opencode-home
set OPENCODE_DISABLE_AUTOUPDATE=1
set OPENCODE_DISABLE_PRUNE=1
:: Ollama 必须关 stream，否则 JSON Parse Error
set OPENCODE_OLLAMA_STREAM=false

:: ===== 检查 Ollama 服务 =====
echo.
echo [检查] Ollama 服务状态...
curl -s http://{{OLLAMA_HOST}}:11434/api/tags >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] Ollama 服务不可用！请检查服务器 {{OLLAMA_HOST}}
    pause
    exit /b 1
)
echo [OK] Ollama 服务正常

:: ===== 检查模型 =====
echo [检查] qwen3:4b 模型...
curl -s http://{{OLLAMA_HOST}}:11434/api/tags | findstr "qwen3:4b" >nul
if %ERRORLEVEL% neq 0 (
    echo [警告] qwen3:4b 未在本地找到，将自动拉取...
)

:: ===== 创建隔离配置目录 =====
if not exist ".opencode-home" mkdir ".opencode-home"

:: ===== 进入 opencode 目录并从源码运行（含超时保护）=====
echo.
echo [启动] OpenCode (本地源码)...
echo [注意] 如果标注长时间无响应，opencode 进程将在 30 分钟后自动终止
echo.

cd /d E:\projects\novalSpeakerV3\opencode

:: 使用 timeout 命令防止 opencode 进程挂起（旧项目 issue #26220 教训）
:: 30 分钟无响应自动终止
start /wait /b "" cmd /c "timeout /t 1800 /nobreak >nul & taskkill /f /im bun.exe 2>nul"

bun run --cwd packages/opencode dev ^
    --dangerously-skip-permissions

echo.
echo 标注完成！
pause
```

### 7.2 首次启动前的准备步骤

```bash
# 1. 安装依赖（只做一次）
cd E:\projects\novalSpeakerV3\opencode
bun install

# 2. 创建隔离配置目录
cd E:\projects\novalSpeakerV3
mkdir .opencode-home

# 3. 把 novel.txt 放好（要标注的小说）
# 确保 novel.txt 在 novalSpeakerV3/ 根目录

# 4. 双击 run-novel.bat 运行
```

---

## 8. 与旧方案的对比

### 8.1 架构对比

| 对比项 | 旧方案 (opencode-novel-loop) | 新方案 (本文) |
|---|---|---|
| **实现方式** | Python 独立 CLI + 自己写循环 | 直接用 opencode + oh-my-openagent |
| **代码量** | ~2000 行 Python | **0 行**（只有配置文件） |
| **维护成本** | 自己维护 | 上游维护，直接升级 |
| **多 Agent** | 无（单 Agent 串行） | 多 Agent 并行编排 |
| **记忆** | 无（每次独立） | 角色注册表持久化 |
| **自动循环** | 自己实现 | ulw-loop 内置 |
| **中断恢复** | 无 | progress.json 记录进度 |
| **模型支持** | OpenAI 兼容 API | OpenCode 所有 provider |
| **显存** | N/A（远程 API） | 单模型 qwen3:4b ≈ 3GB VRAM |
| **隔离性** | Python venv 隔离 | OPENCODE_CONFIG_DIR 隔离 |

### 8.2 为什么新方案更好

```
旧方案：Python Agent → 调用 OpenCode → 每次独立标注
        每次都是"盲人摸象"，没有积累
        自己写 Agent 编排 → fragile verifier 死循环
        自己实现超时重试 → 重试 4 次全白费
        自己写角色识别 → 正则匹配中文名脆弱易错

新方案：oh-my-openagent → 多 Agent 编排 → 标注 + 记忆
        越标越准，因为角色注册表在不断积累
        ulw-loop 自动循环，不会卡死在重试循环
        opencode 管理超时和 fallback，不需要自己实现
        LLM 自然理解角色关系，不需要正则
```

### 8.3 需要注意的风险

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| **Ollama 流式问题** | Ollama 返回 NDJSON，opencode 期望单 JSON | `stream: false` |
| **Qwen3:4b 推理能力** | 4B 模型在多 Agent 编排下可能不够强 | 如效果差可换 qwen3:8b；或降 Team Mode 成员数 |
| **256K 上下文** | Qwen3:4b 有 256K，但不建议塞整卷 | 多 Agent 各自只处理小段，天然解决 |
| **oh-my-openagent 许可证** | SUL-1.0，非 MIT | 仅本地使用，不重新分发 |
| **oh-my-openagent 对 Qwen 的警告** | 官方强烈不建议用 Qwen 做 Sisyphus 主编排 | 标注任务比软件工程简单；如果 Sisyphus 编排混乱，减少子 Agent 委派，让 Sisyphus 自己多干 |
| **Agent 可能不委派** | 旧项目经验：工具零调用 | AGENTS.md 用强指令 + 决策树；启动 prompt 明确要求委派 |
| **Team Mode 在 Windows 兼容性** | oh-my-openagent Team Mode 依赖 tmux | `tmux_visualization: false` 关掉 |
| **opencode 挂起** | 旧项目 issue #26220 | 启动脚本加 30 分钟超时 watchdog |
| **Qwen3:4b 处理中/日混写小说** | 小说有日文人名、口癖、对话标记 | Qwen3 本身支持多语言，AGENTS.md 指定统一用简体中文输出 |

---

## 9. 质量控制和问题排查

### 9.1 测试数据

项目已包含来自旧项目 `opencode-novel-loop` 的完整测试数据：

| 文件 | 路径 | 说明 |
|---|---|---|
| 测试小说 | `novel.txt` | 第一卷小说原文，3065 行，包含 1349 条「」对话 |
| 参考答案 | `answers/第1卷.txt` | 手工标注的完整答案，格式为 `【说话人】「对话内容」` |

#### 答案格式说明

答案文件格式：
```
【说话人】「对话内容」
```

- **多可接受答案**: 用 `|` 分隔，例如 `【赫萝|贤狼赫萝】「呜噜噜咕噜噜噜噜！」` 表示三个答案都算对
- **非人物发声**: `【非人物发声】` 用于拟声词、环境音效
- **旁白**: `【旁白】` 用于非角色说话的场景叙述
- **答案与小说行数对齐**: 第 N 个 `【】` 对应 novel.txt 中第 N 个 `「」`

测试方法：标注完成后，逐行对比 `labeled.txt` 和 `answers/第1卷.txt` 的说话人，多可接受答案中匹配任意一个即算正确。

### 9.2 首次运行的检查清单

第一次运行新方案时，建议按以下顺序检查：

1. **确认隔离生效**: 检查 `.opencode-home/` 下是否有日志和缓存文件，同时确认 `~/.config/opencode/` 没有被修改
2. **确认 Ollama 连接**: 执行 `curl http://{{OLLAMA_HOST}}:11434/api/tags` 确认服务正常
3. **检查 AGENTS.md 没有硬编码**: 扫描 AGENTS.md 中是否出现当前小说特定角色名（如「赫萝」「罗伦斯」），如有则改为通用占位名
4. **小样本测试**: 先用 10 条对话试跑，看输出格式是否正确
5. **检查角色注册表**: 跑 10 条后查看 `.omo/evidence/characters.json` 是否有数据

### 9.2 常见问题与处理

| 现象 | 可能原因 | 处理方法 |
|---|---|---|
| **opencode 启动后无响应** | opencode 挂起（旧项目 issue #26220） | 等待超时自动终止，然后重启 |
| **labeled.txt 一直没有新内容** | ulw-loop 循环未触发 | 检查是否输出了 `<promise>DONE</promise>`；如已输出说明循环认为完成，需检查 progress.json |
| **characters.json 始终为空** | Agent 没有执行角色注册表更新逻辑 | 加强 AGENTS.md 中的指令；在启动 prompt 中显式要求 |
| **角色名不统一** | Agent 没有查角色注册表 | 检查 AGENTS.md 中"一致性优先"规则是否明确 |
| **出现英文标签** | 模型输出语言不受控 | 确认 AGENTS.md 中"输出简体中文"规则到位 |
| **同一对话反复重试后跳过** | 模型无法判断该对话的说话人 | 这是正常行为——宁可跳过也不要硬标 |
| **Qwen3:4b 效果不满意** | 4B 模型推理能力有限 | 可以尝试 `qwen3:8b` 或 `qwen3:32b`（如有足够显存） |

### 9.3 质量控制建议

当前方案没有内置 Verifier/Arbiter（旧项目花了大量精力做的部分），因此建议：

1. **定期抽检**: 每标完一章，人工抽查 10-20 条标注
2. **建立参考答案**: 像旧项目一样维护 `answers/` 目录，用于评估准确率
3. **如果准确率低于 85%**: 检查 AGENTS.md 规则是否不够清晰，或模型是否需要升级
4. **如果频繁死循环**: 考虑关闭 ulw-loop 的自动重试，改为半自动模式（每次标一段后等人确认）

### 9.4 回滚方案

如果新方案效果不如预期，可以随时切换回旧方案：

1. **旧方案 (dialoop)**: 仍然在 `E:\projects\opencode-novel-loop\` 可用
2. **系统 opencode**: 本方案完全不碰系统安装，系统里的 `opencode.exe` 和 `oh-my-opencode` 插件保持原样

---

## 附录：参考文档

| 文档 | 位置 |
|---|---|
| oh-my-openagent Ollama 配置 | `oh-my-openagent/docs/reference/configuration.md` |
| oh-my-openagent Ollama 排错 | `oh-my-openagent/docs/troubleshooting/ollama.md` |
| oh-my-openagent 安装指南 | `oh-my-openagent/docs/guide/installation.md` |
| oh-my-openagent Team Mode | `oh-my-openagent/docs/guide/team-mode.md` |
| opencode 配置参考 | `opencode/.opencode/opencode.jsonc` |
| 旧项目 dialoop | `E:\projects\opencode-novel-loop\dialoop\` |
| 服务器配置 | `ip_config` |
