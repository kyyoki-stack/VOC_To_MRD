# 部署说明

## 静态结果展示

`web/index.html`是通用首页，不嵌入既有评论、洞察或报告。`web/examples/cockpit.html`是独立的匿名座舱案例，包含多个品牌与渠道，并明确标为既有示例。页面不依赖远程字体、CDN或前端构建工具。

公开静态发布先执行`python3 build.py --static --output dist`。只托管`dist/`，该模式会直接提示在线采集服务尚未配置，不向不存在的本机API发送研究请求。示例支持原声筛选、证据展开和报告下载。

本机或Docker运行使用`python3 build.py`生成的`web/`；配置执行器后才可提交研究。公开网站发布不等于已经部署云端采集与AI执行服务。

## GitHub Pages发布

`.github/workflows/pages.yml`在main推送后检查构建与证据契约，仅上传`python3 build.py --static --output dist`生成的两个页面。完整仓库、研究运行目录和本机执行器不作为网站产物上传。公开入口与示例使用相对链接，兼容仓库子路径。

GitHub Pages是静态展示层；在线采集、归类、AI洞察、报告和MRD生成仍需另外部署研究服务。

## Docker网页服务

执行`docker compose up -d --build --wait`，打开`http://127.0.0.1:8780`。Python运行环境、页面、匿名案例与报告都在镜像内；Dockerfile使用非root用户，Compose将8780仅发布到宿主本机。

可以使用`VOC_PORT=8781 docker compose up -d --build --wait`改为8781。容器继续监听8780，`VOC_PUBLIC_PORT`同步浏览器发布端口，避免合法请求被Host／Origin校验拒绝。

`/data/research-runs`写入命名卷，容器重建后保留文件；内存任务状态仍无法恢复。健康检查只检查HTTP服务响应，未配置Codex也应健康。不要用`docker compose down -v`保留研究文件，该选项会删除卷。

默认镜像不包含Codex或渠道工具。浏览、筛选、查看证据和下载报告可独立使用；提交新研究会明确提示执行器未就绪。要在容器内执行真实研究，需要另行安装兼容的Codex CLI、配置模型权限和可访问渠道，并在容器环境完成真实采集验证。不要把Mac账号、HOME或Chrome配置自动打包进镜像。

Docker配置参考：[Dockerfile指令](https://docs.docker.com/reference/dockerfile/)、[Compose服务配置](https://docs.docker.com/reference/compose-file/services/)。

## 本机真实研究

运行`python3 app.py`，使用本机Codex账号、模型权限和已配置工具。服务只绑定127.0.0.1；默认8780端口可避免与既有8768页面冲突。新结果写入被Git忽略的`research-runs/`。

不要把监听地址直接改成公网并依赖本机账号开放服务。当前令牌是本机请求保护，并非多用户登录或授权系统。

## 未来在线研究服务

线上全流程需要补齐以下组件，并在独立环境验收：

1. 用户登录、项目隔离、授权和访问控制。
2. 持久化任务队列、阶段进度、取消、退避重试和重启恢复。
3. 服务端模型执行与用量控制；模型密钥存入部署环境。
4. 可部署的渠道连接器、平台授权和正文／评论分页处理。
5. 数据库、报告文件存储、保留期限、删除与导出。
6. 同一批新评论从采集到MRD的完整验证，以及空结果和失败路径。

本机Chrome会话和OpenCLI连接不等于云端采集能力。线上服务应独立验证渠道可用性，不承诺全平台覆盖。
