# Publisher — 上传发布

**状态**: V1.0 部分实现 — Vercel部署已接入workflow，npx PATH问题已通过`shell=True`解决，含1次重试。

## 职责
- 部署HTML到Vercel生成公网URL
- ~~小红书橱窗上架~~ (V2.0)

## 2026-08-10 — 部署健壮性增强（已完成）

**为什么改**: Vercel CLI偶发网络超时或临时故障，当前无重试机制，一次失败就直接返回本地路径。加1次重试可大幅提高部署成功率。

**具体改动**（已完成）:
1. `main.py` — `_deploy_to_vercel` 加一次重试（间隔5秒），第二次失败再fallback到本地路径
2. `main.py` — 增加部署结果的结构化日志（耗时、重试次数）

**恢复条件**: 无需恢复。

## 已知局限
- Python subprocess找不到`npx vercel`（PATH不包含npm全局bin）。已通过`shell=True`解决。
- 当前部署命令：`npx vercel output/deploy/latest --prod --yes`
