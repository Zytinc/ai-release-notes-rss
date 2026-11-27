# AI Release Notes RSS

为没有公开 RSS 的官方产品更新页和博客生成标准 RSS 2.0 订阅源，供 Folo 或任意 RSS 阅读器使用。

## 订阅源

- Claude Apps Release Notes：`feeds/claude-apps-release-notes.xml`
- Gemini API Changelog：`feeds/gemini-api-changelog.xml`
- Grok Bot Changelog：`feeds/xai-grok-bot-changelog.xml`
- Manus 产品更新：`feeds/manus-updates.xml`
- Manus 官方博客：`feeds/manus-blog.xml`
- 小宇宙《柠檬拿铁》：`feeds/xiaoyuzhou-lemon-latte.xml`
- 智谱官网新闻：`feeds/zhipu-news.xml`
- Kimi 研究博客：`feeds/kimi-research-blog.xml`
- DeepSeek 研究与动态：`feeds/deepseek-research-news.xml`
- MiniMax 研究博客：`feeds/minimax-research-blog.xml`
- 字节跳动 Seed 官方动态：`feeds/bytedance-seed-updates.xml`
- Sand.ai 研究博客：`feeds/sand-research.xml`
- Kling AI 官方博客：`feeds/kling-blog.xml`
- 通义万相官网博客：`feeds/tongyi-wanxiang.xml`
- Runway Research：`feeds/runway-research.xml`
- HeyGen Research：`feeds/heygen-research.xml`

## 运行方式

GitHub Actions 每 6 小时执行 `scripts/generate_feeds.py`。脚本仅抓取公开的官方页面，提取发布时间、标题与摘要，采用稳定 GUID 去重，并保留最近 80 条历史条目。

当检测到新更新时，工作流会提交新的 XML 文件。每周额外产生一次低频活动提交，避免公共仓库因长期无活动而导致 GitHub 停用计划工作流。

## 数据来源

- [Claude Apps Release Notes](https://support.claude.com/en/articles/12138966-release-notes)
- [Gemini API Changelog](https://ai.google.dev/gemini-api/docs/changelog)
- [Grok Bot Changelog](https://x.ai/changelog/bot)
- [Manus 产品更新](https://manus.im/zh-cn/updates)
- [Manus 官方博客](https://manus.im/zh-cn/blog)
- [小宇宙《柠檬拿铁》](https://www.xiaoyuzhoufm.com/podcast/69d70d4093435f38037d6e0b)
- [智谱官网新闻](https://www.zhipuai.cn/zh/news)
- [Kimi 研究博客](https://www.kimi.ai/zh-hans/blog/)
- [DeepSeek 研究与动态](https://www.deepseek.com/news/)
- [MiniMax 研究博客](https://www.minimax.cn/blog)
- [字节跳动 Seed](https://seed.bytedance.com/zh/)
- [Sand.ai 研究博客](https://sandai.cn/research/)
- [Kling AI 官方博客](https://kling.ai/blog)
- [通义万相](https://tongyi.aliyun.com/wan/)
- [Runway Research](https://runway.com/research)
- [HeyGen Research](https://www.heygen.com/research)

本仓库不包含账号凭证、Cookie、私有数据或对官方内容的全文镜像。
