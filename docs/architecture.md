# 网站架构

## 用户路径

首页输入主题 → 本地任务接口 → Codex执行研究 → 校验CSV和报告 → 生成HTML → 用户查看结果与下载。

已有案例是静态快照；它支持展示、搜索、渠道筛选、需求证据展开和下载。新主题不复用该案例的评论，必须建立独立项目并真实采集。

## 模块

| 模块 | 文件 | 责任 |
|---|---|---|
| 通用首页 | `web/index.html` | 主题输入、研究状态与可选示例入口；不预载历史评论 |
| 研究示例 | `web/examples/cockpit.html` | 已有原声、需求洞察、简短结论与下载；明确标为既有示例 |
| 入口 | `app.py`、`Dockerfile`、`compose.yaml` | Python直接运行或Docker启动，默认发布8780端口 |
| 任务服务 | `research-core/scripts/serve.py` | 校验请求，建立独立项目，调用Codex，返回完成／空结果／失败状态 |
| 研究工作流 | `research-core/SKILL.md`、`references/` | 采集、审核、AI分析、证据追溯和MRD规则 |
| 渲染器 | `research-core/scripts/render.py` | 校验字段、ID、来源、日期和需求证据关联，生成内嵌数据的HTML |
| 页面构建 | `build.py` | 分别生成通用首页与匿名案例，检查构建一致性；公开静态模式不请求本机API |

渲染器不执行模型推理或联网采集。语义分析和文档由宿主AI执行；渠道可用性以每次实际采集结果为准。

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

- `GET /api/health`：本机CLI可用性与页面请求令牌；不证明账号、模型权限或渠道可用。
- `POST /api/research`：提交2–200字符的主题，返回任务编号。
- `GET /api/research/<id>`：轮询queued／running／completed／empty／failed状态。
- `GET /runs/<id>/research.html`：读取已生成的结果页。

服务校验本机Host、Origin和提交令牌；主题作为数据通过stdin传给Codex，不通过Shell执行。使用自动审批与workspace-write沙箱，不关闭审批或沙箱。并发为1，单任务超时30分钟，研究状态存于内存。

Python默认绑定127.0.0.1；Docker通过`--host 0.0.0.0`监听容器网络，并仅映射宿主127.0.0.1。`VOC_PUBLIC_PORT`用于端口映射后浏览器的Host/Origin校验。健康检查只证明网页服务可以响应，不要求研究执行器已配置。

运行时研究目录、登录、原始抓取日志和账号配置不提交。自带案例仅含用户授权发布的匿名记录、分析及来源；历史报告中的相对文件名保留为研究来源记录，案例导出统一使用上述契约文件。
