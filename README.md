# jproxy

> 通用 OpenAI 兼容 API 代理 — 自动在多个模型之间切换，避开单个模型的频率限制。

## 快速开始

```bash
# 直接下载可执行文件（无需 Python）
# 或者自己打包（见下方）

# 首次运行进入初始化向导
./jproxy

# 之后直接启动
./jproxy

# 查看状态
./jproxy status
```

## 自己打包

```bash
pip install -r requirements.txt
pip install pyinstaller

python3 -m PyInstaller --onefile --name jproxy \
  --add-data "proxy.py:." \
  --add-data "start.py:." \
  --add-data "model_manager.py:." \
  --add-data "translator.py:." \
  jproxy_cli.py

# 生成的可执行文件在 dist/jproxy
```

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
  api_key: "sk-your-proxy-key"

upstream:
  base_url: "https://api.openai.com/v1"
  api_key: "sk-..."

models:
  - name: "gpt-4o"
    priority: 1
  - name: "gpt-4o-mini"
    priority: 2
```

## 命令

```bash
jproxy           # 有配置就启动，否则进入向导
jproxy init      # 进入初始化向导
jproxy status    # 查看模型配额状态
```
