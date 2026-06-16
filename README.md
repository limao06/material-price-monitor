# 原料市场均价钉钉通知

本目录提供一个本地触发任务，用来抓取 PP、PE、PC、ABS、亚克力(PMMA)、铜、铝的市场均价并发送到钉钉机器人。

## 运行

先试跑，不发送钉钉：

```bash
python3 outputs/material_price_notifier.py --dry-run
```

输出 JSON 调试信息：

```bash
python3 outputs/material_price_notifier.py --dry-run --json
```

发送到钉钉：

```bash
export DINGTALK_WEBHOOK='https://oapi.dingtalk.com/robot/send?access_token=你的token'
python3 outputs/material_price_notifier.py
```

如果钉钉机器人开启了“加签”，再加：

```bash
export DINGTALK_SECRET='SEC开头的加签密钥'
python3 outputs/material_price_notifier.py
```

## 本地定时

每天 09:30 触发可以用 macOS/Linux cron：

```cron
30 9 * * * cd /path/to/material-price-monitor && DINGTALK_WEBHOOK='https://oapi.dingtalk.com/robot/send?access_token=你的token' python3 outputs/material_price_notifier.py >> work/material-price-notifier.log 2>&1
```

## GitHub Actions 部署

本仓库已包含 `.github/workflows/material-price-notifier.yml`，默认每天北京时间 09:33 自动运行，也可以在 Actions 页面手动触发。

为了规避 GitHub schedule 偶发延迟或丢触发，workflow 还会在北京时间 10:17-15:47 之间每 30 分钟兜底触发一次。脚本会用 `data/material-price-send-log.json` 做每日发送锁，避免同一天重复发送钉钉通知。

1. 在仓库 `Settings -> Secrets and variables -> Actions -> New repository secret` 添加：
   - `DINGTALK_WEBHOOK`：钉钉机器人 webhook
   - `DINGTALK_SECRET`：钉钉加签密钥；如果机器人没开加签，可以不填
2. 在仓库 `Settings -> Actions -> General -> Workflow permissions` 里开启 `Read and write permissions`，否则 workflow 不能把历史 JSON 提交回仓库。
3. 进入 `Actions -> Material Price Notifier -> Run workflow` 手动跑一次，确认钉钉收到消息。
4. 默认首个定时是每天北京时间 09:33。GitHub cron 用 UTC，所以 workflow 里写的是 `33 1 * * *`。

GitHub 运行后会在仓库里维护：

```text
data/material-price-history.json
data/material-price-state.json
data/material-price-send-log.json
```

`material-price-history.json` 会按日期保存每日价格、涨跌额、涨跌幅，钉钉通知默认展示今日均价和 7 天趋势。

Actions 会额外生成并提交两张走势图：

```text
charts/material-trend-7d.png
charts/material-trend-30d.png
```

通知会先发送价格表，再以钉钉 FeedCard 卡片形式发送 7 天和 30 天走势图。图片通过 GitHub raw URL 展示，因此钉钉机器人不需要上传本地图片文件。

## 当前口径

- PP：生意社 PP(拉丝) 参考价
- PE：生意社 LLDPE 参考价
- PC：生意社 PC 参考价
- ABS：生意社 ABS 参考价
- 亚克力：生意社 PMMA 参考价
- 铜：长江 1#电解铜现货均价
- 铝：长江 铝A00 现货均价

塑料涨跌按相邻可用报价对比；铜铝涨跌额来自长江有色页面，涨跌幅按前值反算。钉钉通知展示今日均价和 7 天趋势，完整涨跌数据保存在历史 JSON 中。
