# IPTV Merge

每 6 小时通过 GitHub Actions 抓取多个公开电视直播列表，规范化频道信息、剔除非法/内网 URL、按频道去重并保留最多 4–8 条备用线路。生成的列表发布至 `main/output/`，并覆盖更新 `live` 滚动 Release 资产。

> **不是直播流代理。** Fastly jsDelivr 只负责下载订阅文本；视频连接直接由播放器发起。GitHub 托管 Runner 不适合可靠地给国内地区受限源或 IPv6 源做统一测速，因此当前**不做视频流连通性/带宽测试**，入选不代表可用。请以本地实际播放为准。

## 订阅地址

| 分类 | GitHub Release（约每六小时更新） | Fastly jsDelivr（可能存在 12 小时缓存） |
|---|---|---|
| 全部频道 | [all.m3u](https://github.com/Scluzlep/iptv-merge/releases/download/live/all.m3u) | [all.m3u](https://fastly.jsdelivr.net/gh/Scluzlep/iptv-merge@main/output/all.m3u) |
| 国内 | [china.m3u](https://github.com/Scluzlep/iptv-merge/releases/download/live/china.m3u) | [china.m3u](https://fastly.jsdelivr.net/gh/Scluzlep/iptv-merge@main/output/china.m3u) |
| 国际/港澳台 | [global.m3u](https://github.com/Scluzlep/iptv-merge/releases/download/live/global.m3u) | [global.m3u](https://fastly.jsdelivr.net/gh/Scluzlep/iptv-merge@main/output/global.m3u) |
| FAST/影视轮播/主题频道 | [loop.m3u](https://github.com/Scluzlep/iptv-merge/releases/download/live/loop.m3u) | [loop.m3u](https://fastly.jsdelivr.net/gh/Scluzlep/iptv-merge@main/output/loop.m3u) |
| IPv4 | [ipv4.m3u](https://github.com/Scluzlep/iptv-merge/releases/download/live/ipv4.m3u) | [ipv4.m3u](https://fastly.jsdelivr.net/gh/Scluzlep/iptv-merge@main/output/ipv4.m3u) |
| IPv6 | [ipv6.m3u](https://github.com/Scluzlep/iptv-merge/releases/download/live/ipv6.m3u) | [ipv6.m3u](https://fastly.jsdelivr.net/gh/Scluzlep/iptv-merge@main/output/ipv6.m3u) |

[查看滚动 Release](https://github.com/Scluzlep/iptv-merge/releases/tag/live) · [运行 Actions](https://github.com/Scluzlep/iptv-merge/actions/workflows/update.yml) · [统计 JSON](https://github.com/Scluzlep/iptv-merge/blob/main/output/stats.json)

## 上游

数据源配置位于 [`sources.json`](sources.json)，包括：

- [Guovin/iptv-api](https://github.com/Guovin/iptv-api) 的 IPv4/IPv6 发布列表（`gd` 分支）
- [fanmingming/live](https://github.com/fanmingming/live) 的综合、IPv6、ITV 频道
- [YanG-1989/m3u](https://github.com/YanG-1989/m3u) 的综合列表
- [Nekori/TV](https://github.com/Nekori/TV) 的综合列表
- [iptv-org/iptv](https://github.com/iptv-org/iptv) 的全球频道、Pluto/Samsung FAST 和影视/动漫/经典主题分类

每个上游独立请求，失败不会中断其他成功的上游；全部或多数上游不可用时拒绝覆盖既有发布。程序根据电视台名称识别和分组，频道名相同但 URL 不同的备用线路会保留（有数量上限）；不承诺覆盖全部地市县、可播放或版权授权。

**IPv4 / IPv6 分表含义**：IP 字面量按 IP 版本识别，域名通过构建时 DNS A / AAAA 记录分类。DNS 结果不代表流实际可连通或已测试速度，双栈域名可能同时列入两份文件，解析失败的域名仅保留于主题列表。

`loop.m3u` 包含 FAST 和影视/剧集/动漫主题电视台，不意味着所有频道都支持点播或一定是 24 小时循环轮播。

## 更新与自定义

在 Actions 里手动触发 **IPTV merge and rolling release**，或等待定时任务（UTC 00:17 / 06:17 / 12:17 / 18:17）。可编辑 `sources.json` 增删上游、修改 `priority` 或 `scope`（`china`、`global`、`loop`）。

运行脚本：

```bash
python -m unittest discover -s tests -v
python scripts/merge.py
```

纯 Python 标准库，无需 API Key。工作流需要 `GITHUB_TOKEN` 的 `contents: write` 权限；若仓库设置中禁用了 Actions 写入权限，请前往 Settings → Actions → General 修改权限。发布状态可从 `output/stats.json` 核实。

所有视频源归原提供方所有，尊重来源条款与适用法律。该项目只整理公开索引，不重传视频，不保证地域可用性。
