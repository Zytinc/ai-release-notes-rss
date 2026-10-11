# AI Release Notes RSS

为没有公开 RSS 的官方产品更新页生成两个标准 RSS 2.0 订阅源，供 Folo 或任意 RSS 阅读器使用。

## 订阅源

- Claude Apps Release Notes：`feeds/claude-apps-release-notes.xml`
- Gemini API Changelog：`feeds/gemini-api-changelog.xml`

## 运行方式

GitHub Actions 每 6 小时执行 `scripts/generate_feeds.py`。脚本仅抓取公开的官方页面，提取发布时间、标题与摘要，采用稳定 GUID 去重，并保留最近 80 条历史条目。

当检测到新更新时，工作流会提交新的 XML 文件。每周额外产生一次低频活动提交，避免公共仓库因长期无活动而导致 GitHub 停用计划工作流。

## 数据来源

- [Claude Apps Release Notes](https://support.claude.com/en/articles/12138966-release-notes)
- [Gemini API Changelog](https://ai.google.dev/gemini-api/docs/changelog)

本仓库不包含账号凭证、Cookie、私有数据或对官方内容的全文镜像。
