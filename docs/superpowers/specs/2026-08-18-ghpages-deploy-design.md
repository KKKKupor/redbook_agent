# Publisher 部署切换 GitHub Pages 设计

**日期**: 2026-08-18
**状态**: 已获用户批准(方案A)
**范围**: 部署产物(HTML+3张图)由 Vercel 切换为 GitHub Pages 承载

## 1. 背景与目标

实测结论:Vercel 的 `*.vercel.app` 域名在中国网络(家庭WiFi+手机流量)不可达——商品链接与素材图片均无法打开。GitHub Pages(`*.github.io`)实测**可达**(用户手机流量已打开测试页验证)。

**目标**:
1. 每日部署产物由 GitHub Pages 承载,商品链接与钉钉图片国内可达
2. 每天一个专属永久链接 + 一个"永远最新"链接(满足用户"每天不同的固定域名且长久保持"需求)
3. 主流程、state、素材消息结构零改动——只有 URL 的值变化

**非目标**:自定义域名、Cloudflare/OSS 等其他承载、Vercel 恢复(README 记录恢复路径)。

## 2. 链接形态

`gh-pages` 分支结构(每次部署写两层):

```
/ (root)  ── index.html + cover/result/product.png + .nojekyll   ← 最新版
/d/YYYY-MM-DD/ ── 同上4文件                                      ← 当天专属,永久保留
```

- 当天专属(笔记商品链接用): `https://KKKKupor.github.io/redbook_agent/d/2026-08-18/`
- 永远最新: `https://KKKKupor.github.io/redbook_agent/`
- 图片: `https://KKKKupor.github.io/redbook_agent/d/2026-08-18/cover.png` 等
- 域名从 `git remote get-url origin` **动态解析**(不硬编码),解析失败降级

## 3. 架构与数据流

```
publisher: 截图3张(不变) → deploy_to_ghpages(deploy_dir, date_str)
                              │ 临时目录 clone gh-pages(--depth 1)
                              │ 组装:root 最新版 + d/日期/ 当天版 + .nojekyll
                              │ commit → push origin gh-pages(走已配代理+凭据)
                              ▼
              返回 {html_url, cover_image_url, result_image_url, product_image_url}

main.py / build_message / state 字段:零改动
```

## 4. 模块设计

### 4.1 新文件 `utils/ghpages_deploy.py`

```python
def derive_pages_urls(remote_url: str, date_str: str) -> dict:
    """由 origin remote URL 推导 Pages 链接。解析失败返回全空串。
    支持 https://github.com/USER/REPO(.git) 与 git@github.com:USER/REPO.git 两种形式。"""

def deploy_to_ghpages(deploy_dir: Path, date_str: str) -> dict:
    """执行部署:临时目录 clone --depth 1 -b gh-pages → 组装 → commit → push。
    返回 URL dict;任一步失败抛异常(调用方降级)。"""
```

部署流程细节:
1. 临时目录 `clone --depth 1 --branch gh-pages <origin>`;分支不存在(首次)→ 临时目录 `git init` + `checkout --orphan gh-pages` 后直接 push(远端无此分支,无需 force)
2. 复制 deploy_dir 的 4 文件(HTML→index.html + 3 PNG)到根与 `d/{date_str}/`;写入 `.nojekyll`
3. `git -C <tmp> config http.proxy`(继承主仓库代理设置)+ user.name/user.email(继承主仓库配置,提交身份与现有一致)
4. `git push origin gh-pages`;完成即删临时目录(异常时也删,finally 保证)
5. 日期参数:`datetime.now().strftime("%Y-%m-%d")`(运行当天)

### 4.2 `agents/publisher/src/main.py` 修改

- 截图之后:调 `deploy_to_ghpages`;成功 → 返回 4 个 URL;抛异常 → 现有降级(本地路径 + 3 空 URL)
- **删除 `_deploy_to_vercel` 函数**(本次改动后不再被调用;恢复 Vercel 的路径记录在 publisher README)
- 不再写 `vercel.json`

### 4.3 其他文件

- `agents/publisher/README.md`:职责/状态更新为 gh-pages 部署;记录 Vercel 恢复路径
- 无其他代码改动(state、main.py、素材消息、workflow 均不动)

## 5. 错误处理矩阵

| 场景 | 行为 |
|---|---|
| clone/push 失败(网络/代理未开/凭据失效) | 抛异常 → 本地路径 fallback + 空图片 URL → 素材消息"部署失败"提示(现有链路,零改动) |
| remote 解析失败 | `derive_pages_urls` 返回空串 → 同上降级 |
| Pages 发布延迟(约1-2分钟) | 消息发出时链接可能未就绪;人工贴稿时早已生效,可接受 |
| 每日08:00运行时代理未开 | 该次降级为本地路径,日报照常(README 记录该依赖) |
| 历史 d/ 目录无限增长(约230KB/天,一年约85MB) | 按用户"长久保持"需求全部保留,不做清理 |

## 6. 测试策略

- `derive_pages_urls`:TDD 纯函数测试——https 形式、ssh 形式、带/不带 .git 后缀、空串/解析失败、日期注入
- `deploy_to_ghpages`:依赖 git+网络,不写自动测试;E2E 验收:
  1. 手工跑一次真实部署 → 检查 gh-pages 分支两层结构正确
  2. **用户手机流量打开当天链接 + 钉钉看图**(决定性验收)
- 现有 14 个测试不回归

## 7. 用户操作(已完成 ✅)

仓库 Settings → Pages → Deploy from a branch → gh-pages + /(root) → Save。已生效,手机已验证可达。

## 8. 附带项

- `output/deploy/latest/` 下 Vercel 遗留文件(`.vercel/`、`.env.local`、`vercel.json`)不再需要——删除需用户确认(红线)
- Vercel 的 xhs-test 项目闲置,是否删除由用户自定
- 旧 `*.vercel.app` 部署 URL 作废(国内不可达,无实际损失)
