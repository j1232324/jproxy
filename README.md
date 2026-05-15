# jproxy

> 通用 OpenAI 兼容 API 代理 — 自动在多个模型之间切换，避开单个模型的频率限制。

## 这是什么

很多 API 提供商有分钟频率限制（RPM），单个模型调太多次会返回 429。
jproxy 让你配一堆模型，遇到 429 自动换下一个，冷却完自动切回来。

**不是累加每日总额度**，只是让请求更平滑，不被频率限制卡住。

## 工作原理

```
你的应用                    jproxy                         上游 API
  │                          │                              │
  │  POST /chat/completions   │                              │
  │  Authorization: Bearer X  │                              │
  │ ─────────────────────►    │                              │
  │                          │  选最高优先级模型 → 转发      │
  │                          │  遇到 429 → 冷却 30s → 换下一个
  │                          │  冷却完 → 自动切回高优模型    │
  │  ◄─────────────────────  │                              │
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化配置
python3 start.py
```

客户端使用：

```python
from openai import OpenAI
client = OpenAI(
    api_key="你的代理密码",
    base_url="http://127.0.0.1:8000",
)
print(client.chat.completions.create(
    model="any",
    messages=[{"role":"user","content":"你好"}]
).choices[0].message.content)
```

## 配置

```yaml
proxy:
  host: "0.0.0.0"
  port: 8000
  api_key: "sk-your-proxy-key"    # 客户端用的密码

upstream:
  base_url: "https://api.openai.com/v1"   # 上游 API 地址
  api_key: "sk-..."                       # 上游 API Key

models:
  - name: "gpt-4o"
    priority: 1
  - name: "gpt-4o-mini"
    priority: 2

settings:
  max_retries: 3
```

## 命令

```bash
python3 start.py               # 初始化 + 启动
python3 start.py --quick       # 跳过向导直接启动
python3 start.py --reset       # 重置配置
python3 proxy.py --show-usage  # 查看使用情况
```
