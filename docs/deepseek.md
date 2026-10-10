# DeepSeek 配置

本项目支持 DeepSeek 服务端分析，默认模型为 `deepseek-v4-pro`。评论审核关闭思考模式，需求洞察与 MRD 开启思考模式。模型通过官方 `https://api.deepseek.com/chat/completions` 接口调用，支持 JSON 输出；只存最终分析，不存推理过程。

模型名可通过 `DEEPSEEK_MODEL` 调整，例如 `deepseek-flash`。可用模型和参数以 [DeepSeek 官方文档](https://api-docs.deepseek.com/) 为准。

## 1. 在本机填写密钥

首次配置时将 `.env.example` 复制为 `.env`。已有 `.env` 时直接编辑，避免覆盖原配置。

```dotenv
VOC_RESEARCH_BACKEND=deepseek
DEEPSEEK_API_KEY=在本机填写你的密钥
DEEPSEEK_MODEL=deepseek-v4-pro
VOC_COLLECTOR_URL=
VOC_COLLECTOR_TOKEN=
```

从 [DeepSeek 开放平台](https://platform.deepseek.com/) 创建 API 密钥并确认账户额度。不要将密钥发到聊天、写入前端、提交 GitHub，或放进镜像。`.env` 已被 Git 和 Docker 构建忽略；Compose 只在运行时向服务端传入。

```bash
python3 deepseek_tools.py check
python3 deepseek_tools.py check --live
```

第一条只检查配置是否存在，不显示密钥，不请求模型。第二条会进行一次极小的真实 API 调用并产生模型费用；通过只说明模型连通，不说明评论采集可用。401、402、429 分别提示认证失败、余额不足、请求限流；瞬时限流和服务错误最多重试两次。

## 2. 接入真实评论采集

**DeepSeek 聊天 API 不提供本项目所需的平台评论采集。** 当前已实现采集服务适配接口，仓库尚未附带或部署该服务。没有采集服务时，网页提交会返回明确的未配置提示，不会制造评论或把历史案例作为新结果。

`VOC_COLLECTOR_URL` 需要填写你控制的 HTTPS 采集接口，可选的 `VOC_COLLECTOR_TOKEN` 通过服务端 Bearer 请求头发送。不要把平台搜索页或帖子地址填在这里。禁止使用带账号、查询参数或重定向的地址。

接口接收 POST JSON：

```json
{"topic": "待研究产品与主题", "max_comments": 60}
```

响应为以下结构，示例文字只说明字段，并非真实研究数据：

```json
{
  "comments": [
    {
      "quote": "这里放匿名化后的真实评论原文",
      "source_url": "https://example.com/comment/123",
      "platform": "实际渠道名",
      "published_at": "",
      "brand": "",
      "model": "",
      "software_version": "",
      "source_title": "实际来源标题"
    }
  ],
  "sources": [
    {
      "url": "https://example.com/comment/123",
      "status": "已获取评论正文",
      "decision": "本次实际读取评论；身份未独立核实"
    }
  ]
}
```

采集服务负责真实访问、平台授权、分页、匿名化和访问记录；必须使用真实评论正文，不能返回搜索摘要、宣传文案或模型生成原声。未知日期、车型和版本留空，不推断；已知日期使用 `YYYY-MM-DD`。不返回姓名、账号、头像、联系方式或 Cookie。评论最多60条、来源最多60条、响应最多5MB，单次请求最长180秒。

每条评论 URL 必须有对应来源记录。空结果仍需返回 `comments: []` 和包含访问失败原因的 `sources`；搜索失败没有 URL 时可留空。配置项存在不等于采集服务或平台已验收。

后端按去除空白后的完整文本去重，保留原文及来源元数据；模型只能填分析字段。需求必须引用已纳入的原声编号。模型分析先形成数据报告，再由该报告生成11章 MRD，最后校验并生成独立 HTML；不会调用既有座舱案例补样本。

## 3. 启动或重启

```bash
docker compose up -d --build --wait
```

打开 `http://127.0.0.1:8780/`。修改 `.env` 后需重新执行上述命令，单纯刷新网页不会更新容器环境。Python 直接运行可执行 `python3 app.py`，修改配置后重启进程。

`GET /api/health` 返回模型名、分析和采集是否已配置及缺失原因，不返回密钥。`available: true` 仅代表配置项齐全，真实有效性在执行时确认。

## 已有评论文件可以先分析

尚未接通采集时，可显式提供符合上述响应格式的匿名评论 JSON：

```bash
python3 deepseek_tools.py analyze --input /path/to/comments.json --topic '产品与研究主题'
```

只需 DeepSeek 密钥。结果存入新的 `research-runs/<id>/`，包含 CSV、Markdown 报告、MRD 和可直接打开的 `research.html`。报告会说明本次分析的是输入文件，没有重新联网采集。不要将说明字段的示例 JSON 当成真实数据测试研究效果。

## 公网部署现状

GitHub Pages 仍是静态展示页，添加模型密钥不会让它自动运行后端。本机 Docker 配置不会同步到公网。要让线上回车执行新研究，还需部署评论采集服务与云端后端，配置运行时密钥、任务访问控制，再连接前端 API 地址。当前本机 Host/Origin 校验保留，不直接开放公网。

代码测试使用合成数据和模拟响应；真实 DeepSeek 质量、渠道覆盖、耗时和公网完整流程需要有密钥与实际服务后另行验收。
