# Publisher — 上传发布

**状态**: V1.0 部分实现 — GitHub Pages 部署已接入 workflow(gh-pages 分支:根=最新版,d/日期/=当天永久版);~~小红书橱窗上架~~ (V2.0)

## 职责
- 部署HTML+3张截图到GitHub Pages(gh-pages分支),URL写入state
- 生成3张截图(笔记封面×2 + 商品主图×1),随站点部署,URL写入state
- ~~小红书橱窗上架~~ (V2.0)

## 2026-08-10 — 部署健壮性增强（已完成）

**为什么改**: Vercel CLI偶发网络超时或临时故障，当前无重试机制，一次失败就直接返回本地路径。加1次重试可大幅提高部署成功率。

**具体改动**（已完成）:
1. `main.py` — `_deploy_to_vercel` 加一次重试（间隔5秒），第二次失败再fallback到本地路径
2. `main.py` — 增加部署结果的结构化日志（耗时、重试次数）

**恢复条件**: 无需恢复。

> Vercel 部署已于 2026-08-18 移除(vercel.app 域名国内不可达)。恢复路径:git revert <移除commit> 并还原 _deploy_to_vercel(见 git 历史)。

## 已知局限
- 部署依赖本机代理可用(git http.proxy)与GitHub凭据;失败时降级本地路径、素材消息提示"部署失败"
- GitHub Pages发布有1-2分钟生效延迟
- Python subprocess找不到`npx vercel`（PATH不包含npm全局bin）。已通过`shell=True`解决。
- 当前部署命令：`git push origin gh-pages`（由 utils/ghpages_deploy.py 自动执行，含代理/身份继承）
