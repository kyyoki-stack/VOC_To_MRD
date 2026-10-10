# 网站架构

## 用户路径

首页输入主题 → 本地任务接口 → 选择 DeepSeek 或 Codex 执行研究 → 校验CSV和报告 → 生成HTML → 用户查看结果与下载。

DeepSeek 路径：独立评论采集服务返回正文和来源 → 模型逐条审核与标注 → 需求和洞察 → 形成数据报告 → 基于报告生成 MRD。原声、日期和来源不由模型生成，模型仅可写入允许的分析字段。采集服务尚需另行接入。

已有案例是静态快照；它支持展示、搜索、渠道筛选、需求证据展开和下载。新主题不复用该案例的评论，必须建立独立项目并真实采集。

## 模块

| 模块 | 文件 | 责任 |
|---|---|---|
| 通用首页 | `web/index.html` | 主题输入、研究状态与可选示例入口；不预载历史评论 |
| 研究示例 | `web/examples/cockpit.html` | 已有原声、需求洞察、简短结论与下载；明确标为既有示例 |
| 入口 | `app.py`、`Dockerfile`、`compose.yaml` | Python直接运行或Docker启动，默认发布8780端口 |
| 任务服务 | `research-core/scripts/serve.py` | 校验请求，建立独立项目，分派研究后端，返回阶段进度与完成／空结果／失败状态 |
| DeepSeek适配器 | `research-core/scripts/deepseek_client.py`、`deepseek_research.py` | 服务端模型调用、评论采集服务适配、分析字段与证据校验、报告及MRD生成 |
| 私有配置与检查 | `.env.example`、`deepseek_tools.py` | 环境变量示例、不显示密钥的配置检查、真实模型连通测试与显式评论导入 |
| 研究工作流 | `research-core/SKILL.md`、`references/` | 采集、审核、AI分析、证据追溯和MRD规则 |
| 渲染器 | `research-core/scripts/render.py` | 校验字段、ID、来源、日期和需求证据关联，生成内嵌数据的HTML |
| 页面构建 | `build.py` | 分别生成通用首页与匿名案例，检查构建一致性；公开静态模式不请求本机API |

渲染器不执行模型推理或联网采集。语义分析和文档由 DeepSeek API 或宿主AI执行；渠道可用性以每次实际采集结果为准。

## 统一研究输入

每个独立项目使用以下文件：

```text
data/feedback.csv             # 匿名原声与语义标注
data/needs.csv                # 需求判断、优先级、证据与验证方法
data/source_audit.csv         # 来源访问、筛选与失败记录
docs/01-数据分析报告.md
docs/02-MRD.md
docs/03-洞察总结.md
```

案例额外提供`data/report_findings.csv`，用于首页的四条简短结论。新研究页面默认从已完成的需求分析展示前三项优先需求，不编造研究结论。

## 接口与任务

- `GET /api/health`：所选后端的配置状态、缺失原因与页面请求令牌；DeepSeek返回模型名及密钥／采集配置是否存在，不返回密钥，也不证明配置实际可用。
- `POST /api/research`：提交2–200字符的主题，返回任务编号。
- `GET /api/research/<id>`：轮询queued／running／completed／empty／failed状态。
- `GET /runs/<id>/research.html`：读取已生成的结果页。

服务校验本机Host、Origin和提交令牌；主题作为数据通过 JSON 传给服务端 DeepSeek／采集接口，或通过stdin传给Codex，不通过Shell执行。Codex使用自动审批与workspace-write沙箱，不关闭审批或沙箱。并发为1，单任务最长30分钟，研究状态存于内存。DeepSeek HTTP错误只返回经过整理的原因，不向页面回显上游错误正文；模型响应丢弃推理过程，凭据不写入任务产物。

Python默认绑定127.0.0.1；Docker通过`--host 0.0.0.0`监听容器网络，并仅映射宿主127.0.0.1。`VOC_PUBLIC_PORT`用于端口映射后浏览器的Host/Origin校验。健康检查只证明网页服务可以响应，不要求研究执行器已配置。

运行时研究目录、登录、原始抓取日志和账号配置不提交。自带案例仅含用户授权发布的匿名记录、分析及来源；历史报告中的相对文件名保留为研究来源记录，案例导出统一使用上述契约文件。
