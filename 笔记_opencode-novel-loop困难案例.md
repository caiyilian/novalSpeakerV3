# opencode-novel-loop 项目困难案例与教训总结

> 整理日期：2026-06-19
> 来源：`E:\projects\opencode-novel-loop\` 本地源码 + 设计文档 + 调试记录

---

## 目录

1. [项目定位回顾](#1-项目定位回顾)
2. [架构复杂度问题](#2-架构复杂度问题)
3. [困难案例 1：模型超时 — index=1325](#3-困难案例-1模型超时--index1325)
4. [困难案例 2：Fragile Verifier 重试循环](#4-困难案例-2fragile-verifier-重试循环)
5. [困难案例 3：说话人数目不匹配](#5-困难案例-3说话人数目不匹配)
6. [困难案例 4：身份定位 Agent 超时](#6-困难案例-4身份定位-agent-超时)
7. [核心设计缺陷：没有记忆](#7-核心设计缺陷没有记忆)
8. [V2 方案的设计思考](#8-v2-方案的设计思考)
9. [从 OpenCode 上游 Issue 看到的同类问题](#9-从-opencode-上游-issue-看到的同类问题)
10. [总结：这个项目教会了我们什么](#10-总结这个项目教会了我们什么)

---

## 1. 项目定位回顾

```
opencode-novel-loop (dialoop)
├── 目标: 用 AI 自动标注小说对话的说话人
├── 技术栈: Python + Ollama (OpenAI-compatible API)
├── 默认模型: qwen3:32b (后来尝试 qwen3:4b)
├── GitHub: caiyilian/opencode-novel-loop (私有/未公开)
└── 状态: v0.1.0，早期阶段，有多个未解决问题
```

### 原始方案

```
安装 OpenCode → 安装 openloop 插件 (ralph-loop) →
一条提示词触发自动循环标注
```

但这个方案门槛太高，所以改成了**独立 Python CLI**，直接调 Ollama API。

---

## 2. 架构复杂度问题

### 2.1 六阶段 Agent Pipeline

这个项目的核心架构是一个**复杂的多 Agent 流水线**，每个对话标注要经过：

```
labeler (标注) → risk (风险评估) → verifier (验证) →
identity_locator (身份定位) → identity_resolver (身份解析) →
normalizer (标准化) → arbiter (仲裁) → 写入
```

每个阶段都可能调用 LLM，意味着**标注一段对话可能要调用 3-5 次模型**。

### 2.2 Agent 种类

| Agent | 角色 | 调用模型 |
|---|---|---|
| `labeler` | 标注说话人 | ✅ 是（主标注） |
| `verifier` | 验证标注是否正确 | ✅ 是 |
| `identity_locator` | 在上下文中找身份线索 | ✅ 是 |
| `identity_resolver` | 解析身份 | ✅ 是 |
| `normalizer` | 标准化说话人名称 | ❌ 纯 Python 规则 |
| `arbiter` | 仲裁冲突 | ❌ 纯 Python 逻辑 |

### 2.3 配置文件（`templates/opencode.json`）

```json
{
  "agent_loop": {
    "protocol": "auto",
    "max_tool_steps": 20,
    "context_window_lines": 80,
    "temperature": 0.0,
    "verifier_mode": "on",
    "verifier_temperature": 0.0,
    "verifier_max_tokens": 1200,
    "verifier_retries": 1,
    "identity_mode": "on",
    "identity_lookahead_lines": 120,
    "identity_lookahead_rounds": 2,
    "identity_max_tokens": 1400,
    "require_context_before_submit": true,
    "require_identity_tool_for_temporary_speaker": true
  }
}
```

---

## 3. 困难案例 1：模型超时 — index=1325

### 3.1 现象

来自 `.dbg/` 目录的详细调试记录 `debug-model-timeout-1325.md`：

```
迭代: 1325/1349
批次: index=1324, line=2977
错误: model endpoint request timed out after 4 attempt(s)
```

**每次跑到同一位置就卡死**，清除输出重新跑也卡在同一个地方。

### 3.2 调试过程

| 步骤 | 发现 |
|---|---|
| 检查已成功的 batch | `index=1324 line=2977 text=怎么了吗？` 已写入 `.dialoop/annotations.jsonl` |
| 找出下一个未标注 batch | `index=1325 line=2979 text=啊，不好意思。我最近才读完从南方寄上来的戏曲...` |
| 检查后续上下文 | 包含密集的**引用故事块**：男子/男孩/恶魔/商人/宗教戏剧 |
| 确认超时位置 | `agent_loop._chat` 里 `labeler` 请求超时，**不是 verifier 或 identity 阶段** |
| 超时详情 | `message_count=2`, `has_tools=true`, `timeout_s=30`, 实际耗时 ~30048ms |
| 重试行为 | 同样的请求重试 4 次，每次都超时，没有任何退避策略变化 |

### 3.3 根因

```
这不是 fragile-verifier 重试循环那类 bug。
也不是 Identity Locator / Resolver 超时。
可复现的失败是 labeler 端点的超时，
触发条件是 prompt 中包含密集的引用故事块作为上下文。
```

具体来说：
- 第 2979 行之后的上下文包含大量**引述故事**（戏曲内容），掺杂了多个角色描述（男子、男孩、恶魔、商人）
- 这导致 labeler 的 prompt 变得复杂，模型处理时间超过 30 秒 timeout
- 重试策略只是简单地重复同样请求，没有改变任何输入

### 3.4 暴露的问题

1. **固定超时 30 秒**不够灵活——复杂上下文需要更长时间
2. **重试策略太粗糙**——同一请求重试 4 次，每次都超时，不会简化 prompt
3. **调用链没有超时传播**——labeler 超时后，identity 和 verifier 阶段根本没机会执行
4. **没有退化策略**——超时后没有简化上下文再试

---

## 4. 困难案例 2：Fragile Verifier 重试循环

### 4.1 现象

Verifier 对高风险标注返回 `pass` 但置信度低，Arbiter 认为是 "fragile pass" 并阻塞提交。

### 4.2 代码逻辑

`coordinator.py` 中的 `_fragile_high_risk_pass_reason`：

```python
# 高风险标注 + verifier say pass = fragile
# 需要 stronger disambiguation 才能写
```

`agent_loop.py` 中的重试逻辑：

```python
def _reject_premature_submit_with_context(self) -> dict[str, Any]:
    # 要求模型提供更多上下文证据
```

### 4.3 循环触发条件

```
labeler 标注 "张三" (confidence: low)
  → risk 评估: "high" (因为低置信度)
    → verifier 验证: "pass" (但 confidence: "low")
      → arbiter 判断: "fragile high-risk pass"
        → blocks_submission = True
          → labeler 重试
            → 再次标 "张三" (还是 confidence: low)
              → ... 无限循环
```

### 4.4 修复尝试

`agent_loop.py` 中有专门的函数处理：

```python
def repeated_fragile_review_block(...)
def is_fragile_review_block(...)
def unblock_repeated_fragile_arbiter(...)
```

但这只是 patch，不是根本解决。

### 4.5 暴露的问题

1. **verifier 没有独立的判断标准**——它只是重复 labeler 的判断，而不是真的验证
2. **没有置信度阈值**——low confidence → high risk → fragile pass 是个死锁
3. **降级路径缺失**——连续 N 次 fragile 后应自动接受，而不是无限重试

---

## 5. 困难案例 3：说话人数目不匹配

### 5.1 现象

`local_tools.py` 中有专门的 `SpeakerCountMismatchError`：

```python
class SpeakerCountMismatchError(ToolValidationError):
    def __init__(self, expected_count, received_count, ...):
        ...
        "Submit exactly one speaker per active dialogue only;
         do not submit labels for previous_dialogues, following_dialogues,
         or raw context lines."
```

### 5.2 根因

模型在调用 `submit_labels` 时经常**提交数量不对**的说话人：

- 每一批有 N 条对话，模型应该提交 N 个说话人
- 但模型会把**前文的对话**也算进去，提交 N+1 个
- 或者把**后文的对话**也算进去
- 或者提交的 label 顺序和对话顺序不一致

### 5.3 暴露的问题

1. **模型的计数能力弱**——小模型（qwen3:4b/32b）在数数上不靠谱
2. **上下文设计不合理**——把前文/后文对话和当前对话放在一起，模型分不清哪些需要标注
3. **错误信息传不到模型**——即使返回错误，模型在下一轮仍犯同样错误

---

## 6. 困难案例 4：身份定位 Agent 超时

### 6.1 现象

`identity.py` 中 `IDENTITY_MARKERS` 有非常复杂的正则表达式规则：

```python
IDENTITY_MARKERS = (
    "我叫", "我叫做", "我叫作", "小的名叫", "名叫", "名字叫", "名字是", "我是",
)
NAME_PATTERNS = (
    re.compile(r"(?:我叫做|我叫作|我叫|小的名叫|小的叫|...)([\u4e00-\u9fffA-Za-z0-9·•･\.]{1,20})"),
    re.compile(r"(?:我是|小的是|在下是|本人是)([\u4e00-\u9fffA-Za-z0-9·•･\.]{1,20})"),
)
NON_PERSON_NAME_FRAGMENTS = (
    "城镇", "城市", "村落", "村子", "地方", "教会", "修道院", "商行",
)
PERSON_ROLE_PREFIXES = (
    "旅行商人", "刚入行的旅行商人", "新手旅行商人", "商人", "行商", "领主", "骑士", "老板",
)
```

### 6.2 问题

1. **身份定位 Agent 需要调用 LLM 两次**（locate + resolve），对于复杂上下文很容易超时
2. **正则规则太脆弱**——中文角色名变化太多（"张三"、"张老三"、"三哥"、"三儿"），正则匹配不全
3. **临时身份标签**（"少女"、"老人"、"少年"）被特殊处理，但又经常和其他规则冲突
4. **大段上下文查询**——`identity_lookahead_lines: 120` 意味着每次身份查询要读 120 行上下文，每次都要重新调用 LLM

### 6.3 暴露的问题

1. **依赖正则做身份识别**——在 LLM 时代用正则匹配角色名，说明架构层面没有"角色注册表"
2. **没有缓存**——每次标注都要重新扫描上下文定位身份
3. **"临时身份"处理复杂**——"少女"可能既是角色描述又是称呼，代码里需要大量特殊逻辑来处理边界情况

---

## 7. 核心设计缺陷：没有记忆

### 7.1 问题的本质

这是整个项目**最根本**的问题。从 `agent_loop.py` 的 `run_one_batch` 方法可以清楚看到：

```python
def run_one_batch(self) -> AgentBatchResult:
    initial_batch = self.tools.get_next_dialogue()
    # 每次都是全新的对话，没有任何跨 batch 的记忆
    messages = [
        ChatMessage(role="system", content=system_prompt(self.config.protocol)),
        ChatMessage(role="user", content=batch_prompt(initial_batch, ...)),
    ]
    # ... 调 LLM，标注，写结果
    # 下一轮 batch 完全从头开始
```

### 7.2 后果

| 问题 | 具体表现 |
|---|---|
| **角色名不一致** | 同一角色在不同段落被标成不同名字 |
| **无法解析代词** | 「彼」「彼女」「あの人」每次都要从零推理 |
| **越标越乱** | 长篇小说角色越来越多，准确率不升反降 |
| **重复劳动** | 每次都要重新分析"这个语气是谁" |
| **没有进度概念** | 只有 `labeled.txt` 的行数，没有角色库 |

### 7.3 为什么没有记忆

从架构上追溯原因：

1. **当时的设计思路是"stateless pipeline"**——每个 batch 是独立的，方便并行和重试
2. **qwen3:32b 的 40960 context 不够**——不能把整本小说塞进上下文
3. **Python 没有设计持久化层**——只有 `annotation.jsonl`（标注记录），没有 `characters.json`（角色库）
4. **每次标注只读前后 N 行**——`context_window_lines: 80`，80 行之外的信息全部丢失

---

## 8. V2 方案的设计思考

### 8.1 背景

项目中的 `speaker_labeling_plan_v2.md`（751 行，设计文档）提出了 V2 方案，正是为了解决"没有记忆"的问题。

### 8.2 V2 的核心想法

```
不是"每次独立标注一个 batch"，而是"像人类一样顺序阅读小说"

顺序阅读：
  第1章 → [读、标注、记住角色] → 第2章 → [读、标注、更新记忆] → 第3章 → ...
```

### 8.3 V2 的记忆结构

```
memory_v2/
├── global_summary.json        # 卷级长期摘要
├── chunk_summaries.jsonl      # 每个 chunk 的短期摘要
├── facts.jsonl                # 结构化事实
├── characters.jsonl           # 角色卡片（有名字/稳定身份）
├── mysteries.jsonl            # 可追踪但暂未命名的个体
├── npc_groups.jsonl           # 普通群体/路人
└── entity_events.jsonl        # 实体事件日志
```

角色分三类，避免"把所有不确定台词混成一个未知"：

| 类型 | 含义 | 示例 |
|---|---|---|
| `character` | 有名字或稳定身份 | "张三" |
| `mystery` | 可追踪但未命名 | "神秘黑衣人" |
| `npc_group` | 普通群体/路人 | "群众"、"士兵们" |

### 8.4 V2 每个 chunk 的任务链（6 个子任务）

```
Task A: 初标注 ← 当前 chunk 原文 + 已有角色库
Task B: 短期摘要 ← 刚读完的 chunk
Task C: 长期摘要更新 ← 旧长期摘要 + 新 chunk 摘要
Task D: 新实体发现 ← 发现新角色/mystery/npc_group
Task E: 已有角色卡片更新 ← 更新摘要、对话数、重要性
Task F: 回看补标 ← 修正当前 chunk 中不确定的标注
```

### 8.5 V2 没有实现的原因

1. **太复杂**——6 个子任务，每个都要调 LLM，一个 chunk = 6 次模型调用
2. **串行误差**——Task A 的错误会传播到 Task B/C/D/E/F
3. **prompt 预算难以控制**——候选角色筛选、摘要长度、上下文窗口都需要精细调参
4. **调试困难**——6 个阶段的输出互相依赖，出问题很难定位

---

## 9. 从 OpenCode 上游 Issue 看到的同类问题

在搜索过程中发现了 OpenCode 上游的一些相关 Issue，这些问题在 oh-my-openagent 中已经或正在解决：

### 9.1 Auto-compaction infinite loop (#15533)

```
当 auto-compaction 在模型自然结束回合后触发，
SessionCompaction.process() 无条件注入 "Continue..." 消息，
导致无限循环。
```

**oh-my-openagent 的应对**：ulw-loop 有明确的 `<promise>DONE</promise>` 检测机制，避免无限循环。

### 9.2 Session loop doesn't stop when finish_reason=stop (#11153)

```
模型返回 finish_reason=stop (无 tool calls) 时，
session loop 仍然继续发送请求，不会停止。
```

**影响**：这就是 dialoop 的 `run_one_batch` 中需要自己实现循环检测的原因——上游 OpenCode 本身就有这个问题。

### 9.3 Infinite loop after tool calls complete (#26220)

```
Big Pickle 模型在 tool calls 完成后进入无限循环，
进程存活但不做任何有用的事，CPU 0-2%，内存 500-900MB。
```

**影响**：用 OpenCode 直接跑批量任务时可能会 hang 住，需要超时保护。

---

## 10. 总结：这个项目教会了我们什么

### 10.1 不该做的事（教训清单）

| # | 教训 | 具体表现 |
|---|------|----------|
| 1 | **不要自己写 Agent 编排** | dialoop 的 labeler → verifier → identity → arbiter → 循环，2k+ 行 Python |
| 2 | **不要靠正则做 NLP** | `identity.py` 里几十个正则匹配中文角色名，脆弱且低效 |
| 3 | **不要固定超时时间** | 30s 超时在某些复杂上下文不够用，应该动态调整 |
| 4 | **不要简单重试** | 4 次重试都发同样的请求，纯属浪费 |
| 5 | **不要让模型数数** | 模型计数不靠谱，`SpeakerCountMismatchError` 反复出现 |
| 6 | **不要用低置信度阻塞流水线** | `low confidence → fragile pass → retry` 死循环 |
| 7 | **不要没有记忆** | 每段对话独立标注，角色名不一致、代词解析失败 |
| 8 | **不要设计太复杂的 pipeline** | V2 的 6 阶段任务链过于复杂，没有落地 |

### 10.2 应该做的事（新方案启示）

| # | 启示 | 对应新方案 |
|---|------|------------|
| 1 | **用现成的 Agent 编排** | oh-my-openagent 的 multi-agent + ulw-loop |
| 2 | **LLM 自己处理角色识别** | 角色注册表在 LLM 上下文中自然维护，不用正则 |
| 3 | **Ollama 必须关 stream** | `stream: false`，否则 NDJSON 解析错误 |
| 4 | **所有 Agent 同模型** | 全部用 `qwen3:4b`，单模型省显存 |
| 5 | **用文件持久化记忆** | `.omo/evidence/characters.json` 角色注册表 |
| 6 | **用 AGENTS.md 注入规则** | 不写代码，写规则文件让 Agent 自己读 |
| 7 | **利用 ulw-loop 自动循环** | "没标完就继续"，不用自己写循环 |
| 8 | **利用 progress.json 断点续标** | 记录进度，中断后继续 |

### 10.3 新旧方案对比

```
旧方案 (dialoop)                             新方案 (opencode + oh-my-openagent)
─────────────────────────────                ─────────────────────────────────────
~2000 行 Python 代码                         0 行代码（只有配置文件）
自己写 LLM 调用 + 重试 + 超时                OpenCode 引擎处理
自己写 Agent 编排（labeler/verifier/...）     oh-my-openagent 的 discipline agents
正则匹配角色名                                 LLM 自然理解上下文和角色
每段独立标注，没有记忆                        角色注册表持久化
固定 timeout 30s                              由 OpenCode 管理
4 次简单重试                                  OpenCode 的模型 fallback 链
需要手动管理输出文件                           `.omo/` 自动管理状态
```

### 10.4 关键数字

| 指标 | dialoop 旧方案 | 新方案预期 |
|---|---|---|
| 代码量 | ~2000 行 Python | 0 行（配置文件） |
| 模型调用次数/段 | 3-5 次（labeler + verifier + identity × 2） | 1-2 次 |
| 是否有记忆 | ❌ 无 | ✅ 角色注册表 |
| 中断恢复 | ❌ 无 | ✅ progress.json |
| 循环机制 | Python 自己写 | ulw-loop 内置 |
| 多 Agent 编排 | 自己实现 | oh-my-openagent 内置 |
| 显存占用 | N/A | ~3GB（单模型 qwen3:4b） |

---

## 附录：GitHub Issues 完整记录

通过 `gh` CLI 获取到仓库 `caiyilian/opencode-novel-loop` 的所有 12 个 Issue 完整内容。

### Issue 一览

| # | 状态 | 标题 | 创建时间 |
|---|------|------|----------|
| 1 | ✅ CLOSED | 需要真实 OpenCode 环境验证 dialoop 主循环 | 2026-05-18 |
| 2 | ✅ CLOSED | 阶段 4：实现整卷长跑能力 | 2026-05-19 |
| 4 | ✅ CLOSED | 阶段5方案调整 | 2026-05-20 |
| 6 | ✅ CLOSED | 阶段 5-1：评估基线 + 专有词扫描 | 2026-05-21 |
| 7 | ✅ CLOSED | Fix speaker count mismatch error | 2026-05-22 |
| 8 | ✅ CLOSED | 阶段 5-2：证据化标注 + annotations.jsonl | 2026-05-24 |
| 9 | ✅ CLOSED | 阶段 5-3：风险门控 + Verifier Agent | 2026-05-26 |
| 11 | ✅ CLOSED | 阶段 5-3 并行：annotations 风险/Verifier 汇总报告 | 2026-05-27 |
| 13 | ✅ CLOSED | 阶段 5-3.5 mismatch attribution report | 2026-06-01 |
| 15 | ✅ CLOSED | 阶段 5-4：身份后置查找 + 轻量角色库 / 归一 | 2026-06-04 |
| 17 | ✅ CLOSED | 阶段 6-1：Coordinator 调度骨架 + 子 agent 协议 | 2026-06-06 |
| 19 | ✅ CLOSED | 阶段 6-2：独立 Verifier 与 Arbiter 闭环 | 2026-06-08 |
| 21 | 🔴 OPEN | 阶段 6-3：独立 Identity Locator / Resolver | 2026-06-15 |

### #21（当前开放 Issue）— 阶段 6-3：独立 Identity Locator / Resolver

**状态**：OPEN，最新更新时间 2026-06-19

这是**当前最活跃的 Issue**，也是之前本地调试文件 `debug-model-timeout-1325.md` 对应的来源。

#### Issue 描述

@caiyilian 要求 @nightt5879 实现阶段 6-3：把 Identity Locator / Resolver 从"主 Agent 可调用工具"升级为"Coordinator 调度的独立 LLM Agent 会话"。

#### 关键讨论过程

**nightt5879 的第一版实现（6月16日）**：
- 新增 `IdentityPipelineAgent`，将 Locator/Resolver 升级为 Coordinator 里的独立身份复核路径
- 默认 `--identity-mode auto`：当 labeler 提交临时身份（少女/女孩/少年/老人等）时触发
- 123 tests OK

**nightt5879 的第二版（6月16日）**：
- 补充关键设计：Identity Locator / Resolver 各自通过独立的 OpenAI-compatible model client 调用模型
- 原来的 deterministic 路径只作为 fallback
- 124 tests OK

**nightt5879 的第三版（6月16日）**：
- 新增 `mismatch-attribution` 的 `identity_related` 分类统计
- 便于对比 6-3 前后的 identity 相关错误

**nightt5879 的第四版（6月16日）**：
- 补充 `candidate_ranges` 到 `recovery.blocked_reviews[].identity`
- 让验收时能同时看到 candidate range + same-person 判断 + evidence lines

**nightt5879 的第五版（6月16日）**：
- `run.sh` 显式带上 `--identity-mode auto`
- `test.sh` 自动跑 coordinator-trace / mismatch-attribution / verifier-false-pass / scan-terms

**@caiyilian 的复跑反馈（6月19日）**：
- 跑到 `index=1325 line=2979` 时稳定超时
- 确认不是偶发，不是输出文件状态问题
- 超时发生在首个 labeler 模型请求，还没进入 verifier/identity
- 问题根源：该 batch 的上下文包含密集的**戏曲转述对话块**，模型处理超时

> 这个 Issue 目前仍 OPEN，等待 nightt5879 修复这个稳定超时问题。

### #19（已关闭）— 阶段 6-2 的关键发现

这是**最曲折的一个 Issue**，完整展示了 dialoop 项目的协作模式：

#### 阶段 6-2 目标
- 让 Verifier 成为独立模型会话
- Labeler 与 Verifier 冲突时由 Arbiter 裁决
- 被否决的样本不直接写入 `labeled.txt`

#### 关键指标变化（3 轮迭代）

| 指标 | 6-1 Baseline | 6-2 第一轮 | 6-2 最终轮 |
|---|---|---|---|
| accuracy | — | 85.47% | **87.99%** |
| incorrect | — | 196 | **162** |
| high_risk_verifier_pass | 71 | 76 (变差了) | **34** |

#### 核心故事

1. **第一轮复跑**：6-2 机制接上了，但 `high_risk_verifier_pass` 从 71 升到 76，不降反升
2. **nightt5879 收紧 fragile verifier pass**：增加了短句 + 无 rejected_candidates 的阻断门槛
3. **第二轮复跑卡死**：新门槛在 `index=363 line=886 text=嗯？` 处形成稳定死循环
4. **nightt5879 增加 unblock 机制**：重复被同一门槛阻断 N 次后自动放行，但留审计痕迹
5. **第三轮复跑成功**：指标全面改善，`unblocked_after_repeated_review=1`（只放行了 1 次！）

#### 关键结论
> "6-2 的结构目标已经成立，收益指标也已经明显体现出来。"
> — @caiyilian 在验收评论中

### #15（已关闭）— 阶段 5-4 的关键发现

#### 背景
阶段 5-4 把 Identity Locator/Resolver/Normalizer/Arbiter 做成主 Agent 可调用工具，不是独立 LLM 子 Agent。

#### 核心发现
**工具调用统计**（整卷 1349 条标注）：
- `locate_identity`：5 次调用
- `resolve_identity`：3 次调用
- `record_character`：**0 次**调用
- `normalize_speaker`：**0 次**调用
- `arbitrate_identity`：**0 次**调用

> "主 agent 没学会使用新工具，prompt / tool description 还不够强"

#### @caiyilian 的关键观察
> "现在这个是作为额外工具，而不是子 agent，是让主 agent 来调用这些工具，这样子的话，会不会受到主 agent 的上下文长度限制呢？我当时想用多个 agent 协作，就是觉得一个 agent 的上下文长度有限制，多个 agent 有独立的上下文。"

这个观察直接促成了**阶段 6 的独立 Agent 设计**。

### 从 Issues 中提炼的 8 条额外教训

| # | 教训 | 来源 Issue |
|---|------|-----------|
| 1 | **指标可能先变差再变好**— 6-2 第一轮 `high_risk_verifier_pass` 从 71 升到 76，最终降到 34 | #19 |
| 2 | **新门槛可能造成死循环**— fragile verifier pass 门槛导致 `index=363` 稳定卡死 | #19 |
| 3 | **unblock 机制必须有**— 重试 N 次后应自动放行，但不能静默放过（要留审计痕迹） | #19 |
| 4 | **主 Agent 不会自觉调用工具**— 5 个 identity 工具，只有 2 个被调用，3 个零调用 | #15 |
| 5 | **上下文隔离必须靠独立 Agent**— 工具模式不能解决主 Agent 上下文长度限制 | #15 |
| 6 | **英文 prompt 导致英文输出**— system prompt 写英文诱导模型输出 `Customer`/`Merchant` | #1 |
| 7 | **模型计数不靠谱**— SpeakerCountMismatchError 反复出现，需要 schema 动态约束 | #2, #7 |
| 8 | **超时重试不能简单重复**— 同样的超时请求重试 4 次，每次都白费 | #8, #21 |

### 项目时间线

```
2026-05-18  Issue #1:  阶段 0-3 完成，确立独立 Python CLI 方向
2026-05-19  Issue #2:  阶段 4 整卷长跑（连续跑 4 条正确标注）
2026-05-20  Issue #2:  超时 bug 修复 + 上下文窗口扩展
2026-05-21  Issue #4:  阶段 5 方案调整（多 Agent 方向）
2026-05-21  Issue #6:  阶段 5-1 评估基线
2026-05-22  Issue #7:  Speaker count mismatch 修复
2026-05-24  Issue #8:  阶段 5-2 annotations.jsonl
2026-05-26  Issue #9:  阶段 5-3 风险门控 + Verifier
2026-06-01  Issue #13: 阶段 5-3.5 mismatch attribution
2026-06-04  Issue #15: 阶段 5-4 身份后置（工具调用量为 0 的教训）
2026-06-06  Issue #17: 阶段 6-1 Coordinator 骨架
2026-06-08  Issue #19: 阶段 6-2 Verifier/Arbiter 闭环（3 轮迭代）
2026-06-15  Issue #21: 阶段 6-3 Identity Locator/Resolver（当前 OPEN）
```
