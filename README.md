# ModelScope Proxy

> 一个 OpenAI 兼容的 API 代理，自动在多个 ModelScope 免费模型之间切换，聚合多个模型的每日免费配额。

## 动机

ModelScope 提供了大量免费模型 API（约 2000 次/天/模型），但每个模型都有独立的每日配额限制。如果只用一个模型，每天只能用 2000 次。但如果你配置 5 个模型，代理会自动按优先级轮换，一个模型配额耗尽自动切换到下一个，从而获得 **5 × 2000 = 10000 次/天** 的免费调用额度。

## 工作原理

```
你的应用 / 客户端                  Proxy                        ModelScope API
     │                              │                              │
     │  POST /v1/chat/completions    │                              │
     │  Authorization: Bearer <key>  │                              │
     │  {"messages": [...]}          │                              │
     │ ──────────────────────────►   │                              │
     │                              │  挑选最高优先级且有配额的模型   │
     │                              │  ──► Qwen2.5-72B 还有 1800 次  │
     │                              │                              │
     │                              │  POST /v1/chat/completions    │
     │                              │  model=Qwen/Qwen2.5-72B...   │
     │                              │  Authorization: Bearer <tk>   │
     │                              │ ────────────────────────────► │
     │                              │  ◄──────────────────────────── │
     │  ◄────────────────────────── │                              │
     │                              │                              │
     │  下次请求: 如果 72B 配额用完   │                              │
     │  ──► 自动降级到 32B ──►       │                              │
     │                              │                              │
```

**关键点**:
- 客户端只需要一个固定的 Base URL 和 API Key
- 实际调用哪个模型由代理决定，用户无感知
- 遇到 429 配额耗尽 → 自动切换到下一个优先级的模型

## 快速开始

### 1. 安装依赖

```bash
cd ~/123456/tmp
pip install -r requirements.txt
```

### 2. 配置

```bash
# 编辑 config.yaml，至少填写以下两项:
#   1. modelscope.api_token — 你的 ModelScope API Token
#   2. models — 至少添加一个模型

# 然后运行交互式模型列表配置:
python3 proxy.py --review-models
```

或者直接编辑 `config.yaml`：

```yaml
modelscope:
  api_token: "你的-modelscope-token"

models:
  - name: "Qwen/Qwen2.5-72B-Instruct"
    priority: 1
    daily_limit: 2000
  - name: "Qwen/Qwen2.5-32B-Instruct"
    priority: 2
    daily_limit: 2000
```

### 3. 启动

```bash
python3 proxy.py
```

### 4. 客户端使用

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-proxy-key",           # config.yaml 里的 proxy.api_key
    base_url="http://127.0.0.1:8000",      # proxy 地址
)

response = client.chat.completions.create(
    model="any",  # 随便填，proxy 会自动选
    messages=[{"role": "user", "content": "你好"}],
)

print(response.choices[0].message.content)
```

或者 curl：

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-proxy-key" \
  -d '{
    "model": "any",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

## 配置详解

```yaml
proxy:
  host: "0.0.0.0"       # 监听地址（0.0.0.0 允许外部访问）
  port: 8000             # 监听端口
  api_key: "sk-xxx"      # 客户端调用时需要提供的 API Key

modelscope:
  api_token: "..."       # 你的 ModelScope Token（必填）
  base_url: "..."        # API 地址（一般不动）

models:
  - name: "Qwen/Qwen2.5-72B-Instruct"   # ModelScope 模型名
    priority: 1                           # 优先级（1=最高，先用这个）
    daily_limit: 2000                     # 每日配额上限

settings:
  max_retries: 3                         # 遇到 429 最多重试几个模型
  model_review_interval_days: 30          # 多久提醒一次审查模型列表
```

## 优先级与切换策略

| 优先级 | 模型 | 配额状态 | 行为 |
|--------|------|----------|------|
| 1 (最高) | Qwen2.5-72B | 还剩 500 次 | ✅ 优先使用 |
| 1 (最高) | Qwen2.5-72B | 已用完 (429) | ❌ 标记耗尽，降级 |
| 2 | Qwen2.5-32B | 还剩 2000 次 | ✅ 自动切换到这里 |
| 2 | Qwen2.5-32B | 也用完了 | ❌ 继续降级 |
| 3 | Qwen2.5-14B | 还剩 2000 次 | ✅ 使用 |
| ... | ... | 全部耗尽 | ⛔ 返回 429 |

## 常用命令

```bash
# 启动服务
python3 proxy.py

# 指定端口
python3 proxy.py --port 8080

# 查看当前配额使用情况
python3 proxy.py --show-usage

# 交互式编辑模型列表（添加/删除模型）
python3 proxy.py --review-models

# 指定配置文件
python3 proxy.py --config /path/to/config.yaml
```

## 推荐的免费模型

以下 ModelScope 模型有免费 API 额度（截至编写时，请自行确认）：

| 模型 | 说明 |
|------|------|
| `Qwen/Qwen2.5-72B-Instruct` | 通义千问 72B |
| `Qwen/Qwen2.5-32B-Instruct` | 通义千问 32B |
| `Qwen/Qwen2.5-14B-Instruct` | 通义千问 14B |
| `Qwen/Qwen2.5-7B-Instruct` | 通义千问 7B |
| `Qwen/Qwen2.5-Coder-32B-Instruct` | 代码专用 32B |
| `Qwen/QwQ-32B-Preview` | 推理模型 32B |
| `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | DeepSeek R1 蒸馏版 |
| `ZhipuAI/glm-4-9b-chat` | 智谱 GLM-4 |

## 模型列表审查提醒

由于 ModelScope 不断有新模型上线，代理会在启动时检查是否超过 30 天未审查模型列表。如果超期，会显示提醒：

```
┌─────────────────────────────────────────────────────────────┐
│  📋 模型列表审查提醒                                        │
│  上次审查距今已超过 30 天                                    │
│  ModelScope 不断有新模型上线，建议定期更新。                 │
│                                                             │
│  运行以下命令审查:                                            │
│    python3 proxy.py --review-models                         │
└─────────────────────────────────────────────────────────────┘
```

运行 `--review-models` 后会进入交互式界面，可以添加新模型、删除旧模型、调整优先级。

## 文件结构

```
~/123456/tmp/
├── proxy.py              # 主服务 (FastAPI + 路由 + CLI)
├── model_manager.py      # 模型池管理 + 配额追踪
├── translator.py         # 格式转换层
├── config.yaml           # 配置文件（你的 Token 和模型列表）
├── requirements.txt      # Python 依赖
├── README.md             # 本文件
├── .model_quota_state.json  # (自动生成) 配额状态持久化
└── .model_review         # (自动生成) 审查日期标记
```

## 注意事项

1. **API Token 安全**: `modelscope.api_token` 是你的 ModelScope 凭证，不要泄露
2. **配额是估计值**: 每个模型实际每日限额以 ModelScope 官方为准，`daily_limit` 默认 2000 仅供参考
3. **不同模型能力不同**: 高优先级用强模型（72B），降级后可能使用较弱模型
4. **流式支持**: 代理完整支持 SSE 流式响应
