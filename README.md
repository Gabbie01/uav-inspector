# uav-inspector

反无人机设备巡检记录 → 结构化运维报告 自动生成器。

输入现场巡检日志（射频侦测 / 雷达+视觉 / 无线电压制 / 激光 四类设备），
输出带风险分级、故障归因和处置动作的 Markdown 运维报告。

---

## 为什么做这个项目

这不是一个「调用一下大模型 API」的玩具。它复刻的是低空安全/反无人机行业里
真实存在、但很少有人用工程化方式做掉的一环：**现场巡检数据的结构化与报告自动化**。

设计上的三条硬规矩（也是面试时最值得讲的三点）：

1. **确定性的部分用代码，判断力的部分才用模型。**
   日志解析、设备类型推断、风险统计、证据校验全部在代码里完成。
   模型只负责它真正擅长的：跨记录归因、风险定级、处置建议。

2. **模型输出必须过 schema 校验，校验失败让模型自己修。**
   不是把模型返回的字符串直接塞进报告，而是 Pydantic 强校验 + 修复重试。

3. **事实校验闸门：模型不许编造。**
   模型可能虚构设备编号或伪造证据行。代码会逐条比对日志，
   剔除虚构设备、把对不上的证据替换成真实日志行，并在报告里标注数据质量问题。

---

## 快速开始

```bash
cd ~/projects/uav-inspector

# 1. 装依赖（uv 会自动建 .venv）
make install

# 2. 离线演示：完整跑通解析 -> 模型 -> 校验 -> 渲染，不需要 API Key
make demo

# 3. 配置真实模型
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 4. 自检：检查配置和 API 连通性
make doctor

# 5. 用真实模型生成报告
make generate
```

输出默认打印到屏幕，也可以写文件：

```bash
uv run uav-inspect generate data/samples/inspection_2026-10-28.log \
    --site "深圳-某低空防护示范点" \
    --output reports/2026-10-28.md
```

---

## 架构

```
data/samples/inspection_*.log
        │
        ▼
   parser.py        正则解析 + 关键词先验定级  ──→  LogRecord[]
        │                                        (纯确定性)
        ▼
   prompts.py       组装角色设定 + 结构化上下文 + 输出 schema
        │
        ▼
   llm.py           OpenAI 兼容客户端
        │             ├─ 重试 + 指数退避（限流/超时/5xx）
        │             ├─ json_object 约束输出
        │             └─ Pydantic 校验失败 → 回灌错误让模型重写
        │
        ▼
   report.py        ★ 事实校验闸门
        │             ├─ 剔除模型虚构的设备编号
        │             ├─ 证据行必须能在日志中匹配，否则替换为真实行
        │             └─ 合并代码计算的客观统计（不采信模型给的数字）
        │
        ▼
   render.py        Markdown / 纯文本渲染
        │
        ▼
   InspectionReport
```

模块职责：

| 模块 | 职责 | 是否依赖模型 |
|---|---|---|
| `config.py` | 环境变量/`.env` 配置，`SecretStr` 保护密钥 | 否 |
| `models.py` | Pydantic 数据模型 + 风险等级 + 设备类型 | 否 |
| `parser.py` | 日志解析、设备类型推断、关键词先验定级 | 否 |
| `prompts.py` | 提示词模板、修复提示词 | — |
| `llm.py` | 客户端、重试、结构化输出、校验修复、离线 FakeLLM | 是 |
| `report.py` | 编排 + 事实校验 + 统计合并 | 部分 |
| `render.py` | Markdown / 纯文本渲染 | 否 |
| `cli.py` | `generate` / `demo` / `doctor` | 部分 |

---

## 支持的模型服务

全部走 OpenAI 兼容协议，改 `.env` 里的 `LLM_BASE_URL` 和 `LLM_MODEL` 即可切换：

| 服务 | base_url | 备注 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | 性价比最高，适合练手 |
| Moonshot | `https://api.moonshot.cn/v1` | 长文本 |
| 阿里百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 通义千问 |
| SiliconFlow | `https://api.siliconflow.cn/v1` | 模型多 |
| OpenAI | `https://api.openai.com/v1` | 官方 |

---

## 测试

```bash
make test        # 单元测试，完全不联网
make lint        # ruff
make typecheck   # mypy 严格模式
```

测试用 `FakeLLM` 替换真实模型，因此 CI 里不需要任何密钥，也不会产生 API 费用。

---

## 目录结构

```
src/uav_inspector/     包源码
tests/                 pytest 用例
data/samples/          样例巡检日志
reports/               生成结果（git 忽略）
.env.example           配置模板
Makefile               常用命令快捷方式
```

---

## 后续规划

- [ ] 接入 `dvc` 做数据版本管理，巡检记录可追溯
- [ ] 报告导出 PDF / 微信企业格式
- [ ] 按设备维度做历史趋势对比，识别慢性劣化
- [ ] 接入向量检索：把历史工单作为 few-shot 样例喂给模型
- [ ] 视觉侧扩展：无人机小目标检测（YOLO + TensorRT 边缘部署）

---

## 说明

本项目为个人作品集项目，用于展示 LLM 应用工程化能力。
日志样例为虚构数据，不涉及任何真实客户、涉密项目或厂商产品。
